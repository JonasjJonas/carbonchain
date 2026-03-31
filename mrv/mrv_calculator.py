"""
CarbonChain — mrv_calculator.py  v1.0
======================================
Pipeline MRV completo: lê o JSON do satellite.py,
aplica as fórmulas VM0042 v2.2 e calcula os créditos
por ativo (SOIL, REDD, ARR) prontos para o mint CCT-*.

Fluxo:
  satellite.py → resultado_sat_CPA-GO-001.json
       ↓
  mrv_calculator.py (este arquivo)
       ↓
  resultado_mrv_CPA-GO-001.json  → CCTFactory.sol (mint)

Fórmulas aplicadas (VM0042 v2.2 §6):
  ΔC_SOC  = (SOC_t1 - SOC_t0) × BD × D × 10_000 × (44/12)
  N2O_red = ΔFertilizante × EF × 44/28 × GWP_N2O
  CH4_red = ΔQueima × EF_CH4 × GWP_CH4
  Leakage = ΔSOC_total × fator_leakage
  Créditos_líquidos = (ΔC_SOC + N2O_red + CH4_red - Leakage)
                      × (1 - incerteza) × (1 - buffer)
"""

import json
import math
import argparse
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, asdict, field
from typing import Optional


# ── CONSTANTES VM0042 v2.2 ────────────────────────────────────────────────────

# Conversão C → CO₂e
C_TO_CO2 = 44 / 12          # = 3.6667

# Potencial de aquecimento global (AR6 — IPCC 2021)
GWP_N2O  = 273              # N₂O em 100 anos
GWP_CH4  = 27.9             # CH₄ em 100 anos

# Fatores de emissão padrão (IPCC Tier 1 para Cerrado)
EF_N2O_DIRECT   = 0.01      # 1% do N aplicado emite N₂O diretamente
EF_N2O_INDIRECT = 0.0075    # 0.75% indireto (volatilização + lixiviação)
EF_CH4_QUEIMA   = 6.8       # kg CH₄ / t biomassa queimada

# Parâmetros de solo padrão Latossolo Vermelho-Amarelo (Cerrado)
BULK_DENSITY_PADRAO = 1.20  # g/cm³ — Latossolo típico sul de Goiás
PROFUNDIDADE_CM     = 30    # cm — VM0042 §4.2
FATOR_LEAKAGE       = 0.05  # 5% leakage de maquinário (VM0042 §8)

# ── PARÂMETROS VM0015 — REDD+ (Reserva Legal) ──
# Referências: IPCC 2006 AFOLU, MapBiomas 2024, Souza et al. 2020
TAXA_DESMATAMENTO_CERRADO = 0.0058  # 0.58%/ano — taxa histórica sul de Goiás (PRODES/INPE)
CARBONO_ACIMA_SOLO_CERRADO = 42.0   # tC/ha acima do solo — Cerrado típico (sensu stricto)
CARBONO_ABAIXO_SOLO_CERRADO= 28.0   # tC/ha abaixo do solo + serapilheira
CARBONO_TOTAL_CERRADO      = CARBONO_ACIMA_SOLO_CERRADO + CARBONO_ABAIXO_SOLO_CERRADO  # 70 tC/ha
FATOR_LEAKAGE_REDD          = 0.10  # 10% leakage para REDD (deslocamento de pressão)

# Descontos Verra
DESCONTO_INCERTEZA = 0.20
BUFFER_PERMANENCIA = 0.15

# Preços de referência (USD/tCO₂e) — guia de mercado 2025
PRECOS_REFERENCIA = {
    "SOIL": 9,    # VM0042 — solo agrícola
    "REDD": 54,   # VM0015 — REDD+ com CCP label (inclui Reserva Legal)
    "ARR":  76,   # VM0047 — restauração/reflorestamento
}

# Distribuição padrão de área (800ha base)
DIST_AREA = {
    "solo_agricola_pct": 0.75,   # 600ha / 800ha
    "reserva_pct":       0.20,   # 160ha / 800ha
    "restauracao_pct":   0.05,   #  40ha / 800ha
}


# ── DATA CLASSES ──────────────────────────────────────────────────────────────

@dataclass
class DadosSolo:
    """Dados de entrada de solo para cálculo ΔC_SOC."""
    cpa_id:          str
    zona:            str        # "solo_agricola" | "reserva" | "restauracao"
    area_ha:         float
    soc_t0_pct:      float      # SOC baseline (ano 0) em %
    soc_t1_pct:      float      # SOC atual (ano t) em %
    bulk_density:    float = BULK_DENSITY_PADRAO
    profundidade_cm: float = PROFUNDIDADE_CM
    # Práticas agrícolas para cálculo N2O/CH4
    fertilizante_n_kg_ha: float = 120.0   # kg N/ha/ano (média Cerrado)
    reducao_fertilizante_pct: float = 0.15  # 15% redução c/ plantio direto
    area_queimada_ha: float = 0.0          # ha afetados por fogo (padrão 0)


@dataclass
class ResultadoAtivo:
    """Resultado calculado para um ativo de carbono."""
    tipo:              str    # SOIL | REDD | ARR
    area_ha:           float
    delta_soc_tco2e:   float  # ΔC_SOC em tCO₂e bruto
    n2o_reducao_tco2e: float  # Redução emissões N₂O
    ch4_reducao_tco2e: float  # Redução emissões CH₄
    leakage_tco2e:     float  # Leakage estimado
    bruto_tco2e:       float  # Total antes dos descontos
    apos_incerteza:    float  # Após 20% de incerteza
    apos_buffer:       float  # Após 15% de buffer (créditos vendáveis)
    vcus_emitidos:     float  # VCUs = tCO₂e vendáveis (arredondado)
    receita_bruta_usd: float  # VCUs × preço de referência
    caixa_cc_usd:      float  # 20% para CarbonChain
    caixa_prod_usd:    float  # 80% para o produtor


@dataclass
class ResultadoFazenda:
    """Resultado consolidado de uma fazenda."""
    cpa_id:          str
    fazenda:         str
    area_ha:         float
    periodo:         str
    data_calculo:    str
    metodologia:     str = "VM0042 v2.2 + VM0015 + VM0047"
    ativos:          list = field(default_factory=list)
    # Totais consolidados
    total_bruto_tco2e:   float = 0.0
    total_vcus:          float = 0.0
    total_receita_usd:   float = 0.0
    total_caixa_cc_usd:  float = 0.0
    total_caixa_prod_usd:float = 0.0
    # Metadados de qualidade
    fonte_satellite:     str = ""
    ndvi_medio:          float = 0.0
    soc_proxy:           float = 0.0
    additionality_ok:    bool = True


# ── CÁLCULOS VM0042 ───────────────────────────────────────────────────────────

def calcular_delta_soc(dados: DadosSolo) -> float:
    """
    ΔC_SOC — mudança no estoque de carbono orgânico do solo.

    Fórmula VM0042 v2.2 §6.1:
      ΔSOC = (SOC_t1 - SOC_t0) × BD × D × 10.000 × (44/12)

    Onde:
      SOC_t1, SOC_t0 = % carbono orgânico (frações decimais)
      BD              = bulk density (g/cm³)
      D               = profundidade (cm)
      10.000          = conversão ha → cm² (×10000 m²/ha × 10000 cm²/m² / 10000)
                        simplificado: ×100 (t/ha de carbono)
      44/12           = conversão C → CO₂e

    Resultado em tCO₂e/ha/ano.
    """
    soc_t0 = dados.soc_t0_pct / 100
    soc_t1 = dados.soc_t1_pct / 100
    delta_soc_fracao = soc_t1 - soc_t0

    # Conversão de unidades (prova completa):
    # delta_c (g/cm²) = delta_frac × BD(g/cm³) × D(cm)
    # → tC/ha: g/cm² × (10^8 cm²/ha) ÷ (10^6 g/t) = g/cm² × 100
    # Ou passo a passo: g/cm² → kg/m² (×10) → t/ha (×10) → total ×100
    delta_c_t_ha = delta_soc_fracao * dados.bulk_density * dados.profundidade_cm * 100

    # Converte para tCO₂e/ha
    delta_co2e_ha = delta_c_t_ha * C_TO_CO2

    # Total para a área
    return delta_co2e_ha * dados.area_ha


def calcular_reducao_n2o(dados: DadosSolo) -> float:
    """
    Redução de emissões N₂O pela mudança de manejo de fertilizantes.

    VM0042 v2.2 §6.3 — emissões N₂O diretas + indiretas:
      N₂O_emissao = N_aplicado × (EF_direto + EF_indireto) × (44/28) × GWP

    A redução vem da diminuição de N aplicado com plantio direto/SPD.
    """
    n_aplicado_ha  = dados.fertilizante_n_kg_ha
    reducao_n      = n_aplicado_ha * dados.reducao_fertilizante_pct  # kg N/ha reduzidos

    # N₂O emitido por kg de N: (direto + indireto) × conversão N→N₂O (44/28)
    ef_total  = EF_N2O_DIRECT + EF_N2O_INDIRECT
    n2o_kg_ha = reducao_n * ef_total * (44 / 28)

    # Converte kg N₂O/ha → tCO₂e/ha
    co2e_ha = n2o_kg_ha * GWP_N2O / 1000

    return co2e_ha * dados.area_ha


def calcular_reducao_ch4(dados: DadosSolo) -> float:
    """
    Redução de emissões CH₄ pela eliminação de queima de biomassa.

    VM0042 v2.2 §6.4:
      CH₄_emissao = Biomassa_queimada × EF_CH4 × GWP_CH4
    """
    if dados.area_queimada_ha <= 0:
        return 0.0

    # Biomassa média Cerrado: 8 t/ha (pastagem) a 25 t/ha (cerradão)
    biomassa_t_ha = 12.0  # t biomassa seca/ha — média Cerrado degradado
    ch4_kg_ha = biomassa_t_ha * EF_CH4_QUEIMA
    co2e_ha   = ch4_kg_ha * GWP_CH4 / 1000

    return co2e_ha * dados.area_queimada_ha


def calcular_leakage(bruto_tco2e: float) -> float:
    """
    Leakage de atividade — deslocamento de emissões para fora da área.

    VM0042 v2.2 §8: Para projetos ALM, o leakage principal vem do
    aumento de uso de maquinário (maior consumo de diesel). 
    Fator conservador: 5% do bruto.
    """
    return bruto_tco2e * FATOR_LEAKAGE


def calcular_redd_vm0015(area_ha: float) -> float:
    """
    Créditos REDD+ via VM0015 — emissões evitadas por preservação da Reserva Legal.

    Lógica: a Reserva Legal seria desmatada à taxa histórica regional
    sem o projeto. O projeto evita esse desmatamento. Os créditos
    representam o carbono que teria sido liberado.

    Fórmula VM0015 §6 (simplificada para PoA):
      REDD = Area × Taxa_desmatamento × Carbono_total × C_to_CO2 × (1 - Leakage)

    Onde:
      Area              = área da Reserva Legal em ha
      Taxa_desmatamento = taxa histórica PRODES/INPE para a região (0.58%/ano sul de GO)
      Carbono_total     = tC/ha na biomassa acima + abaixo do solo (70 tC/ha Cerrado)
      C_to_CO2          = 44/12 = 3.667
      Leakage           = 10% (pressão de desmatamento deslocada para fora da área)

    Retorna tCO₂e/ano bruto (antes dos descontos Verra).
    """
    emissoes_evitadas = (
        area_ha
        * TAXA_DESMATAMENTO_CERRADO
        * CARBONO_TOTAL_CERRADO
        * C_TO_CO2
    )
    return emissoes_evitadas * (1 - FATOR_LEAKAGE_REDD)


def aplicar_descontos(bruto: float) -> tuple[float, float, float]:
    """
    Aplica os dois descontos Verra em sequência:
      1. Desconto de incerteza 20%
      2. Buffer de permanência 15%

    Retorna: (após_incerteza, após_buffer, vcus_emitidos)
    """
    apos_incerteza = bruto * (1 - DESCONTO_INCERTEZA)
    apos_buffer    = apos_incerteza * (1 - BUFFER_PERMANENCIA)
    vcus           = math.floor(apos_buffer)  # VCUs são inteiros
    return apos_incerteza, apos_buffer, float(vcus)


def calcular_receitas(vcus: float, tipo: str) -> tuple[float, float, float]:
    """
    Calcula as receitas a partir dos VCUs emitidos.
    Retorna: (receita_bruta, caixa_cc, caixa_produtor)
    """
    preco          = PRECOS_REFERENCIA.get(tipo, 9)
    receita_bruta  = vcus * preco
    caixa_cc       = receita_bruta * 0.20
    caixa_produtor = receita_bruta * 0.80
    return receita_bruta, caixa_cc, caixa_produtor


# ── CÁLCULO POR ATIVO ─────────────────────────────────────────────────────────

def calcular_ativo_redd(area_ha: float, cpa_id: str = "") -> ResultadoAtivo:
    """
    Calcula créditos CCT-REDD via VM0015 (emissões evitadas).
    Diferente do SOIL/ARR — não usa delta SOC, usa área × taxa × carbono.
    """
    bruto      = calcular_redd_vm0015(area_ha)
    # Leakage já está dentro do calcular_redd_vm0015
    apos_inc, apos_buf, vcus = aplicar_descontos(bruto)
    receita, cc, prod = calcular_receitas(vcus, "REDD")

    return ResultadoAtivo(
        tipo="REDD",
        area_ha=area_ha,
        delta_soc_tco2e=0.0,        # REDD não usa delta SOC
        n2o_reducao_tco2e=0.0,
        ch4_reducao_tco2e=0.0,
        leakage_tco2e=round(calcular_redd_vm0015(area_ha) / (1 - FATOR_LEAKAGE_REDD)
                            * FATOR_LEAKAGE_REDD, 2),  # leakage deduzido
        bruto_tco2e=round(bruto, 2),
        apos_incerteza=round(apos_inc, 2),
        apos_buffer=round(apos_buf, 2),
        vcus_emitidos=vcus,
        receita_bruta_usd=round(receita, 2),
        caixa_cc_usd=round(cc, 2),
        caixa_prod_usd=round(prod, 2),
    )


def calcular_ativo(
    tipo: str,
    area_ha: float,
    soc_t0: float,
    soc_t1: float,
    bulk_density: float = BULK_DENSITY_PADRAO,
    fertilizante_n: float = 120.0,
    reducao_fertilizante: float = 0.15,
    area_queimada: float = 0.0,
    cpa_id: str = "",
) -> ResultadoAtivo:
    """
    Calcula os créditos de carbono para um ativo específico.
    """
    dados = DadosSolo(
        cpa_id=cpa_id,
        zona=tipo.lower(),
        area_ha=area_ha,
        soc_t0_pct=soc_t0,
        soc_t1_pct=soc_t1,
        bulk_density=bulk_density,
        fertilizante_n_kg_ha=fertilizante_n,
        reducao_fertilizante_pct=reducao_fertilizante,
        area_queimada_ha=area_queimada,
    )

    # Componentes do cálculo
    delta_soc  = calcular_delta_soc(dados)
    n2o_red    = calcular_reducao_n2o(dados) if tipo == "SOIL" else 0.0
    ch4_red    = calcular_reducao_ch4(dados)
    bruto      = delta_soc + n2o_red + ch4_red
    leakage    = calcular_leakage(bruto)
    bruto_liq  = max(0.0, bruto - leakage)

    # Descontos Verra
    apos_inc, apos_buf, vcus = aplicar_descontos(bruto_liq)

    # Receitas
    receita, cc, prod = calcular_receitas(vcus, tipo)

    return ResultadoAtivo(
        tipo=tipo,
        area_ha=area_ha,
        delta_soc_tco2e=round(delta_soc, 2),
        n2o_reducao_tco2e=round(n2o_red, 2),
        ch4_reducao_tco2e=round(ch4_red, 2),
        leakage_tco2e=round(leakage, 2),
        bruto_tco2e=round(bruto_liq, 2),
        apos_incerteza=round(apos_inc, 2),
        apos_buffer=round(apos_buf, 2),
        vcus_emitidos=vcus,
        receita_bruta_usd=round(receita, 2),
        caixa_cc_usd=round(cc, 2),
        caixa_prod_usd=round(prod, 2),
    )


# ── PIPELINE PRINCIPAL ────────────────────────────────────────────────────────

def calcular_fazenda(
    sat_json_path: Path,
    soc_t0_pct: Optional[float] = None,
    soc_t1_pct: Optional[float] = None,
    periodo: str = None,
    verbose: bool = True,
) -> ResultadoFazenda:
    """
    Pipeline MRV completo para uma fazenda.

    Lê o JSON do satellite.py e calcula os créditos dos 3 ativos:
      SOIL (VM0042) — solo agrícola em transição regenerativa
      REDD (VM0015) — Reserva Legal com vegetação nativa preservada
      ARR  (VM0047) — área em restauração ativa

    Parâmetros SOC:
      soc_t0_pct: SOC baseline em % (medido no campo no T0). Se None, deriva do soc_proxy.
      soc_t1_pct: SOC atual em % (medido no campo neste ciclo). Se None, deriva do soc_proxy.

    Derivação automática do soc_proxy (índice 0-1):
      O soc_proxy do satellite.py é um índice relativo (NDWI+NDVI). Para converter
      em % de SOC real (Latossolo Cerrado típico: 1.2% a 3.5%):
        SOC_real ≈ soc_proxy × 3.5%  (regressão calibrada AgroCares)
      T0 = SOC_real (baseline estimada sem manejo)
      T1 = T0 + Δ realista (0.011%/ano para Cerrado iLPF/plantio direto)
    """
    # ── Carrega dados do satélite ──
    with open(sat_json_path, encoding="utf-8") as f:
        sat = json.load(f)

    meta   = sat["metadata"]
    eleg   = sat["elegibilidade"]
    ndvi   = sat["indices"]["ndvi_medio"]
    soc_px = sat["indices"]["soc_proxy"]
    add_ok = eleg["additionality_ok"]

    cpa_id  = meta["cpa_id"]
    fazenda = meta["fazenda"]
    area_ha = meta["area_ha"]

    # ── Deriva SOC do soc_proxy se não fornecido manualmente ──
    SOC_MAX_PCT = 3.5   # teto de SOC% para Latossolo Cerrado
    DELTA_SOC_ANO = 0.011  # Δ%/ano realista (iLPF / plantio direto)

    if soc_t0_pct is None:
        soc_t0_pct = round(soc_px * SOC_MAX_PCT, 3)
        if verbose:
            print(f"   ℹ️  SOC T0 derivado do soc_proxy ({soc_px:.4f}): {soc_t0_pct}%")
    if soc_t1_pct is None:
        soc_t1_pct = round(soc_t0_pct + DELTA_SOC_ANO, 3)
        if verbose:
            print(f"   ℹ️  SOC T1 estimado (T0 + Δ{DELTA_SOC_ANO}%/ano): {soc_t1_pct}%")

    if verbose:
        print(f"\n⚗️  CarbonChain — MRV Calculator")
        print(f"   Fazenda: {fazenda}")
        print(f"   CPA ID:  {cpa_id}")
        print(f"   Área:    {area_ha} ha")
        print("=" * 55)

    # ── Áreas por ativo (da análise satelital ou distribuição padrão) ──
    solo_ha    = eleg.get("solo_agricola_ha") or area_ha * DIST_AREA["solo_agricola_pct"]
    reserva_ha = eleg.get("reserva_ha")       or area_ha * DIST_AREA["reserva_pct"]
    rest_ha    = area_ha * DIST_AREA["restauracao_pct"]

    if verbose:
        print(f"\n📐 Áreas por ativo:")
        print(f"   SOIL (solo agrícola):  {solo_ha:.0f} ha")
        print(f"   REDD (Reserva Legal):  {reserva_ha:.0f} ha")
        print(f"   ARR  (restauração):    {rest_ha:.0f} ha")
        print(f"\n📊 SOC:  T0={soc_t0_pct}%  →  T1={soc_t1_pct}%  (Δ={soc_t1_pct-soc_t0_pct:.2f}%)")
        print(f"   Adicionalidade: {'✓ OK' if add_ok else '⚠️  Verificar'}")

    # ── Calcula os 3 ativos ──
    ativo_soil = calcular_ativo(
        tipo="SOIL", area_ha=solo_ha,
        soc_t0=soc_t0_pct, soc_t1=soc_t1_pct,
        fertilizante_n=120.0, reducao_fertilizante=0.15,
        cpa_id=cpa_id,
    )
    ativo_redd = calcular_ativo_redd(
        area_ha=reserva_ha,
        cpa_id=cpa_id,
    )
    ativo_arr = calcular_ativo(
        tipo="ARR", area_ha=rest_ha,
        # ARR: restauração ~0.5 tC/ha/ano (mais rápido — biomassa aérea + solo)
        # Solo degradado pré-restauração → Δ=0.014%/ano
        soc_t0=soc_t0_pct * 0.90,
        soc_t1=soc_t0_pct * 0.90 + 0.014,
        cpa_id=cpa_id,
    )

    if verbose:
        _print_ativo(ativo_soil)
        _print_ativo(ativo_redd)
        _print_ativo(ativo_arr)

    # ── Consolida resultado ──
    ativos = [ativo_soil, ativo_redd, ativo_arr]
    total_bruto  = sum(a.bruto_tco2e for a in ativos)
    total_vcus   = sum(a.vcus_emitidos for a in ativos)
    total_rec    = sum(a.receita_bruta_usd for a in ativos)
    total_cc     = sum(a.caixa_cc_usd for a in ativos)
    total_prod   = sum(a.caixa_prod_usd for a in ativos)

    resultado = ResultadoFazenda(
        cpa_id=cpa_id,
        fazenda=fazenda,
        area_ha=area_ha,
        periodo=periodo or f"{meta.get('data_imagem','')[:4]}-ciclo-1",
        data_calculo=datetime.now().isoformat(),
        ativos=[asdict(a) for a in ativos],
        total_bruto_tco2e=round(total_bruto, 2),
        total_vcus=total_vcus,
        total_receita_usd=round(total_rec, 2),
        total_caixa_cc_usd=round(total_cc, 2),
        total_caixa_prod_usd=round(total_prod, 2),
        fonte_satellite=str(sat_json_path),
        ndvi_medio=ndvi,
        soc_proxy=soc_px,
        additionality_ok=add_ok,
    )

    if verbose:
        _print_resumo(resultado)

    # ── Salva JSON ──
    out_dir = sat_json_path.parent
    out_fn  = out_dir / f"resultado_mrv_{cpa_id}.json"
    with open(out_fn, "w", encoding="utf-8") as f:
        json.dump(asdict(resultado), f, ensure_ascii=False, indent=2)
    print(f"\n  ✓ JSON salvo: {out_fn}")
    print(f"  → Pronto para mint CCT-SOIL, CCT-REDD, CCT-ARR via CCTFactory.sol")

    return resultado


# ── PRINT HELPERS ─────────────────────────────────────────────────────────────

def _print_ativo(a: ResultadoAtivo):
    """Imprime resultado de um ativo de forma legível."""
    metodo = {"SOIL": "VM0042", "REDD": "VM0015", "ARR": "VM0047"}.get(a.tipo, "")
    print(f"\n  ─── CCT-{a.tipo} ({a.area_ha:.0f} ha) [{metodo}] ───")
    if a.tipo == "REDD":
        print(f"    Emissões evitadas:   {a.bruto_tco2e + a.leakage_tco2e:>8.1f} tCO₂e (bruto)")
        print(f"    Leakage 10%:         {a.leakage_tco2e:>8.1f} tCO₂e")
    else:
        print(f"    ΔC_SOC:          {a.delta_soc_tco2e:>8.1f} tCO₂e")
        if a.n2o_reducao_tco2e:
            print(f"    N₂O reduzido:    {a.n2o_reducao_tco2e:>8.1f} tCO₂e")
        if a.ch4_reducao_tco2e:
            print(f"    CH₄ reduzido:    {a.ch4_reducao_tco2e:>8.1f} tCO₂e")
        print(f"    Leakage:         {a.leakage_tco2e:>8.1f} tCO₂e")
    print(f"    Bruto líquido:   {a.bruto_tco2e:>8.1f} tCO₂e")
    print(f"    – Incerteza 20%: {a.apos_incerteza:>8.1f} tCO₂e")
    print(f"    – Buffer 15%:    {a.apos_buffer:>8.1f} tCO₂e")
    print(f"    VCUs emitidos:   {a.vcus_emitidos:>8.0f}")
    print(f"    Receita bruta:   USD {a.receita_bruta_usd:>8,.0f}")
    print(f"    → Produtor 80%: USD {a.caixa_prod_usd:>8,.0f}")
    print(f"    → CC 20%:       USD {a.caixa_cc_usd:>8,.0f}")


def _print_resumo(r: ResultadoFazenda):
    """Imprime o resumo consolidado da fazenda."""
    print(f"\n{'='*55}")
    print(f"  TOTAL — {r.fazenda}")
    print(f"{'='*55}")
    print(f"  VCUs totais:       {r.total_vcus:>8.0f} tCO₂e")
    print(f"  Receita bruta:     USD {r.total_receita_usd:>8,.0f}")
    print(f"  Caixa produtor:    USD {r.total_caixa_prod_usd:>8,.0f}")
    print(f"  Caixa CC (20%):    USD {r.total_caixa_cc_usd:>8,.0f}")
    levy = r.total_vcus * 0.23
    print(f"  Levy Verra est.:   USD {levy:>8,.0f}  (USD 0,23/VCU)")
    print(f"  Caixa CC líquido:  USD {r.total_caixa_cc_usd - levy:>8,.0f}")
    print(f"{'='*55}")


# ── MODO MULTI-FAZENDA ────────────────────────────────────────────────────────

def calcular_rodada(
    data_dir: Path = Path("data/sample_farm"),
    soc_t0: Optional[float] = None,
    soc_t1: Optional[float] = None,
) -> dict:
    """
    Calcula os créditos de todas as fazendas com JSON no diretório.
    Retorna resumo consolidado da rodada.
    """
    jsons = sorted(data_dir.glob("resultado_sat_CPA-*.json"))
    if not jsons:
        print(f"⚠️  Nenhum arquivo resultado_sat_*.json encontrado em {data_dir}")
        return {}

    print(f"\n🗂️  Calculando {len(jsons)} fazendas da rodada...\n")

    resumo_rodada = {
        "n_fazendas":      len(jsons),
        "total_vcus":      0.0,
        "total_receita":   0.0,
        "total_caixa_cc":  0.0,
        "total_caixa_prod":0.0,
        "fazendas":        [],
    }

    for jp in jsons:
        res = calcular_fazenda(jp, soc_t0_pct=soc_t0, soc_t1_pct=soc_t1)
        resumo_rodada["total_vcus"]       += res.total_vcus
        resumo_rodada["total_receita"]    += res.total_receita_usd
        resumo_rodada["total_caixa_cc"]   += res.total_caixa_cc_usd
        resumo_rodada["total_caixa_prod"] += res.total_caixa_prod_usd
        resumo_rodada["fazendas"].append({
            "cpa_id":   res.cpa_id,
            "fazenda":  res.fazenda,
            "vcus":     res.total_vcus,
            "receita":  res.total_receita_usd,
        })
        print()

    # Resumo final da rodada
    print(f"\n{'═'*55}")
    print(f"  RESUMO DA RODADA — {len(jsons)} fazendas")
    print(f"{'═'*55}")
    print(f"  VCUs totais:       {resumo_rodada['total_vcus']:>8.0f}")
    print(f"  Receita total:     USD {resumo_rodada['total_receita']:>8,.0f}")
    print(f"  Caixa CC total:    USD {resumo_rodada['total_caixa_cc']:>8,.0f}")
    print(f"  Caixa prod total:  USD {resumo_rodada['total_caixa_prod']:>8,.0f}")
    levy_total = resumo_rodada["total_vcus"] * 0.23
    print(f"  Levy Verra total:  USD {levy_total:>8,.0f}")
    print(f"  CC líquido:        USD {resumo_rodada['total_caixa_cc'] - levy_total:>8,.0f}")
    print(f"{'═'*55}")

    # Salva resumo da rodada
    resumo_fn = data_dir / "resumo_rodada_mrv.json"
    with open(resumo_fn, "w", encoding="utf-8") as f:
        json.dump(resumo_rodada, f, ensure_ascii=False, indent=2)
    print(f"\n  ✓ Resumo salvo: {resumo_fn}")

    return resumo_rodada


# ── ENTRY POINT ───────────────────────────────────────────────────────────────

def _resolver_json_path(farm_arg: str) -> Path:
    """
    Resolve o argumento --farm para o caminho real do JSON.

    Aceita:
      1. Caminho completo: data/prospeccao/CPA-GO-002/resultado_sat_CPA-GO-002.json
      2. CPA ID curto:     CPA-GO-002  → data/prospeccao/CPA-GO-002/resultado_sat_CPA-GO-002.json
      3. Caminho legado:   data/sample_farm/resultado_sat_CPA-GO-001.json
    """
    p = Path(farm_arg)

    # 1. Se já é um arquivo que existe, retorna direto
    if p.is_file():
        return p

    # 2. Se parece um CPA ID (ex: CPA-GO-002), resolve na estrutura de prospecção
    if farm_arg.upper().startswith("CPA-"):
        cpa_id = farm_arg.upper()
        candidatos = [
            Path(f"data/prospeccao/{cpa_id}/resultado_sat_{cpa_id}.json"),
            Path(f"prospeccao/data/prospeccao/{cpa_id}/resultado_sat_{cpa_id}.json"),
            Path(f"data/sample_farm/resultado_sat_{cpa_id}.json"),
        ]
        for c in candidatos:
            if c.is_file():
                return c
        # Nenhum encontrado — mostra onde procurou
        print(f"❌ JSON não encontrado para '{cpa_id}'. Procurei em:")
        for c in candidatos:
            print(f"   → {c}")
        raise FileNotFoundError(f"Nenhum resultado_sat encontrado para {cpa_id}")

    # 3. Caminho passado não existe — erro claro
    raise FileNotFoundError(
        f"❌ Arquivo não encontrado: '{farm_arg}'\n"
        f"   Use o CPA ID (ex: --farm CPA-GO-002) ou o caminho completo do JSON."
    )


def main():
    parser = argparse.ArgumentParser(
        description="CarbonChain — MRV Calculator (VM0042 v2.2)"
    )
    parser.add_argument(
        "--farm", default=None,
        help="CPA ID (ex: CPA-GO-002) ou caminho do JSON do satellite.py"
    )
    parser.add_argument(
        "--all", action="store_true",
        help="Calcular todas as fazendas (busca em data/prospeccao/ e data/sample_farm/)"
    )
    parser.add_argument(
        "--soc-t0", type=float, default=None,
        help="SOC baseline T0 em %% (default: deriva do soc_proxy do JSON)"
    )
    parser.add_argument(
        "--soc-t1", type=float, default=None,
        help="SOC atual T1 em %% (default: deriva do soc_proxy do JSON)"
    )
    args = parser.parse_args()

    # Valores SOC: usa os passados manualmente, ou None para derivar do JSON
    soc_t0 = args.soc_t0
    soc_t1 = args.soc_t1

    if args.all:
        # Busca JSONs em ambos os diretórios
        dirs = [Path("data/prospeccao"), Path("data/sample_farm")]
        jsons_found = []
        for d in dirs:
            if d.is_dir():
                # Prospecção: data/prospeccao/CPA-*/resultado_sat_*.json
                jsons_found.extend(sorted(d.glob("**/resultado_sat_CPA-*.json")))
        if not jsons_found:
            print("⚠️  Nenhum resultado_sat_*.json encontrado em data/prospeccao/ ou data/sample_farm/")
            return
        print(f"\n🗂️  Encontrados {len(jsons_found)} JSONs de prospecção\n")
        for jp in jsons_found:
            calcular_fazenda(
                sat_json_path=jp,
                soc_t0_pct=soc_t0,
                soc_t1_pct=soc_t1,
            )
            print()
    elif args.farm:
        sat_path = _resolver_json_path(args.farm)
        calcular_fazenda(
            sat_json_path=sat_path,
            soc_t0_pct=soc_t0,
            soc_t1_pct=soc_t1,
        )
    else:
        # Modo demo: gera dados satelitais e calcula
        print("\n🧪 Modo demo — gerando dados satelitais e calculando créditos...\n")
        import subprocess, sys
        subprocess.run([sys.executable, "mrv/satellite.py", "--all"], check=True)
        calcular_rodada(
            data_dir=Path("data/sample_farm"),
            soc_t0=soc_t0 or 1.80,
            soc_t1=soc_t1 or 1.811,
        )


if __name__ == "__main__":
    main()
