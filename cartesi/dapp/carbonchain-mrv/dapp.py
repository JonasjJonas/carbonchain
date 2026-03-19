"""
CarbonChain — dapp.py
MRV on-chain via Cartesi Rollup
Processa dados de fazenda e calcula créditos VM0042 de forma auditável
"""

from os import environ
import logging
import requests
import json
import hashlib

logging.basicConfig(level="INFO")
logger = logging.getLogger(__name__)

rollup_server = environ["ROLLUP_HTTP_SERVER_URL"]
logger.info(f"CarbonChain MRV dApp iniciado — rollup: {rollup_server}")


# ── CONSTANTES VM0042 ─────────────────────────────────────────
FATOR_C_CO2        = 44 / 12
DESCONTO_INCERTEZA = 0.20
BUFFER_VERRA       = 0.15
PROFUNDIDADE_CM    = 30


# ── CÁLCULO VM0042 (mesma lógica do mrv/vm0042.py) ───────────

def calcular_soc_stock(soc_pct, bulk_density, prof=PROFUNDIDADE_CM):
    return soc_pct * bulk_density * prof * 0.1

def converter_co2e(soc_stock):
    return soc_stock * FATOR_C_CO2

def calcular_creditos(pontos_base, pontos_atual, area_ha, preco_usd=15.0):
    """
    Executa o cálculo completo VM0042.
    Recebe listas de pontos de coleta NIR de dois anos e retorna os créditos.
    """
    def media_stock(pontos):
        stocks = [calcular_soc_stock(p["soc_pct"], p["bulk_density"]) for p in pontos]
        return sum(stocks) / len(stocks)

    stock_base  = media_stock(pontos_base)
    stock_atual = media_stock(pontos_atual)

    co2e_base  = converter_co2e(stock_base)
    co2e_atual = converter_co2e(stock_atual)
    delta      = co2e_atual - co2e_base

    brutos       = max(0, delta * area_ha)
    certificados = brutos * (1 - DESCONTO_INCERTEZA)
    buffer       = certificados * BUFFER_VERRA
    vendaveis    = certificados - buffer
    receita      = vendaveis * preco_usd

    return {
        "delta_co2e_ha":        round(delta, 4),
        "creditos_brutos":      round(brutos, 2),
        "creditos_certificados":round(certificados, 2),
        "buffer_retido":        round(buffer, 2),
        "creditos_vendaveis":   round(vendaveis, 2),
        "receita_usd":          round(receita, 2),
        "produtor_usd":         round(receita * 0.80, 2),
        "carbonchain_usd":      round(receita * 0.20, 2),
        "metodologia":          "Verra VM0042 v2.1",
        "desconto_incerteza":   DESCONTO_INCERTEZA,
        "buffer_pct":           BUFFER_VERRA,
    }


def gerar_hash(resultado, fazenda_id):
    """
    Gera o hash auditável do cálculo — essa é a prova on-chain.
    Qualquer um pode re-executar o cálculo e verificar que o hash bate.
    """
    payload = json.dumps({
        "fazenda_id": fazenda_id,
        "resultado":  resultado,
    }, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


# ── HANDLERS DO ROLLUP ────────────────────────────────────────

def handle_advance(data):
    """
    Processa uma nova solicitação de cálculo de créditos.

    Input esperado (hex decodificado):
    {
        "fazenda_id":    "fazenda_rio_verde_001",
        "area_ha":       600,
        "preco_usd_t":   15.0,
        "pontos_base":   [{"soc_pct": 2.1, "bulk_density": 1.3}, ...],
        "pontos_atual":  [{"soc_pct": 2.4, "bulk_density": 1.3}, ...]
    }
    """
    logger.info("CarbonChain — nova solicitação de cálculo MRV")

    try:
        # Decodifica o payload hex → JSON
        hex_data = data["payload"]
        payload  = json.loads(bytes.fromhex(hex_data[2:]).decode("utf-8"))

        fazenda_id    = payload["fazenda_id"]
        area_ha       = payload["area_ha"]
        preco_usd_t   = payload.get("preco_usd_t", 15.0)
        pontos_base   = payload["pontos_base"]
        pontos_atual  = payload["pontos_atual"]

        logger.info(f"Calculando créditos para: {fazenda_id} | {area_ha}ha")

        # Executa o cálculo VM0042
        resultado = calcular_creditos(
            pontos_base, pontos_atual, area_ha, preco_usd_t
        )

        # Gera o hash auditável
        resultado["fazenda_id"]  = fazenda_id
        resultado["area_ha"]     = area_ha
        resultado["hash_calculo"]= gerar_hash(resultado, fazenda_id)

        logger.info(f"Créditos vendáveis: {resultado['creditos_vendaveis']} tCO₂e")
        logger.info(f"Hash: {resultado['hash_calculo']}")

        # Emite o resultado como Notice na blockchain
        resultado_hex = "0x" + json.dumps(resultado).encode("utf-8").hex()
        requests.post(rollup_server + "/notice", json={"payload": resultado_hex})

        logger.info("✅ Cálculo concluído e gravado on-chain")
        return "accept"

    except Exception as e:
        logger.error(f"❌ Erro no cálculo: {e}")
        erro_hex = "0x" + str(e).encode("utf-8").hex()
        requests.post(rollup_server + "/report", json={"payload": erro_hex})
        return "reject"


def handle_inspect(data):
    """
    Responde consultas sobre o estado do dApp.
    Pode ser usado para verificar o último resultado calculado.
    """
    logger.info("CarbonChain — consulta de estado recebida")
    info = {
        "dapp":       "CarbonChain MRV",
        "versao":     "1.0.0",
        "metodologia":"Verra VM0042 v2.1",
        "status":     "operacional",
    }
    info_hex = "0x" + json.dumps(info).encode("utf-8").hex()
    requests.post(rollup_server + "/report", json={"payload": info_hex})
    return "accept"


# ── LOOP PRINCIPAL DO ROLLUP ──────────────────────────────────

handlers = {
    "advance_state": handle_advance,
    "inspect_state": handle_inspect,
}

finish = {"status": "accept"}

logger.info("CarbonChain MRV dApp — aguardando solicitações...")

while True:
    response = requests.post(rollup_server + "/finish", json=finish)
    if response.status_code == 202:
        pass  # sem solicitações pendentes
    else:
        rollup_request = response.json()
        finish["status"] = handlers[rollup_request["request_type"]](
            rollup_request["data"]
        )