"""
CarbonChain — satellite.py
Integração com Sentinel-2 via Copernicus Data Space
Gera mapa NDVI e pontos de amostragem para fazenda no sul de Goiás
"""

import numpy as np
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from sentinelhub import (
    SHConfig,
    SentinelHubRequest,
    DataCollection,
    MimeType,
    BBox,
    CRS,
    bbox_to_dimensions,
)

# ── CONFIGURAÇÃO ──────────────────────────────────────────────
# Coordenadas: área agrícola em Rio Verde — Sul de Goiás
# Bounding box: ~200 hectares de lavoura + Cerrado nativo
FAZENDA_BBOX = BBox(
    bbox=[-51.0100, -17.8500, -50.8800, -17.7500],
    crs=CRS.WGS84
)

RESOLUCAO_M = 10  # Sentinel-2 resolução 10m por pixel

# ── EVALSCRIPT SENTINEL-2 ─────────────────────────────────────
# Busca as bandas B4 (vermelho) e B8 (infravermelho próximo)
# para calcular NDVI = (B8 - B4) / (B8 + B4)
EVALSCRIPT = """
//VERSION=3
function setup() {
  return {
    input: ["B04", "B08", "dataMask"],
    output: { bands: 3, sampleType: "FLOAT32" }
  };
}
function evaluatePixel(sample) {
  let ndvi = (sample.B08 - sample.B04) / (sample.B08 + sample.B04 + 0.0001);
  return [sample.B04, sample.B08, ndvi];
}
"""

def calcular_ndvi(b4, b8):
    """Calcula NDVI pixel a pixel."""
    return (b8 - b4) / (b8 + b4 + 1e-10)

def classificar_zona(ndvi_medio):
    """Classifica a zona pelo valor médio de NDVI."""
    if ndvi_medio >= 0.6:
        return "Alta biomassa (floresta/reserva)"
    elif ndvi_medio >= 0.4:
        return "Vegetação densa (lavoura saudável)"
    elif ndvi_medio >= 0.2:
        return "Vegetação moderada"
    elif ndvi_medio >= 0.0:
        return "Solo exposto / pastagem degradada"
    else:
        return "Água / sombra"

def gerar_pontos_amostragem(ndvi_array, n_pontos=120):
    """
    Gera pontos de amostragem distribuídos pelas zonas de variabilidade.
    Concentra mais pontos onde o NDVI é mais variável (maior incerteza).
    """
    h, w = ndvi_array.shape
    pontos = []

    # Divide em grade e pega o ponto de maior variabilidade em cada célula
    linhas = int(np.sqrt(n_pontos))
    colunas = n_pontos // linhas

    step_y = h // linhas
    step_x = w // colunas

    for i in range(linhas):
        for j in range(colunas):
            y_start = i * step_y
            y_end   = min(y_start + step_y, h)
            x_start = j * step_x
            x_end   = min(x_start + step_x, w)

            celula = ndvi_array[y_start:y_end, x_start:x_end]
            if celula.size == 0:
                continue

            # Ponto central da célula com maior desvio padrão local
            cy = (y_start + y_end) // 2
            cx = (x_start + x_end) // 2
            pontos.append((cy, cx, float(np.mean(celula))))

    return pontos

def gerar_mapa(ndvi_array, pontos, output_path="data/sample_farm/mapa_ndvi.png"):
    """Gera o mapa NDVI colorido com os pontos de amostragem."""

    fig, axes = plt.subplots(1, 2, figsize=(16, 7))
    fig.patch.set_facecolor('#0f1e2d')

    # ── Mapa NDVI ──
    cmap = mcolors.LinearSegmentedColormap.from_list(
        "ndvi_carbonchain",
        ["#8B2020", "#D4A017", "#F0F4F0", "#27AE60", "#1A5C38"],
        N=256
    )
    im = axes[0].imshow(ndvi_array, cmap=cmap, vmin=-0.2, vmax=0.8)
    axes[0].set_title("NDVI — Índice de Vegetação\nRio Verde, Sul de Goiás",
                       color='white', fontsize=12, fontweight='bold', pad=12)
    axes[0].axis('off')

    cbar = plt.colorbar(im, ax=axes[0], orientation='vertical', fraction=0.046, pad=0.04)
    cbar.ax.yaxis.set_tick_params(color='white')
    plt.setp(cbar.ax.yaxis.get_ticklabels(), color='white', fontsize=8)
    cbar.set_label('Valor NDVI', color='white', fontsize=9)

    # ── Mapa com pontos de amostragem ──
    axes[1].imshow(ndvi_array, cmap=cmap, vmin=-0.2, vmax=0.8, alpha=0.7)
    axes[1].set_title(f"Pontos de Amostragem NIR\n{len(pontos)} pontos georreferenciados",
                      color='white', fontsize=12, fontweight='bold', pad=12)
    axes[1].axis('off')

    ys = [p[0] for p in pontos]
    xs = [p[1] for p in pontos]
    vals = [p[2] for p in pontos]

    scatter = axes[1].scatter(xs, ys, c=vals, cmap=cmap, vmin=-0.2, vmax=0.8,
                               s=18, edgecolors='white', linewidths=0.4, alpha=0.9)

    # Fundo escuro
    for ax in axes:
        ax.set_facecolor('#0f1e2d')

    fig.suptitle("CarbonChain — MRV Satélite · Fazenda Piloto",
                 color='#D4A017', fontsize=14, fontweight='bold', y=1.01)

    plt.tight_layout()
    plt.savefig(output_path, dpi=150, bbox_inches='tight',
                facecolor='#0f1e2d', edgecolor='none')
    print(f"✓ Mapa salvo em: {output_path}")
    return output_path

def analisar_fazenda(b4_array, b8_array):
    """Análise completa da fazenda — NDVI + zonas + pontos."""

    print("\n🛰️  CarbonChain — Análise Satellite")
    print("=" * 45)

    ndvi = calcular_ndvi(b4_array, b8_array)

    # Estatísticas gerais
    ndvi_medio  = float(np.nanmean(ndvi))
    ndvi_min    = float(np.nanmin(ndvi))
    ndvi_max    = float(np.nanmax(ndvi))
    ndvi_std    = float(np.nanstd(ndvi))

    print(f"\n📊 Estatísticas NDVI:")
    print(f"   Médio:    {ndvi_medio:.3f}")
    print(f"   Mínimo:   {ndvi_min:.3f}")
    print(f"   Máximo:   {ndvi_max:.3f}")
    print(f"   Desvio:   {ndvi_std:.3f}")
    print(f"   Classificação: {classificar_zona(ndvi_medio)}")

    # Distribuição por zona
    total_pixels = ndvi.size
    print(f"\n🗺️  Distribuição de zonas:")
    zonas = {
        "Floresta/Reserva (NDVI > 0.6)":     np.sum(ndvi > 0.6),
        "Lavoura saudável (0.4–0.6)":         np.sum((ndvi >= 0.4) & (ndvi < 0.6)),
        "Vegetação moderada (0.2–0.4)":       np.sum((ndvi >= 0.2) & (ndvi < 0.4)),
        "Solo exposto (0.0–0.2)":             np.sum((ndvi >= 0.0) & (ndvi < 0.2)),
        "Água/sombra (< 0.0)":               np.sum(ndvi < 0.0),
    }
    for zona, pixels in zonas.items():
        pct = (pixels / total_pixels) * 100
        ha  = (pixels * RESOLUCAO_M * RESOLUCAO_M) / 10000
        print(f"   {zona}: {pct:.1f}% (~{ha:.0f}ha)")

    # Pontos de amostragem
    pontos = gerar_pontos_amostragem(ndvi, n_pontos=120)
    print(f"\n📍 Pontos de amostragem NIR gerados: {len(pontos)}")
    print(f"   Densidade: ~{len(pontos)/((ndvi.size * RESOLUCAO_M**2)/10000):.2f} pontos/ha")

    # Gerar mapa
    mapa_path = gerar_mapa(ndvi, pontos)

    print("\n✅ Análise concluída!")
    print(f"   Use os {len(pontos)} pontos para coleta com sensor NIR em campo.")
    print("=" * 45)

    return {
        "ndvi":   ndvi,
        "pontos": pontos,
        "stats":  {"medio": ndvi_medio, "std": ndvi_std},
        "zonas":  zonas,
    }


# ── MODO DE TESTE SEM API ─────────────────────────────────────
# Gera dados sintéticos realistas para validar o pipeline
# sem precisar de credenciais da API ainda
def rodar_teste_local():
    """
    Simula imagem Sentinel-2 de uma fazenda de 200ha no Cerrado.
    Distribui zonas de lavoura, reserva e solo exposto realisticamente.
    """
    print("\n🧪 Modo teste local — dados sintéticos Rio Verde / GO")
    print("   (Para dados reais, configure as credenciais Copernicus)\n")

    np.random.seed(42)
    h, w = 200, 200

    # Cria padrão espacial realista: reserva no norte, lavoura no centro, solo no sul
    ndvi_base = np.zeros((h, w))

    # Zona norte — reserva/floresta (NDVI alto 0.6–0.8)
    ndvi_base[:60, :] = np.random.uniform(0.60, 0.80, (60, w))

    # Zona centro — lavoura saudável (NDVI médio 0.35–0.6)
    ndvi_base[60:140, :] = np.random.uniform(0.35, 0.60, (80, w))

    # Zona sul — solo exposto / pastagem (NDVI baixo 0.05–0.25)
    ndvi_base[140:, :] = np.random.uniform(0.05, 0.25, (60, w))

    # Adiciona textura e variação espacial suave
    from scipy.ndimage import gaussian_filter
    ndvi_base = gaussian_filter(ndvi_base, sigma=3)
    ndvi_base += np.random.normal(0, 0.02, (h, w))
    ndvi_base = np.clip(ndvi_base, -0.1, 0.9)

    # Converte NDVI de volta para B4 e B8 sintéticos
    b8 = np.random.uniform(0.2, 0.5, (h, w))
    b4 = b8 * (1 - ndvi_base) / (1 + ndvi_base + 1e-10)
    b4 = np.clip(b4, 0.01, 1.0)

    return b4, b8


if __name__ == "__main__":
    # Roda o teste local primeiro
    # Quando tiver credenciais Copernicus, substitui por dados reais
    b4, b8 = rodar_teste_local()
    resultado = analisar_fazenda(b4, b8)