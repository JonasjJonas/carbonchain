"""
CarbonChain — vm0042.py
Modelo de cálculo de créditos de carbono
Baseado na metodologia Verra VM0042 v2.1
"""

import json
import math
from dataclasses import dataclass, asdict
from typing import List


# ── CONSTANTES DA METODOLOGIA VM0042 ─────────────────────────
FATOR_C_CO2     = 44 / 12       # Conversão carbono → CO₂e (3.667)
DESCONTO_INCERTEZA = 0.20       # 20% desconto padrão Verra
BUFFER_VERRA    = 0.15          # 15% buffer de garantia
PROFUNDIDADE_CM = 30            # Profundidade padrão ISO 18400-104


@dataclass
class PontoColeta:
    """Representa uma amostra coletada pelo sensor NIR em campo."""
    ponto_id:      str
    latitude:      float
    longitude:     float
    soc_pct:       float   # % carbono orgânico no solo
    bulk_density:  float   # g/cm³ — densidade do solo
    umidade_pct:   float   # % umidade no momento da coleta
    zona:          str     # "lavoura", "reserva", "restauracao"


@dataclass
class ResultadoFazenda:
    """Resultado completo do cálculo VM0042 para uma fazenda."""
    fazenda_id:          str
    area_ha:             float
    n_amostras:          int
    soc_medio_pct:       float
    soc_stock_tc_ha:     float    # tC/ha
    co2e_ha:             float    # tCO₂e/ha
    delta_co2e_ha:       float    # tCO₂e/ha — variação entre anos
    creditos_brutos:     float    # tCO₂e total bruto
    creditos_certificados: float  # após -20% incerteza
    buffer_retido:       float    # créditos retidos pela Verra
    creditos_vendaveis:  float    # disponíveis para venda
    receita_usd:         float    # estimativa de receita
    desconto_incerteza:  float
    buffer_pct:          float


# ── PASSO 1: Estoque de carbono por ponto ────────────────────

def calcular_soc_stock(soc_pct: float,
                       bulk_density: float,
                       profundidade_cm: float = PROFUNDIDADE_CM) -> float:
    """
    Calcula o estoque de carbono orgânico no solo (SOC stock).

    Fórmula VM0042:
        SOC_stock (tC/ha) = SOC(%) × BD (g/cm³) × Prof (cm) × 0.1

    Args:
        soc_pct: % de carbono orgânico medido pelo sensor NIR
        bulk_density: densidade do solo em g/cm³
        profundidade_cm: profundidade de coleta em cm (padrão: 30cm)

    Returns:
        Estoque de carbono em toneladas C por hectare (tC/ha)
    """
    if soc_pct < 0 or soc_pct > 20:
        raise ValueError(f"SOC% inválido: {soc_pct}. Range esperado: 0–20%")
    if bulk_density < 0.5 or bulk_density > 2.5:
        raise ValueError(f"Bulk density inválida: {bulk_density}. Range: 0.5–2.5 g/cm³")

    return soc_pct * bulk_density * profundidade_cm * 0.1


# ── PASSO 2: Converter carbono em CO₂ equivalente ───────────

def converter_co2e(soc_stock_tc_ha: float) -> float:
    """
    Converte toneladas de carbono em CO₂ equivalente.

    Fórmula:
        CO₂e = tC/ha × (44/12) = tC/ha × 3.667

    Args:
        soc_stock_tc_ha: estoque de carbono em tC/ha

    Returns:
        Equivalente em tCO₂e/ha
    """
    return soc_stock_tc_ha * FATOR_C_CO2


# ── PASSO 3: Delta entre anos ────────────────────────────────

def calcular_delta(co2e_ano_atual: float,
                   co2e_ano_base: float) -> float:
    """
    Calcula a variação de CO₂e entre dois anos.
    O crédito é o carbono NOVO sequestrado — não o que já existia.

    Args:
        co2e_ano_atual: CO₂e medido no ano atual (tCO₂e/ha)
        co2e_ano_base: CO₂e medido no ano base (linha de base)

    Returns:
        Delta em tCO₂e/ha (positivo = sequestrou carbono)
    """
    delta = co2e_ano_atual - co2e_ano_base
    if delta < 0:
        print(f"⚠️  Delta negativo ({delta:.3f} tCO₂e/ha): solo perdeu carbono neste ciclo.")
    return delta


# ── PASSO 4: Escalar para a área total ───────────────────────

def escalar_area(delta_co2e_ha: float, area_ha: float) -> float:
    """
    Escala o delta por hectare para a área total da fazenda.

    Args:
        delta_co2e_ha: variação por hectare (tCO₂e/ha)
        area_ha: área total da fazenda em hectares

    Returns:
        Total de créditos brutos em tCO₂e
    """
    return delta_co2e_ha * area_ha


# ── PASSO 5: Aplicar descontos Verra ─────────────────────────

def aplicar_descontos(creditos_brutos: float,
                      desconto_incerteza: float = DESCONTO_INCERTEZA,
                      buffer_pct: float = BUFFER_VERRA):
    """
    Aplica os dois descontos obrigatórios da Verra:
    1. Desconto de incerteza (20%): compensa a margem de erro da medição
    2. Buffer de garantia (15%): retido pela Verra como seguro anti-reversão

    Args:
        creditos_brutos: total bruto em tCO₂e
        desconto_incerteza: percentual de desconto de incerteza (default 20%)
        buffer_pct: percentual do buffer Verra (default 15%)

    Returns:
        tuple: (certificados, buffer_retido, vendaveis)
    """
    certificados  = creditos_brutos * (1 - desconto_incerteza)
    buffer_retido = certificados * buffer_pct
    vendaveis     = certificados - buffer_retido

    return certificados, buffer_retido, vendaveis


# ── CÁLCULO COMPLETO POR FAZENDA ─────────────────────────────

def calcular_fazenda(fazenda_id: str,
                     pontos_ano_base: List[PontoColeta],
                     pontos_ano_atual: List[PontoColeta],
                     area_ha: float,
                     preco_usd_t: float = 15.0) -> ResultadoFazenda:
    """
    Executa o cálculo VM0042 completo para uma fazenda.

    Recebe as listas de pontos coletados no Ano 0 (linha de base)
    e no Ano 1+ (monitoramento) e calcula os créditos gerados.

    Args:
        fazenda_id: identificador único da fazenda
        pontos_ano_base: amostras NIR do Ano 0
        pontos_ano_atual: amostras NIR do Ano atual
        area_ha: área total da fazenda em hectares
        preco_usd_t: preço estimado por tCO₂e em USD

    Returns:
        ResultadoFazenda com todos os valores calculados
    """

    def media_soc_stock(pontos: List[PontoColeta]) -> tuple:
        """Calcula a média ponderada de SOC stock dos pontos."""
        stocks = [
            calcular_soc_stock(p.soc_pct, p.bulk_density)
            for p in pontos
        ]
        soc_medio = sum(p.soc_pct for p in pontos) / len(pontos)
        stock_medio = sum(stocks) / len(stocks)
        return soc_medio, stock_medio

    # Calcular para cada ano
    soc_medio_base,  stock_base  = media_soc_stock(pontos_ano_base)
    soc_medio_atual, stock_atual = media_soc_stock(pontos_ano_atual)

    # Converter para CO₂e
    co2e_base  = converter_co2e(stock_base)
    co2e_atual = converter_co2e(stock_atual)

    # Delta
    delta = calcular_delta(co2e_atual, co2e_base)

    # Escalar para área total
    brutos = escalar_area(delta, area_ha)

    # Aplicar descontos
    certificados, buffer, vendaveis = aplicar_descontos(brutos)

    # Receita estimada
    receita = vendaveis * preco_usd_t

    return ResultadoFazenda(
        fazenda_id=fazenda_id,
        area_ha=area_ha,
        n_amostras=len(pontos_ano_atual),
        soc_medio_pct=soc_medio_atual,
        soc_stock_tc_ha=stock_atual,
        co2e_ha=co2e_atual,
        delta_co2e_ha=delta,
        creditos_brutos=max(0, brutos),
        creditos_certificados=max(0, certificados),
        buffer_retido=max(0, buffer),
        creditos_vendaveis=max(0, vendaveis),
        receita_usd=max(0, receita),
        desconto_incerteza=DESCONTO_INCERTEZA,
        buffer_pct=BUFFER_VERRA,
    )


# ── MODO DE TESTE ─────────────────────────────────────────────

def gerar_pontos_teste(n: int, soc_base: float,
                       soc_variacao: float, zona: str) -> List[PontoColeta]:
    """Gera pontos de coleta simulados para teste."""
    import random
    random.seed(42)
    pontos = []
    for i in range(n):
        soc = soc_base + random.uniform(-soc_variacao, soc_variacao)
        pontos.append(PontoColeta(
            ponto_id=f"{zona}_{i+1:03d}",
            latitude=-17.80 + random.uniform(-0.05, 0.05),
            longitude=-50.93 + random.uniform(-0.05, 0.05),
            soc_pct=round(max(0.1, soc), 3),
            bulk_density=round(random.uniform(1.1, 1.5), 2),
            umidade_pct=round(random.uniform(15, 35), 1),
            zona=zona,
        ))
    return pontos


def imprimir_resultado(r: ResultadoFazenda):
    """Exibe o resultado de forma legível no terminal."""
    print("\n📐 CarbonChain — Resultado VM0042")
    print("=" * 48)
    print(f"\n🏡 Fazenda:          {r.fazenda_id}")
    print(f"   Área total:       {r.area_ha} ha")
    print(f"   Amostras:         {r.n_amostras} pontos NIR")
    print(f"\n🌱 SOC médio:        {r.soc_medio_pct:.3f}%")
    print(f"   Stock carbono:    {r.soc_stock_tc_ha:.3f} tC/ha")
    print(f"   CO₂e por ha:      {r.co2e_ha:.3f} tCO₂e/ha")
    print(f"   Delta (novo):     {r.delta_co2e_ha:.3f} tCO₂e/ha")
    print(f"\n📊 Créditos brutos:  {r.creditos_brutos:.1f} tCO₂e")
    print(f"   –{int(r.desconto_incerteza*100)}% incerteza:   –{r.creditos_brutos - r.creditos_certificados:.1f} tCO₂e")
    print(f"   Certificados:     {r.creditos_certificados:.1f} tCO₂e")
    print(f"   –{int(r.buffer_pct*100)}% buffer Verra: –{r.buffer_retido:.1f} tCO₂e")
    print(f"   ✅ Vendáveis:      {r.creditos_vendaveis:.1f} tCO₂e")
    print(f"\n💰 Receita estimada: US${r.receita_usd:,.0f}")
    print(f"   Produtor (80%):  US${r.receita_usd * 0.80:,.0f}")
    print(f"   CarbonChain(20%):US${r.receita_usd * 0.20:,.0f}")
    print("=" * 48)


if __name__ == "__main__":
    print("\n🧪 Teste VM0042 — Fazenda Rio Verde / GO")
    print("   Simulando Ano 0 (base) → Ano 1 (após plantio direto)\n")

    # Ano 0 — linha de base
    pontos_base = gerar_pontos_teste(
        n=120, soc_base=2.1, soc_variacao=0.3, zona="lavoura"
    )

    # Ano 1 — após adoção de cobertura de solo e rotação
    pontos_atual = gerar_pontos_teste(
        n=120, soc_base=2.4, soc_variacao=0.3, zona="lavoura"
    )

    resultado = calcular_fazenda(
        fazenda_id="fazenda_rio_verde_001",
        pontos_ano_base=pontos_base,
        pontos_ano_atual=pontos_atual,
        area_ha=600,       # 600ha de plantio direto (VM0042)
        preco_usd_t=15.0,
    )

    imprimir_resultado(resultado)

    # Salvar resultado em JSON
    import os
    os.makedirs("data/sample_farm", exist_ok=True)
    with open("data/sample_farm/resultado_vm0042.json", "w") as f:
        json.dump(asdict(resultado), f, indent=2, ensure_ascii=False)
    print(f"\n✓ Resultado salvo em: data/sample_farm/resultado_vm0042.json")