"""
CarbonChain — satellite.py  v2.0
=================================
Integração com Sentinel-2 via Copernicus Data Space
Pipeline completo de MRV por satélite para fazendas no Cerrado.

Bandas usadas:
  B04 (Red)    — cálculo NDVI
  B08 (NIR)    — cálculo NDVI + biomassa
  B11 (SWIR1)  — umidade do solo / matéria orgânica (VM0042)
  B12 (SWIR2)  — análise SOC + discriminação de cobertura

Outputs:
  data/sample_farm/mapa_ndvi.png        — mapa visual NDVI + SWIR
  data/sample_farm/resultado_sat.json   — JSON para mrv_calculator.py

Uso:
  python mrv/satellite.py                    # modo teste local
  python mrv/satellite.py --farm itumbiara  # fazenda específica
  python mrv/satellite.py --api             # dados reais Copernicus
"""

import os
import json
import argparse
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from scipy.ndimage import gaussian_filter
from matplotlib.path import Path as MplPath

# Raiz do repositório e carregamento automático do .env
ROOT = Path(__file__).resolve().parent.parent
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env')
except ImportError:
    pass  # python-dotenv opcional — credenciais podem vir de variáveis de ambiente

# sentinelhub importado condicionalmente — evita crash sem credenciais
try:
    from sentinelhub import (
        SHConfig,
        SentinelHubRequest,
        DataCollection,
        MimeType,
        BBox,
        CRS,
        bbox_to_dimensions,
    )
    SENTINELHUB_OK = True
except ImportError:
    SENTINELHUB_OK = False
    print("⚠️  sentinelhub não instalado — usando modo local")


# ── CONFIGURAÇÃO ──────────────────────────────────────────────────────────────

RESOLUCAO_M = 10   # Sentinel-2: 10m por pixel (B04, B08); B11/B12 = 20m
DATA_DIR    = Path("data/sample_farm")

# Fazendas cadastradas — expandir conforme novos CPAs são adicionados
FAZENDAS = {
    "itumbiara": {
        "nome":     "Fazenda Piloto — Itumbiara, GO",
        "municipio":"Itumbiara",
        "bbox":     [-49.2800, -18.4500, -49.1500, -18.3500],
        "area_ha":  800,
        "cpa_id":   "CPA-GO-001",
    },
    "rio_verde": {
        "nome":     "Fazenda Boa Esperança — Rio Verde, GO",
        "municipio":"Rio Verde",
        "bbox":     [-51.0100, -17.8500, -50.8800, -17.7500],
        "area_ha":  1200,
        "cpa_id":   "CPA-GO-002",
    },
    "jatai": {
        "nome":     "Fazenda São Benedito — Jataí, GO",
        "municipio":"Jataí",
        "bbox":     [-51.7500, -17.9300, -51.6200, -17.8300],
        "area_ha":  850,
        "cpa_id":   "CPA-GO-003",
    },
}

# EvalScript: coleta B04, B08, B11, B12 + máscara de nuvem
EVALSCRIPT_MULTIBAND = """
//VERSION=3
function setup() {
  return {
    input: ["B04", "B08", "B11", "B12", "SCL"],
    output: { bands: 5, sampleType: "FLOAT32" }
  };
}
function evaluatePixel(sample) {
  // SCL: 4=vegetation, 5=not_veg, 6=water, 8-11=clouds
  let cloud = (sample.SCL >= 8 && sample.SCL <= 11) ? 1.0 : 0.0;
  return [sample.B04, sample.B08, sample.B11, sample.B12, cloud];
}
"""


# ── ÍNDICES ESPECTRAIS ────────────────────────────────────────────────────────

def calcular_ndvi(b4: np.ndarray, b8: np.ndarray) -> np.ndarray:
    """NDVI = (NIR - Red) / (NIR + Red). Range: -1 a 1."""
    return (b8 - b4) / (b8 + b4 + 1e-10)


def calcular_ndwi(b8: np.ndarray, b11: np.ndarray) -> np.ndarray:
    """
    NDWI (Normalized Difference Water Index) — umidade do solo.
    NDWI = (NIR - SWIR1) / (NIR + SWIR1)
    Valores altos → solo úmido / alta matéria orgânica.
    Crítico para VM0042: SOC correlaciona com umidade retida.
    """
    return (b8 - b11) / (b8 + b11 + 1e-10)


def calcular_nbr(b8: np.ndarray, b12: np.ndarray) -> np.ndarray:
    """
    NBR (Normalized Burn Ratio) — detecta área queimada / solo exposto.
    NBR = (NIR - SWIR2) / (NIR + SWIR2)
    Usado para detectar eventos de perda de permanência.
    """
    return (b8 - b12) / (b8 + b12 + 1e-10)


def calcular_bsi(b4: np.ndarray, b8: np.ndarray,
                 b11: np.ndarray, b12: np.ndarray) -> np.ndarray:
    """
    BSI (Bare Soil Index) — exposição de solo nu.
    BSI = ((SWIR1 + Red) - (NIR + Blue)) / ((SWIR1 + Red) + (NIR + Blue))
    Aproximado aqui sem Blue: BSI ≈ (SWIR1 - NIR) / (SWIR1 + NIR).
    Valores altos → solo exposto (baixo carbono, alta erosão).
    """
    return (b11 - b8) / (b11 + b8 + 1e-10)


# ── CLASSIFICAÇÃO ─────────────────────────────────────────────────────────────

def classificar_zona(ndvi: float) -> str:
    """Classifica a zona pelo NDVI médio."""
    if ndvi >= 0.6:   return "Alta biomassa — floresta/reserva"
    if ndvi >= 0.4:   return "Vegetação densa — lavoura saudável"
    if ndvi >= 0.2:   return "Vegetação moderada"
    if ndvi >= 0.0:   return "Solo exposto / pastagem degradada"
    return "Água / sombra"


def estimar_soc_relativo(ndwi: np.ndarray, ndvi: np.ndarray) -> np.ndarray:
    """
    Estimativa relativa de SOC (Soil Organic Carbon) a partir de índices.
    Fórmula empírica baseada em correlações Literatura VM0042:
      SOC_proxy = 0.6 × NDWI + 0.4 × NDVI  (normalizado 0–1)
    Nota: é um proxy para priorização de pontos NIR.
    O valor absoluto de SOC vem da análise laboratorial + sensor NIR.
    """
    soc_proxy = 0.6 * ndwi + 0.4 * ndvi
    # Normaliza para 0–1
    s_min, s_max = np.nanmin(soc_proxy), np.nanmax(soc_proxy)
    if s_max > s_min:
        soc_proxy = (soc_proxy - s_min) / (s_max - s_min)
    return np.clip(soc_proxy, 0, 1)


# ── PONTOS DE AMOSTRAGEM ──────────────────────────────────────────────────────

def gerar_pontos_amostragem(
    ndvi: np.ndarray,
    soc_proxy: np.ndarray,
    n_pontos: int = None,
    area_ha: float = 800.0
) -> list[dict]:
    """
    Gera pontos de amostragem para coleta com sensor NIR em campo.

    Estratégia (VM0042 §7.3):
    - 70% dos pontos distribuídos proporcionalmente à variabilidade do SOC
    - 30% em grade regular para cobertura espacial uniforme
    - Concentra pontos em zonas de maior incerteza (alto desvio padrão)

    Retorna lista de dicts com {row, col, ndvi, soc_proxy, prioridade}.
    """
    h, w = ndvi.shape
    pontos = []

    # ── Densidade de amostragem baseada na área real (VM0042 §7.3) ──
    # Padrão: 1 ponto a cada 8 ha, mínimo 30, máximo 200
    if n_pontos is None:
        n_pontos = max(30, min(200, int(area_ha / 8)))
        print(f"   Pontos de amostragem calculados: {n_pontos} ({area_ha:.0f} ha ÷ 8 ha/ponto)")

    # ── Grade regular (30% dos pontos) ──
    n_grid = int(n_pontos * 0.30)
    linhas = int(np.sqrt(n_grid))
    cols   = n_grid // linhas
    sy, sx = h // linhas, w // cols

    for i in range(linhas):
        for j in range(cols):
            cy = i * sy + sy // 2
            cx = j * sx + sx // 2
            cy, cx = min(cy, h-1), min(cx, w-1)
            pontos.append({
                "row": int(cy), "col": int(cx),
                "ndvi":      round(float(ndvi[cy, cx]), 4),
                "soc_proxy": round(float(soc_proxy[cy, cx]), 4),
                "prioridade": "grade",
            })

    # ── Variabilidade local (70% dos pontos) ──
    n_var   = n_pontos - len(pontos)
    n_cells = int(np.sqrt(n_var))
    sy2, sx2 = h // n_cells, w // n_cells

    for i in range(n_cells):
        for j in range(n_cells):
            y0, y1 = i * sy2, min((i+1) * sy2, h)
            x0, x1 = j * sx2, min((j+1) * sx2, w)
            celula_soc = soc_proxy[y0:y1, x0:x1]
            if celula_soc.size == 0:
                continue
            # Ponto de maior variabilidade local
            std_local = np.std(celula_soc)
            cy = (y0 + y1) // 2
            cx = (x0 + x1) // 2
            prioridade = "alta" if std_local > 0.15 else "media" if std_local > 0.08 else "baixa"
            pontos.append({
                "row": int(cy), "col": int(cx),
                "ndvi":      round(float(ndvi[cy, cx]), 4),
                "soc_proxy": round(float(soc_proxy[cy, cx]), 4),
                "prioridade": prioridade,
            })

    # Remove pontos fora do polígono da fazenda (NDVI é NaN após máscara)
    pontos = [
        p for p in pontos
        if not np.isnan(ndvi[p["row"], p["col"]])
    ]

    # Ordena por prioridade para otimizar rota de campo
    ordem = {"alta": 0, "media": 1, "baixa": 2, "grade": 3}
    pontos.sort(key=lambda p: ordem.get(p["prioridade"], 4))

    return pontos[:n_pontos]


# ── VISUALIZAÇÃO ──────────────────────────────────────────────────────────────

def gerar_mapa(
    ndvi: np.ndarray,
    ndwi: np.ndarray,
    soc_proxy: np.ndarray,
    pontos: list[dict],
    fazenda_info: dict,
    output_path: Path,
) -> Path:
    """
    Gera painel visual de 3 mapas:
      1. NDVI — cobertura vegetal
      2. NDWI/SOC proxy — umidade e matéria orgânica do solo
      3. Pontos de amostragem priorizados por SOC
    """
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fig, axes = plt.subplots(1, 3, figsize=(21, 7))
    fig.patch.set_facecolor('#09150C')

    # Colormaps
    cmap_ndvi = mcolors.LinearSegmentedColormap.from_list(
        "ndvi", ["#7B2020", "#C8960A", "#F5F5E8", "#27AE60", "#0D5C38"], N=256
    )
    cmap_soc = mcolors.LinearSegmentedColormap.from_list(
        "soc", ["#F0E6CC", "#C4983A", "#8B5E15", "#4A3010", "#1A0A00"], N=256
    )
    cmap_pts = cmap_ndvi

    def style_ax(ax, title):
        ax.set_title(title, color='white', fontsize=11, fontweight='bold', pad=10)
        ax.set_facecolor('#09150C')
        ax.axis('off')

    # ── 1. NDVI ──
    im1 = axes[0].imshow(ndvi, cmap=cmap_ndvi, vmin=-0.1, vmax=0.85)
    style_ax(axes[0], "NDVI — Cobertura Vegetal")
    cb1 = plt.colorbar(im1, ax=axes[0], fraction=0.046, pad=0.04)
    cb1.set_label('NDVI', color='white', fontsize=8)
    plt.setp(cb1.ax.yaxis.get_ticklabels(), color='white', fontsize=7)

    # Adiciona legenda de zonas
    for ndvi_val, label, color in [
        (0.70, "Reserva/Floresta", "#27AE60"),
        (0.50, "Lavoura", "#A8D060"),
        (0.30, "Veg. Moderada", "#F0F0A0"),
        (0.10, "Solo Exposto", "#D4A017"),
    ]:
        axes[0].annotate(
            f"━ {label}",
            xy=(0.02, 0.02 + ndvi_val * 0.8),
            xycoords='axes fraction',
            color=color, fontsize=6.5, alpha=0.85,
        )

    # ── 2. SOC Proxy ──
    im2 = axes[1].imshow(soc_proxy, cmap=cmap_soc, vmin=0, vmax=1)
    style_ax(axes[1], "SOC Proxy — Matéria Orgânica\n(NDWI + NDVI · índice relativo)")
    cb2 = plt.colorbar(im2, ax=axes[1], fraction=0.046, pad=0.04)
    cb2.set_label('SOC proxy (0–1)', color='white', fontsize=8)
    plt.setp(cb2.ax.yaxis.get_ticklabels(), color='white', fontsize=7)

    # ── 3. Pontos de amostragem ──
    axes[2].imshow(ndvi, cmap=cmap_pts, vmin=-0.1, vmax=0.85, alpha=0.6)
    style_ax(axes[2], f"Pontos de Amostragem NIR\n{len(pontos)} pontos — rota de campo otimizada")

    cores_prio = {"alta": "#E74C3C", "media": "#F39C12", "baixa": "#3498DB", "grade": "#2ECC71"}
    tamanhos   = {"alta": 28, "media": 20, "baixa": 14, "grade": 12}

    for prio, cor, tam in [
        ("grade",  "#2ECC71", 12),
        ("baixa",  "#3498DB", 14),
        ("media",  "#F39C12", 20),
        ("alta",   "#E74C3C", 28),
    ]:
        pts_prio = [p for p in pontos if p["prioridade"] == prio]
        if pts_prio:
            xs = [p["col"] for p in pts_prio]
            ys = [p["row"] for p in pts_prio]
            axes[2].scatter(xs, ys, c=cor, s=tam, edgecolors='white',
                           linewidths=0.3, alpha=0.9, label=prio, zorder=3)

    axes[2].legend(
        title="Prioridade NIR", title_fontsize=7,
        fontsize=6.5, framealpha=0.3,
        facecolor='#09150C', labelcolor='white',
        loc='lower right',
    )

    nome_fazenda = fazenda_info.get("nome", "Fazenda Piloto")
    cpa_id = fazenda_info.get("cpa_id", "—")
    fig.suptitle(
        f"CarbonChain — MRV Satélite · {nome_fazenda}\n"
        f"CPA ID: {cpa_id} · VM0042 v2.2 · Sentinel-2",
        color='#E6A020', fontsize=13, fontweight='bold', y=1.02
    )

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight',
                facecolor='#09150C', edgecolor='none')
    plt.close()
    print(f"  ✓ Mapa salvo: {output_path}")
    return output_path



# -- MASCARA DE POLIGONO -------------------------------------------------------

def criar_mascara_poligono(geojson_geom, bbox, shape):
    h, w = shape
    lon_min, lat_min, lon_max, lat_max = bbox

    def geo_para_pixel(lon, lat):
        col = (lon - lon_min) / (lon_max - lon_min) * w
        row = (lat_max - lat) / (lat_max - lat_min) * h
        return col, row

    def anel_para_mascara(anel):
        pts_px = [geo_para_pixel(lon, lat) for lon, lat in anel]
        path = MplPath(pts_px)
        cols, rows = np.meshgrid(np.arange(w), np.arange(h))
        pts = np.column_stack([cols.ravel(), rows.ravel()])
        return path.contains_points(pts).reshape(h, w)

    tipo = geojson_geom.get("type", "")
    coords = geojson_geom.get("coordinates", [])
    mascara = np.zeros((h, w), dtype=bool)

    if tipo == "Polygon":
        mascara |= anel_para_mascara(coords[0])
    elif tipo == "MultiPolygon":
        for poligono in coords:
            mascara |= anel_para_mascara(poligono[0])

    return mascara


# ── ANÁLISE PRINCIPAL ─────────────────────────────────────────────────────────

def analisar_fazenda(
    b4: np.ndarray,
    b8: np.ndarray,
    b11: np.ndarray,
    b12: np.ndarray,
    fazenda_info: dict,
    cloud_mask: np.ndarray = None,
    data_imagem: str = None,
    geometria: dict = None,
) -> dict:
    """
    Análise completa da fazenda.
    Retorna dict estruturado para consumo pelo mrv_calculator.py.
    """
    nome = fazenda_info.get("nome", "Fazenda")
    area_ha = fazenda_info.get("area_ha", 800)

    print(f"\n🛰️  CarbonChain — Análise Satelite")
    print(f"   Fazenda: {nome}")
    print(f"   CPA ID:  {fazenda_info.get('cpa_id', '—')}")
    print("=" * 50)

    # Aplica máscara de nuvem se disponível
    if cloud_mask is not None:
        cloud_pct = float(np.mean(cloud_mask) * 100)
        print(f"\n☁️  Cobertura de nuvens: {cloud_pct:.1f}%")
        if cloud_pct > 30:
            print("   ⚠️  Alta cobertura — considerar outra data")
        # Mascara pixels nublados com NaN
        for arr in [b4, b8, b11, b12]:
            arr[cloud_mask > 0.5] = np.nan

    # -- Mascara do poligono real da fazenda --
    if geometria is not None and fazenda_info.get("bbox"):
        h_arr, w_arr = b4.shape
        mascara = criar_mascara_poligono(geometria, fazenda_info["bbox"], (h_arr, w_arr))
        pixels_dentro = int(np.sum(mascara))
        area_mapeada_ha = round(pixels_dentro * (RESOLUCAO_M ** 2) / 10_000, 1)
        print(f"\n   Mascara aplicada: {pixels_dentro} pixels = {area_mapeada_ha} ha reais (CAR: {fazenda_info.get('area_ha','?')} ha)")
        fora = ~mascara
        for arr in [b4, b8, b11, b12]:
            arr[fora] = np.nan
    else:
        area_mapeada_ha = fazenda_info.get("area_ha", 0)

    # -- Indices espectrais --
    ndvi     = calcular_ndvi(b4, b8)
    ndwi     = calcular_ndwi(b8, b11)
    nbr      = calcular_nbr(b8, b12)
    bsi      = calcular_bsi(b4, b8, b11, b12)
    soc_prox = estimar_soc_relativo(ndwi, ndvi)

    # ── Estatísticas NDVI ──
    ndvi_medio = float(np.nanmean(ndvi))
    ndvi_std   = float(np.nanstd(ndvi))
    ndvi_p25   = float(np.nanpercentile(ndvi, 25))
    ndvi_p75   = float(np.nanpercentile(ndvi, 75))

    print(f"\n📊 NDVI:")
    print(f"   Médio:  {ndvi_medio:.3f}  |  Std: {ndvi_std:.3f}")
    print(f"   P25:    {ndvi_p25:.3f}  |  P75: {ndvi_p75:.3f}")
    print(f"   Classe: {classificar_zona(ndvi_medio)}")

    # ── Estatísticas NDWI / SOC ──
    ndwi_medio   = float(np.nanmean(ndwi))
    soc_medio    = float(np.nanmean(soc_prox))
    bsi_medio    = float(np.nanmean(bsi))

    print(f"\n🌱 Solo:")
    print(f"   NDWI (umidade):   {ndwi_medio:.3f}")
    print(f"   SOC proxy:        {soc_medio:.3f}")
    print(f"   BSI (solo nu):    {bsi_medio:.3f}")
    print(f"   NBR (queimada):   {float(np.nanmean(nbr)):.3f}")

    # ── Distribuição de zonas por área ──
    total_px = np.sum(~np.isnan(ndvi))
    px_ha    = (RESOLUCAO_M ** 2) / 10_000  # ha por pixel

    zonas = {
        "floresta_reserva_ha":   round(float(np.sum(ndvi > 0.60)) * px_ha, 1),
        "lavoura_saudavel_ha":   round(float(np.sum((ndvi >= 0.40) & (ndvi < 0.60))) * px_ha, 1),
        "vegetacao_moderada_ha": round(float(np.sum((ndvi >= 0.20) & (ndvi < 0.40))) * px_ha, 1),
        "solo_exposto_ha":       round(float(np.sum((ndvi >= 0.00) & (ndvi < 0.20))) * px_ha, 1),
        "agua_sombra_ha":        round(float(np.sum(ndvi < 0.00)) * px_ha, 1),
    }
    total_mapeado = sum(zonas.values())

    print(f"\n🗺️  Zonas (área estimada):")
    for zona, ha in zonas.items():
        pct = (ha / total_mapeado * 100) if total_mapeado > 0 else 0
        print(f"   {zona.replace('_ha','').replace('_',' '):28s}: {ha:6.0f} ha  ({pct:.0f}%)")

    # ── Elegibilidade VM0042 ──
    # Solo agrícola = lavoura + vegetação moderada + solo exposto
    solo_agricola_ha = zonas["lavoura_saudavel_ha"] + zonas["vegetacao_moderada_ha"] + zonas["solo_exposto_ha"]
    reserva_ha       = zonas["floresta_reserva_ha"]
    additionality_ok = ndvi_std > 0.10   # variabilidade indica potencial de melhoria

    print(f"\n✅ Elegibilidade VM0042:")
    print(f"   Solo agrícola elegível: {solo_agricola_ha:.0f} ha")
    print(f"   Reserva Legal (REDD+):  {reserva_ha:.0f} ha")
    print(f"   Adicionalidade proxy:   {'✓ OK' if additionality_ok else '⚠ Verificar'}")

    # ── Pontos de amostragem ──
    pontos = gerar_pontos_amostragem(ndvi, soc_prox, n_pontos=120, area_ha=area_ha)
    n_alta = len([p for p in pontos if p["prioridade"] == "alta"])
    print(f"\n📍 Pontos de amostragem NIR: {len(pontos)}")
    print(f"   Alta prioridade: {n_alta}  |  Média: {len([p for p in pontos if p['prioridade']=='media'])}  |  Baixa/grade: {len(pontos)-n_alta}")
    print(f"   Densidade: {len(pontos)/area_ha:.2f} pontos/ha")

    # ── Gerar mapa ──
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    cpa_id  = fazenda_info.get("cpa_id", "CPA-XX-000").replace(" ", "_")
    mapa_fn = DATA_DIR / f"mapa_ndvi_{cpa_id}.png"
    gerar_mapa(ndvi, ndwi, soc_prox, pontos, fazenda_info, mapa_fn)

    # ── Montar resultado JSON ──
    resultado = {
        "metadata": {
            "cpa_id":        fazenda_info.get("cpa_id", ""),
            "fazenda":       nome,
            "municipio":     fazenda_info.get("municipio", ""),
            "area_ha":       area_ha,
            "data_imagem":   data_imagem or datetime.now().strftime("%Y-%m-%d"),
            "resolucao_m":   RESOLUCAO_M,
            "metodologia":   "VM0042 v2.2",
            "sensor":        "Sentinel-2 MSI",
            "gerado_em":     datetime.now().isoformat(),
        },
        "indices": {
            "ndvi_medio":  round(ndvi_medio, 4),
            "ndvi_std":    round(ndvi_std, 4),
            "ndvi_p25":    round(ndvi_p25, 4),
            "ndvi_p75":    round(ndvi_p75, 4),
            "ndwi_medio":  round(ndwi_medio, 4),
            "bsi_medio":   round(bsi_medio, 4),
            "soc_proxy":   round(soc_medio, 4),
            "classificacao": classificar_zona(ndvi_medio),
        },
        "zonas_ha":   zonas,
        "elegibilidade": {
            "solo_agricola_ha":   round(solo_agricola_ha, 1),
            "reserva_ha":         round(reserva_ha, 1),
            "additionality_ok":   additionality_ok,
        },
        "amostragem": {
            "n_pontos":      len(pontos),
            "pontos_ha":     round(len(pontos) / area_ha, 3),
            "pontos":        pontos,
        },
        "outputs": {
            "mapa_ndvi": str(mapa_fn),
        },
    }

    # Salva JSON
    json_fn = DATA_DIR / f"resultado_sat_{cpa_id}.json"
    with open(json_fn, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)
    print(f"  ✓ JSON salvo:  {json_fn}")

    print("\n✅ Análise concluída!")
    print(f"   → Próximo passo: levar os {n_alta} pontos de alta prioridade para coleta NIR em campo.")
    print("=" * 50)

    return resultado


# ── MODO TESTE LOCAL ──────────────────────────────────────────────────────────

def rodar_teste_local(fazenda_key: str = "itumbiara") -> tuple:
    """
    Simula imagem Sentinel-2 realista para fazenda no Cerrado.
    Representa padrão típico: reserva ao norte, lavoura no centro,
    solo exposto/pastagem ao sul — comum no sul de Goiás.

    Todas as 4 bandas (B04, B08, B11, B12) são simuladas.
    """
    fazenda = FAZENDAS.get(fazenda_key, FAZENDAS["itumbiara"])
    area_ha = fazenda["area_ha"]
    # Dimensiona o array para cobrir a área real da fazenda
    # lado = √(area_ha × 10.000m²/ha ÷ resolução²)
    # Exemplo: 800ha → √(8.000.000 / 100) = 282 pixels → 795ha mapeados
    lado = int(np.sqrt(area_ha * 10_000 / RESOLUCAO_M ** 2))
    lado = max(lado, 50)  # mínimo 50px
    h, w = lado, lado

    print(f"\n🧪 Modo teste local — dados sintéticos Cerrado")
    print(f"   Fazenda: {fazenda['nome']}")
    print(f"   Grid:    {h}×{w} pixels = {h*w*RESOLUCAO_M**2/10000:.0f} ha mapeados\n")

    np.random.seed(42)

    # ── Padrão base NDVI por zona ──
    ndvi_base = np.zeros((h, w))
    n30 = h // 3

    # Norte — reserva/floresta nativa Cerrado (NDVI 0.6–0.82)
    ndvi_base[:n30, :]    = np.random.uniform(0.62, 0.82, (n30, w))
    # Centro — lavoura soja/milho (NDVI 0.38–0.62)
    ndvi_base[n30:2*n30, :] = np.random.uniform(0.38, 0.62, (n30, w))
    # Sul — pastagem degradada/solo exposto (NDVI 0.04–0.26)
    ndvi_base[2*n30:, :]  = np.random.uniform(0.04, 0.26, (h - 2*n30, w))

    # Suaviza e adiciona textura
    ndvi_base = gaussian_filter(ndvi_base, sigma=4)
    ndvi_base += np.random.normal(0, 0.025, (h, w))
    ndvi_base  = np.clip(ndvi_base, -0.05, 0.88)

    # ── B08 (NIR) ──
    b8 = 0.25 + 0.30 * ndvi_base + np.random.normal(0, 0.015, (h, w))
    b8 = np.clip(b8, 0.05, 0.75)

    # ── B04 (Red) — derivado do NDVI ──
    b4 = b8 * (1 - ndvi_base) / (1 + ndvi_base + 1e-10)
    b4 = np.clip(b4 + np.random.normal(0, 0.01, (h, w)), 0.01, 0.50)

    # ── B11 (SWIR1) — umidade do solo ──
    # Reserva: alta umidade (baixo SWIR), pastagem: baixa umidade (alto SWIR)
    b11 = 0.35 - 0.25 * ndvi_base + np.random.normal(0, 0.02, (h, w))
    b11 = gaussian_filter(b11, sigma=2)
    b11 = np.clip(b11, 0.05, 0.55)

    # ── B12 (SWIR2) — discriminação de cobertura ──
    b12 = 0.28 - 0.18 * ndvi_base + np.random.normal(0, 0.018, (h, w))
    b12 = gaussian_filter(b12, sigma=2)
    b12 = np.clip(b12, 0.03, 0.48)

    return b4, b8, b11, b12, fazenda


# ── API COPERNICUS ────────────────────────────────────────────────────────────

def buscar_sentinel2_api(
    fazenda_key: str = "itumbiara",
    data_inicio: str = None,
    data_fim: str = None,
    fazenda_override: dict = None,  # bbox dinâmico vindo do pipeline.py
) -> tuple:
    """
    Busca dados reais Sentinel-2 via Copernicus Data Space API.

    Para usar:
    1. Criar conta gratuita em: https://dataspace.copernicus.eu
    2. Copiar Client ID e Client Secret
    3. Criar arquivo .env na raiz do projeto:
       SH_CLIENT_ID=seu_client_id
       SH_CLIENT_SECRET=seu_client_secret

    Ou setar variáveis de ambiente antes de rodar:
       export SH_CLIENT_ID=...
       export SH_CLIENT_SECRET=...
    """
    if not SENTINELHUB_OK:
        raise ImportError("sentinelhub não instalado. Rode: pip install sentinelhub")

    client_id     = os.getenv("SH_CLIENT_ID")
    client_secret = os.getenv("SH_CLIENT_SECRET")

    if not client_id or not client_secret:
        raise ValueError(
            "\n🔑 Credenciais Copernicus não encontradas!\n"
            "   1. Crie conta em: https://dataspace.copernicus.eu\n"
            "   2. Crie arquivo .env na raiz:\n"
            "      SH_CLIENT_ID=seu_id\n"
            "      SH_CLIENT_SECRET=seu_secret\n"
            "   3. Rode novamente com --api\n"
        )

    # SHConfig não aceita kwargs no construtor — atributos devem ser setados depois
    config = SHConfig()
    config.sh_client_id     = client_id
    config.sh_client_secret = client_secret
    config.sh_base_url      = "https://sh.dataspace.copernicus.eu"
    config.sh_token_url     = "https://identity.dataspace.copernicus.eu/auth/realms/CDSE/protocol/openid-connect/token"

    # Usa bbox dinâmico do pipeline se fornecido, senão busca no dict FAZENDAS
    if fazenda_override:
        fazenda = fazenda_override
    else:
        fazenda = FAZENDAS.get(fazenda_key, FAZENDAS["itumbiara"])
    bbox    = BBox(bbox=fazenda["bbox"], crs=CRS.WGS84)
    tamanho = bbox_to_dimensions(bbox, resolution=RESOLUCAO_M)

    if data_inicio is None:
        # Padrão: último mês com baixa nebulosidade (período seco Cerrado = maio–setembro)
        hoje = datetime.now()
        data_fim    = hoje.strftime("%Y-%m-%dT00:00:00Z")
        data_inicio = (hoje - timedelta(days=30)).strftime("%Y-%m-%dT00:00:00Z")

    print(f"\n🌐 Buscando Sentinel-2 via API Copernicus...")
    print(f"   Fazenda:   {fazenda['nome']}")
    print(f"   Bbox:      {fazenda['bbox']}")
    print(f"   Resolução: {RESOLUCAO_M}m | Tamanho: {tamanho}")
    print(f"   Período:   {data_inicio[:10]} → {data_fim[:10]}")

    request = SentinelHubRequest(
        evalscript=EVALSCRIPT_MULTIBAND,
        input_data=[
            SentinelHubRequest.input_data(
                data_collection=DataCollection.SENTINEL2_L2A.define_from(
                    "s2l2a_cdse",
                    service_url="https://sh.dataspace.copernicus.eu"
                ),
                time_interval=(data_inicio, data_fim),
                mosaicking_order="leastCC",
            )
        ],
        responses=[SentinelHubRequest.output_response("default", MimeType.TIFF)],
        bbox=bbox,
        size=tamanho,
        config=config,
    )

    dados = request.get_data()[0]  # shape: (h, w, 5) — B04, B08, B11, B12, cloud
    print(f"   ✓ Dados recebidos: shape {dados.shape}")

    b4    = dados[:, :, 0].astype(float) / 10000
    b8    = dados[:, :, 1].astype(float) / 10000
    b11   = dados[:, :, 2].astype(float) / 10000
    b12   = dados[:, :, 3].astype(float) / 10000
    cloud = dados[:, :, 4].astype(float)

    return b4, b8, b11, b12, cloud, fazenda, data_inicio[:10]


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CarbonChain — Análise Satellite MRV (VM0042)"
    )
    parser.add_argument(
        "--farm", default="itumbiara",
        choices=list(FAZENDAS.keys()),
        help="Fazenda a analisar (default: itumbiara)"
    )
    parser.add_argument(
        "--api", action="store_true",
        help="Usar dados reais da API Copernicus (requer credenciais)"
    )
    parser.add_argument(
        "--start", default=None,
        help="Data início ISO (ex: 2024-06-01) — só com --api"
    )
    parser.add_argument(
        "--end", default=None,
        help="Data fim ISO (ex: 2024-08-31) — só com --api"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Analisar todas as fazendas cadastradas"
    )

    args = parser.parse_args()

    if args.all:
        print(f"\n🗂️  Analisando todas as {len(FAZENDAS)} fazendas cadastradas...\n")
        resultados = {}
        for key in FAZENDAS:
            b4, b8, b11, b12, fazenda = rodar_teste_local(key)
            resultados[key] = analisar_fazenda(b4, b8, b11, b12, fazenda)
        # Salva resumo consolidado
        resumo_fn = DATA_DIR / "resumo_todas_fazendas.json"
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        resumo = {k: {
            "cpa_id":   v["metadata"]["cpa_id"],
            "fazenda":  v["metadata"]["fazenda"],
            "ndvi":     v["indices"]["ndvi_medio"],
            "soc":      v["indices"]["soc_proxy"],
            "solo_ha":  v["elegibilidade"]["solo_agricola_ha"],
            "reserva_ha": v["elegibilidade"]["reserva_ha"],
        } for k, v in resultados.items()}
        with open(resumo_fn, "w", encoding="utf-8") as f:
            json.dump(resumo, f, ensure_ascii=False, indent=2)
        print(f"\n✓ Resumo consolidado: {resumo_fn}")
        return

    if args.api:
        try:
            b4, b8, b11, b12, cloud, fazenda, data_img = buscar_sentinel2_api(
                fazenda_key=args.farm,
                data_inicio=args.start,
                data_fim=args.end,
            )
            analisar_fazenda(b4, b8, b11, b12, fazenda,
                             cloud_mask=cloud, data_imagem=data_img)
        except (ValueError, ImportError) as e:
            print(f"\n❌ {e}")
            print("   Rodando em modo local como fallback...\n")
            b4, b8, b11, b12, fazenda = rodar_teste_local(args.farm)
            analisar_fazenda(b4, b8, b11, b12, fazenda)
    else:
        b4, b8, b11, b12, fazenda = rodar_teste_local(args.farm)
        analisar_fazenda(b4, b8, b11, b12, fazenda)


if __name__ == "__main__":
    main()
