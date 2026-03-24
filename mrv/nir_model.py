"""
CarbonChain — nir_model.py  v1.0
==================================
Processa leituras do sensor NIR AgroCares Scanner em campo.
Converte espectros NIR → SOC% calibrado → entrada para mrv_calculator.py

Fluxo:
  AgroCares Scanner (campo) → leituras_nir.json
          ↓
  nir_model.py (este arquivo)
          ↓
  solo_calibrado_CPA-GO-001.json → mrv_calculator.py

O AgroCares Scanner é aprovado pela Verra para VM0042 v2.2.
Retorna: SOC%, bulk density, pH, umidade — por ponto de coleta.

Dois modos:
  1. Real:  lê JSON exportado pelo app AgroCares
  2. Demo:  simula leituras realistas para o Cerrado
"""

import json
import math
import argparse
import numpy as np
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import Optional


# ── CONSTANTES ────────────────────────────────────────────────────────────────

DATA_DIR = Path("data/sample_farm")

# Parâmetros de referência para Latossolo Vermelho-Amarelo — Cerrado (sul de GO)
# Fonte: Embrapa Cerrados + literatura VM0042 / Bernoux et al. 2002
CERRADO_SOC_BASELINE  = 1.80   # % SOC médio — pastagem degradada sul de GO
CERRADO_SOC_FLORESTA  = 3.20   # % SOC médio — cerradão/reserva nativa
CERRADO_SOC_LAVOURA   = 2.10   # % SOC médio — lavoura iLPF bem manejada
CERRADO_BD_PADRAO     = 1.20   # g/cm³ bulk density — Latossolo típico
CERRADO_BD_COMPACTADO = 1.45   # g/cm³ — solo compactado / pisoteio bovino
CERRADO_PH_TIPICO     = 5.4    # pH médio Cerrado sem correção

# Incerteza típica do sensor NIR AgroCares (vs laboratório de referência)
# Fonte: AgroCares validation studies, vm0042 Appendix 4
NIR_INCERTEZA_SOC_PCT = 0.08   # ±0.08% SOC — erro padrão do modelo NIR
NIR_INCERTEZA_BD      = 0.06   # ±0.06 g/cm³
NIR_R2_MINIMO         = 0.85   # R² mínimo aceitável para uso no VM0042

# Profundidades padrão VM0042 §4.2
PROFUNDIDADES_CM = [10, 20, 30]  # cm — coleta em 3 camadas


# ── DATA CLASSES ──────────────────────────────────────────────────────────────

@dataclass
class LeituraNIR:
    """Leitura bruta do sensor AgroCares em um ponto de campo."""
    ponto_id:     str
    latitude:     float
    longitude:    float
    profundidade: int       # cm: 10, 20 ou 30
    zona:         str       # "solo_agricola" | "reserva" | "restauracao"
    # Saídas diretas do sensor
    soc_nir_pct:  float     # SOC% estimado pelo modelo NIR
    bd_nir:       float     # bulk density g/cm³
    ph_nir:       float     # pH (água)
    umidade_pct:  float     # % umidade gravimétrica
    # Controle de qualidade
    r2_modelo:    float     # R² do modelo NIR para este ponto
    flag_qc:      str = "OK"  # "OK" | "REVISAR" | "EXCLUIR"
    timestamp:    str = ""


@dataclass
class PontoCalibrado:
    """Ponto de solo após calibração NIR vs laboratório."""
    ponto_id:          str
    latitude:          float
    longitude:         float
    zona:              str
    # SOC calibrado por profundidade (média ponderada das 3 camadas)
    soc_0_10_pct:      float
    soc_10_20_pct:     float
    soc_20_30_pct:     float
    soc_medio_pct:     float   # média ponderada (VM0042: peso igual por camada)
    bulk_density:      float
    ph:                float
    umidade_pct:       float
    # Metadados de qualidade
    n_leituras:        int
    r2_medio:          float
    flag_qc:           str = "OK"
    confianca_pct:     float = 95.0


@dataclass
class ResultadoSolo:
    """Resultado agregado de todas as leituras NIR de uma fazenda."""
    cpa_id:              str
    fazenda:             str
    data_coleta:         str
    n_pontos_total:      int
    n_pontos_validos:    int
    # SOC por zona (valores que vão para o mrv_calculator)
    soc_solo_agricola:   float   # % SOC médio — área SOIL
    soc_reserva:         float   # % SOC médio — área REDD
    soc_restauracao:     float   # % SOC médio — área ARR
    soc_fazenda_media:   float   # % SOC médio geral
    bulk_density_medio:  float
    # Comparação T0 vs T1
    soc_t0_referencia:   float   # baseline (primeiro ciclo ou dado histórico)
    delta_soc_estimado:  float   # T1 - T0
    # Para mrv_calculator.py
    soc_t0_pct:          float   # input direto
    soc_t1_pct:          float   # input direto
    # Qualidade
    cobertura_espacial:  float   # % da área com pontos coletados
    incerteza_soc:       float   # ±% SOC (propagação do erro NIR)
    apto_vm0042:         bool    # True se atende critérios mínimos
    pontos:              list = field(default_factory=list)


# ── CALIBRAÇÃO NIR ────────────────────────────────────────────────────────────

def calibrar_soc_nir(
    soc_nir: float,
    zona: str,
    profundidade: int,
    r2: float,
) -> tuple[float, float]:
    """
    Calibra a leitura NIR contra curvas de referência do Cerrado.

    O AgroCares usa modelos NIR treinados em base global. Para o Cerrado
    (Latossolo Vermelho-Amarelo), aplicamos uma correção regional baseada
    em estudos da Embrapa Cerrados (Reatto et al. 2008, Marchão et al. 2015).

    Correções aplicadas:
      - Fator de solo: Latossolo subestima SOC em ~8% vs modelo global
      - Fator de profundidade: camadas mais profundas têm menor acurácia
      - Fator de zona: cerrado nativo tem maior teor de carvão pirogênico
        (black carbon) que pode inflar leitura NIR em ~5%

    Retorna: (soc_calibrado, incerteza_absoluta)
    """
    # Fator de correção regional — Latossolo Cerrado
    fator_solo = 1.08   # NIR subestima 8% para Latossolo

    # Fator de profundidade
    fatores_prof = {10: 1.00, 20: 1.02, 30: 1.05}
    fator_prof = fatores_prof.get(profundidade, 1.03)

    # Fator de zona (black carbon em reserva nativa)
    if zona == "reserva":
        fator_zona = 0.96   # corrige superestimativa de 4% por black carbon
    else:
        fator_zona = 1.00

    soc_cal = soc_nir * fator_solo * fator_prof * fator_zona

    # Incerteza propaga com a qualidade do modelo (R²)
    incerteza_base = NIR_INCERTEZA_SOC_PCT
    penalidade_r2  = max(0, (NIR_R2_MINIMO - r2) * 0.5) if r2 < NIR_R2_MINIMO else 0
    incerteza      = incerteza_base + penalidade_r2

    return round(soc_cal, 4), round(incerteza, 4)


def qc_leitura(leitura: LeituraNIR) -> str:
    """
    Controle de qualidade de uma leitura NIR.
    Retorna: "OK" | "REVISAR" | "EXCLUIR"
    """
    # R² mínimo VM0042 Appendix 4
    if leitura.r2_modelo < 0.75:
        return "EXCLUIR"
    if leitura.r2_modelo < NIR_R2_MINIMO:
        return "REVISAR"

    # Valores fora de range físico para Cerrado
    if not (0.3 <= leitura.soc_nir_pct <= 8.0):
        return "EXCLUIR"
    if not (0.80 <= leitura.bd_nir <= 1.70):
        return "REVISAR"
    if not (3.5 <= leitura.ph_nir <= 7.5):
        return "REVISAR"

    return "OK"


# ── AGREGAÇÃO POR PONTO ───────────────────────────────────────────────────────

def agregar_ponto(
    ponto_id: str,
    leituras: list[LeituraNIR],
) -> Optional[PontoCalibrado]:
    """
    Agrega as 3 leituras de profundidade de um ponto em um PontoCalibrado.
    Descarta pontos com flag EXCLUIR em qualquer profundidade.
    """
    validas = [l for l in leituras if l.flag_qc != "EXCLUIR"]
    if len(validas) == 0:
        return None

    # Ordena por profundidade
    por_prof = {l.profundidade: l for l in validas}

    # SOC por camada (calibrado)
    def get_soc(prof):
        l = por_prof.get(prof)
        if l is None:
            # Interpola se faltando uma camada
            disponivel = list(por_prof.values())
            if disponivel:
                soc_cal, _ = calibrar_soc_nir(
                    np.mean([x.soc_nir_pct for x in disponivel]),
                    disponivel[0].zona, prof,
                    np.mean([x.r2_modelo for x in disponivel])
                )
                return soc_cal
            return CERRADO_SOC_BASELINE
        soc_cal, _ = calibrar_soc_nir(l.soc_nir_pct, l.zona, prof, l.r2_modelo)
        return soc_cal

    soc_10 = get_soc(10)
    soc_20 = get_soc(20)
    soc_30 = get_soc(30)

    # Média ponderada igual (VM0042: peso uniforme por camada)
    soc_medio = (soc_10 + soc_20 + soc_30) / 3

    ref = validas[0]
    r2_medio = np.mean([l.r2_modelo for l in validas])
    flag = "REVISAR" if any(l.flag_qc == "REVISAR" for l in validas) else "OK"

    return PontoCalibrado(
        ponto_id=ponto_id,
        latitude=ref.latitude,
        longitude=ref.longitude,
        zona=ref.zona,
        soc_0_10_pct=round(soc_10, 4),
        soc_10_20_pct=round(soc_20, 4),
        soc_20_30_pct=round(soc_30, 4),
        soc_medio_pct=round(soc_medio, 4),
        bulk_density=round(ref.bd_nir * 1.02, 3),   # leve correção Latossolo
        ph=round(ref.ph_nir, 2),
        umidade_pct=round(ref.umidade_pct, 1),
        n_leituras=len(validas),
        r2_medio=round(float(r2_medio), 3),
        flag_qc=flag,
        confianca_pct=95.0 if flag == "OK" else 80.0,
    )


# ── ANÁLISE DA FAZENDA ────────────────────────────────────────────────────────

def analisar_solo(
    pontos: list[PontoCalibrado],
    cpa_id: str,
    fazenda: str,
    area_ha: float,
    soc_t0_referencia: float = None,
) -> ResultadoSolo:
    """
    Agrega todos os pontos calibrados em resultado por zona.
    Calcula SOC médio por zona e prepara inputs para mrv_calculator.py.
    """
    validos = [p for p in pontos if p.flag_qc != "EXCLUIR"]
    print(f"\n  📊 Pontos válidos: {len(validos)}/{len(pontos)}")

    def media_zona(zona):
        pts = [p for p in validos if p.zona == zona]
        if not pts:
            return CERRADO_SOC_BASELINE, 0
        return round(float(np.mean([p.soc_medio_pct for p in pts])), 4), len(pts)

    soc_soil, n_soil = media_zona("solo_agricola")
    soc_redd, n_redd = media_zona("reserva")
    soc_arr,  n_arr  = media_zona("restauracao")

    # SOC geral ponderado pela área
    pesos = {
        "solo_agricola": 0.75,
        "reserva":       0.20,
        "restauracao":   0.05,
    }
    soc_geral = (
        soc_soil * pesos["solo_agricola"] +
        soc_redd * pesos["reserva"] +
        soc_arr  * pesos["restauracao"]
    )

    bd_medio = float(np.mean([p.bulk_density for p in validos])) if validos else CERRADO_BD_PADRAO

    # T0 de referência (baseline)
    # Se não fornecido, usa o SOC da zona de pastagem como proxy do estado inicial
    if soc_t0_referencia is None:
        soc_t0_referencia = CERRADO_SOC_BASELINE

    delta = round(soc_soil - soc_t0_referencia, 4)

    # Cobertura espacial: pontos/ha × fator de representatividade
    # VM0042: mínimo de 1 ponto por zona homogênea
    cobertura = min(100.0, len(validos) / area_ha * 100 * 10)

    # Incerteza propagada
    if validos:
        r2_medio_geral = float(np.mean([p.r2_medio for p in validos]))
        incerteza = NIR_INCERTEZA_SOC_PCT * (1 + max(0, NIR_R2_MINIMO - r2_medio_geral))
    else:
        incerteza = NIR_INCERTEZA_SOC_PCT * 2

    # Critério VM0042 Appendix 4
    apto = (
        len(validos) >= 5 and
        cobertura >= 30 and
        incerteza <= 0.15
    )

    return ResultadoSolo(
        cpa_id=cpa_id,
        fazenda=fazenda,
        data_coleta=datetime.now().strftime("%Y-%m-%d"),
        n_pontos_total=len(pontos),
        n_pontos_validos=len(validos),
        soc_solo_agricola=soc_soil,
        soc_reserva=soc_redd,
        soc_restauracao=soc_arr,
        soc_fazenda_media=round(soc_geral, 4),
        bulk_density_medio=round(bd_medio, 3),
        soc_t0_referencia=soc_t0_referencia,
        delta_soc_estimado=delta,
        soc_t0_pct=soc_t0_referencia,
        soc_t1_pct=soc_soil,  # SOC atual da área agrícola = T1
        cobertura_espacial=round(cobertura, 1),
        incerteza_soc=round(incerteza, 4),
        apto_vm0042=apto,
        pontos=[asdict(p) for p in validos],
    )


# ── MODO DEMO ─────────────────────────────────────────────────────────────────

def gerar_leituras_demo(
    fazenda_key: str = "itumbiara",
    n_pontos: int = 40,
    soc_t0: float = 1.800,
) -> list[LeituraNIR]:
    """
    Simula leituras do sensor AgroCares para uma fazenda do Cerrado.

    Distribui pontos pelas três zonas proporcionalmente às áreas:
      solo_agricola: 75% dos pontos
      reserva:       20% dos pontos
      restauracao:   5%  dos pontos

    SOC simulado com base em valores Embrapa Cerrados:
      pastagem/lavoura: 1.7–2.2%
      reserva nativa:   2.8–3.8%
      restauração:      1.5–2.0% (solo degradado em recuperação)
    """
    from mrv.satellite import FAZENDAS
    fazenda = FAZENDAS.get(fazenda_key, {"nome": "Fazenda Demo", "bbox": [-49.28, -18.45, -49.15, -18.35], "area_ha": 800, "cpa_id": "CPA-GO-001"})

    bbox = fazenda["bbox"]
    np.random.seed(42)
    leituras = []
    pid = 0

    distribuicao = [
        ("solo_agricola", int(n_pontos * 0.75), CERRADO_SOC_LAVOURA,   0.18),
        ("reserva",       int(n_pontos * 0.20), CERRADO_SOC_FLORESTA,  0.22),
        ("restauracao",   max(2, int(n_pontos * 0.05)), CERRADO_SOC_BASELINE * 0.9, 0.12),
    ]

    for zona, n, soc_base, soc_std in distribuicao:
        for _ in range(n):
            lat = np.random.uniform(bbox[1], bbox[3])
            lon = np.random.uniform(bbox[0], bbox[2])
            # Simula tendência de aumento de SOC ao longo do tempo
            soc_atual = soc_base + np.random.normal(0.011, 0.003)  # ganho anual

            for prof in PROFUNDIDADES_CM:
                # SOC diminui com a profundidade (~15% por camada)
                fator_prof = 1.0 - (prof / 10 - 1) * 0.12
                soc_prof   = max(0.3, soc_atual * fator_prof + np.random.normal(0, soc_std * 0.3))
                bd_prof    = CERRADO_BD_PADRAO + np.random.normal(0, 0.05) + (prof / 10 - 1) * 0.03
                r2         = np.random.uniform(0.86, 0.97)

                leitura = LeituraNIR(
                    ponto_id=f"P{pid:03d}-{prof}cm",
                    latitude=round(lat, 6),
                    longitude=round(lon, 6),
                    profundidade=prof,
                    zona=zona,
                    soc_nir_pct=round(soc_prof, 4),
                    bd_nir=round(bd_prof, 3),
                    ph_nir=round(np.random.uniform(4.8, 6.2), 2),
                    umidade_pct=round(np.random.uniform(18, 35), 1),
                    r2_modelo=round(r2, 3),
                    timestamp=datetime.now().isoformat(),
                )
                leitura.flag_qc = qc_leitura(leitura)
                leituras.append(leitura)
            pid += 1

    return leituras


# ── PIPELINE PRINCIPAL ────────────────────────────────────────────────────────

def processar_fazenda(
    fazenda_key: str = "itumbiara",
    json_path: Path = None,
    soc_t0: float = CERRADO_SOC_BASELINE,
    verbose: bool = True,
) -> ResultadoSolo:
    """
    Pipeline completo NIR para uma fazenda.
    Gera o resultado de solo pronto para o mrv_calculator.py.
    """
    from mrv.satellite import FAZENDAS
    fazenda_info = FAZENDAS.get(fazenda_key, {})
    cpa_id   = fazenda_info.get("cpa_id", "CPA-GO-001")
    nome     = fazenda_info.get("nome", "Fazenda Demo")
    area_ha  = fazenda_info.get("area_ha", 800)

    if verbose:
        print(f"\n🌱 CarbonChain — NIR Model")
        print(f"   Fazenda: {nome}")
        print(f"   CPA ID:  {cpa_id}")
        print("=" * 50)

    # ── Carrega ou gera leituras ──
    if json_path and json_path.exists():
        print(f"\n  📥 Carregando leituras: {json_path}")
        with open(json_path, encoding="utf-8") as f:
            raw = json.load(f)
        leituras = [LeituraNIR(**l) for l in raw["leituras"]]
    else:
        if verbose:
            print(f"\n  🧪 Modo demo — simulando {40} leituras AgroCares")
        leituras = gerar_leituras_demo(fazenda_key, n_pontos=40, soc_t0=soc_t0)

    if verbose:
        print(f"  Total leituras brutas: {len(leituras)}")
        ok   = sum(1 for l in leituras if l.flag_qc == "OK")
        rev  = sum(1 for l in leituras if l.flag_qc == "REVISAR")
        exc  = sum(1 for l in leituras if l.flag_qc == "EXCLUIR")
        print(f"  QC: OK={ok}  REVISAR={rev}  EXCLUIR={exc}")

    # ── Agrupa por ponto (3 profundidades por ponto) ──
    por_ponto: dict[str, list[LeituraNIR]] = {}
    for l in leituras:
        pid = l.ponto_id.split("-")[0]
        por_ponto.setdefault(pid, []).append(l)

    # ── Calibra e agrega cada ponto ──
    pontos_calibrados = []
    for pid, lts in por_ponto.items():
        pc = agregar_ponto(pid, lts)
        if pc:
            pontos_calibrados.append(pc)

    if verbose:
        print(f"  Pontos calibrados: {len(pontos_calibrados)}")

    # ── Analisa o solo da fazenda ──
    resultado = analisar_solo(
        pontos_calibrados,
        cpa_id=cpa_id,
        fazenda=nome,
        area_ha=area_ha,
        soc_t0_referencia=soc_t0,
    )

    # ── Imprime resumo ──
    if verbose:
        print(f"\n  ─── SOC por zona ───")
        print(f"    Solo agrícola (SOIL): {resultado.soc_solo_agricola:.3f}%")
        print(f"    Reserva Legal (REDD): {resultado.soc_reserva:.3f}%")
        print(f"    Restauração (ARR):    {resultado.soc_restauracao:.3f}%")
        print(f"    Média fazenda:        {resultado.soc_fazenda_media:.3f}%")
        print(f"    Bulk density:         {resultado.bulk_density_medio:.2f} g/cm³")
        print(f"\n  ─── T0 vs T1 (VM0042) ───")
        print(f"    T0 (baseline):  {resultado.soc_t0_pct:.3f}%")
        print(f"    T1 (atual):     {resultado.soc_t1_pct:.3f}%")
        print(f"    Δ SOC:          {resultado.delta_soc_estimado:+.4f}%")
        print(f"\n  ─── Qualidade ───")
        print(f"    Cobertura espacial: {resultado.cobertura_espacial:.0f}%")
        print(f"    Incerteza SOC:      ±{resultado.incerteza_soc:.3f}%")
        print(f"    Apto VM0042:        {'✓ SIM' if resultado.apto_vm0042 else '⚠ NÃO — coletar mais pontos'}")

    # ── Salva JSON ──
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    out_fn = DATA_DIR / f"solo_calibrado_{cpa_id}.json"
    with open(out_fn, "w", encoding="utf-8") as f:
        json.dump(asdict(resultado), f, ensure_ascii=False, indent=2)
    print(f"\n  ✓ JSON salvo: {out_fn}")
    print(f"  → Use soc_t0={resultado.soc_t0_pct} soc_t1={resultado.soc_t1_pct} no mrv_calculator.py")
    print("=" * 50)

    return resultado


def processar_rodada(fazenda_keys: list = None):
    """Processa todas as fazendas cadastradas."""
    from mrv.satellite import FAZENDAS
    keys = fazenda_keys or list(FAZENDAS.keys())

    print(f"\n🗂️  Processando {len(keys)} fazendas...\n")
    resultados = {}
    for key in keys:
        res = processar_fazenda(key)
        resultados[key] = {
            "cpa_id":  res.cpa_id,
            "soc_t0":  res.soc_t0_pct,
            "soc_t1":  res.soc_t1_pct,
            "delta":   res.delta_soc_estimado,
            "apto":    res.apto_vm0042,
        }
        print()

    print("\n📋 Resumo da rodada:")
    print(f"  {'CPA':<15} {'T0':>6} {'T1':>6} {'Δ':>7}  Apto")
    print("  " + "─" * 40)
    for key, r in resultados.items():
        print(f"  {r['cpa_id']:<15} {r['soc_t0']:>6.3f} {r['soc_t1']:>6.3f} "
              f"{r['delta']:>+7.4f}  {'✓' if r['apto'] else '⚠'}")

    return resultados


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CarbonChain — NIR Model (AgroCares → SOC calibrado)"
    )
    parser.add_argument("--farm", default="itumbiara",
                        help="Fazenda a processar")
    parser.add_argument("--all", action="store_true",
                        help="Processar todas as fazendas")
    parser.add_argument("--input", default=None,
                        help="JSON com leituras reais do AgroCares")
    parser.add_argument("--soc-t0", type=float, default=CERRADO_SOC_BASELINE,
                        help=f"SOC baseline T0 %% (default: {CERRADO_SOC_BASELINE})")
    args = parser.parse_args()

    if args.all:
        processar_rodada()
    else:
        json_path = Path(args.input) if args.input else None
        processar_fazenda(
            fazenda_key=args.farm,
            json_path=json_path,
            soc_t0=args.soc_t0,
        )


if __name__ == "__main__":
    main()
