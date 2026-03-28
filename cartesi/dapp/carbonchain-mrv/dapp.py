"""
CarbonChain — dapp.py  v2.0
=============================
MRV on-chain via Cartesi Rollup.

Executa o pipeline MRV completo dentro de uma máquina Linux
determinística (RISC-V) verificável. O resultado é gravado
on-chain com hash SHA-256 — qualquer auditor pode re-executar
e confirmar que o hash bate.

Inputs aceitos (advance):
  1. "calcular_mrv"  — JSON com dados de fazenda → calcula créditos
  2. "registrar_cpa" — registra nova fazenda no PoA

Outputs:
  Notice  → resultado completo (VCUs por ativo, receitas, hash)
  Voucher → instrução de mint para CCTFactory.sol

Metodologias implementadas:
  CCT-SOIL — VM0042 v2.2 (solo agrícola)
  CCT-REDD — VM0015     (Reserva Legal / REDD+)
  CCT-ARR  — VM0047     (restauração / reflorestamento)
"""

from os import environ
import logging
import requests
import json
import hashlib
import math
from datetime import datetime

logging.basicConfig(level="INFO")
logger = logging.getLogger(__name__)

rollup_server = environ.get("ROLLUP_HTTP_SERVER_URL", "http://localhost:5004")
logger.info(f"CarbonChain MRV dApp v2.0 — rollup: {rollup_server}")


# ── CONSTANTES (espelho do mrv_calculator.py) ─────────────────────────────────

C_TO_CO2            = 44 / 12       # 3.6667
GWP_N2O             = 273
EF_N2O_DIRECT       = 0.01
EF_N2O_INDIRECT     = 0.0075
DESCONTO_INCERTEZA  = 0.20
BUFFER_PERMANENCIA  = 0.15
FATOR_LEAKAGE_SOIL  = 0.05
FATOR_LEAKAGE_REDD  = 0.10
TAXA_DESMAT_CERRADO = 0.0058        # 0.58%/ano PRODES/INPE sul de GO
CARBONO_TOTAL_CERR  = 70.0          # tC/ha Cerrado (acima + abaixo do solo)
BD_PADRAO           = 1.20          # g/cm³ Latossolo
PROF_CM             = 30            # cm

PRECOS = {"SOIL": 9, "REDD": 54, "ARR": 76}

# Estado interno — persiste entre chamadas no mesmo rollup epoch
_estado = {
    "cpas_registrados": [],
    "calculos_realizados": 0,
    "ultimo_calculo": None,
}


# ── FÓRMULAS MRV ─────────────────────────────────────────────────────────────

def calcular_delta_soc(soc_t0: float, soc_t1: float,
                       area_ha: float, bd: float = BD_PADRAO) -> float:
    """
    ΔC_SOC = (SOC_t1 - SOC_t0) × BD × D × 100 × C_to_CO2 × area
    Resultado em tCO₂e total.
    """
    delta_frac  = (soc_t1 - soc_t0) / 100
    delta_c_ha  = delta_frac * bd * PROF_CM * 100   # tC/ha
    return delta_c_ha * C_TO_CO2 * area_ha


def calcular_n2o(area_ha: float, fert_n_kg_ha: float = 120.0,
                 reducao_pct: float = 0.15) -> float:
    """Redução N₂O por diminuição de fertilizante nitrogenado."""
    reducao_n  = fert_n_kg_ha * reducao_pct
    ef_total   = EF_N2O_DIRECT + EF_N2O_INDIRECT
    n2o_kg_ha  = reducao_n * ef_total * (44 / 28)
    return n2o_kg_ha * GWP_N2O / 1000 * area_ha


def calcular_redd(area_ha: float) -> float:
    """
    VM0015: emissões evitadas por preservação da Reserva Legal.
    REDD = área × taxa_desmat × carbono_total × C_to_CO2 × (1 - leakage)
    """
    return (area_ha * TAXA_DESMAT_CERRADO
            * CARBONO_TOTAL_CERR * C_TO_CO2
            * (1 - FATOR_LEAKAGE_REDD))


def aplicar_descontos(bruto: float) -> tuple:
    """Aplica incerteza 20% + buffer 15%. Retorna (após_inc, após_buf, vcus)."""
    apos_inc = bruto * (1 - DESCONTO_INCERTEZA)
    apos_buf = apos_inc * (1 - BUFFER_PERMANENCIA)
    vcus     = math.floor(apos_buf)
    return round(apos_inc, 2), round(apos_buf, 2), float(vcus)


def calcular_ativo(tipo: str, area_ha: float,
                   soc_t0: float = 1.800, soc_t1: float = 1.811,
                   bd: float = BD_PADRAO) -> dict:
    """Calcula créditos para um ativo. Retorna dict pronto para o Notice."""
    if tipo == "REDD":
        bruto_bruto = calcular_redd(area_ha) / (1 - FATOR_LEAKAGE_REDD)
        leakage     = bruto_bruto * FATOR_LEAKAGE_REDD
        bruto       = bruto_bruto - leakage
    else:
        delta_soc   = calcular_delta_soc(soc_t0, soc_t1, area_ha, bd)
        n2o         = calcular_n2o(area_ha) if tipo == "SOIL" else 0.0
        bruto_pre   = delta_soc + n2o
        leakage     = bruto_pre * FATOR_LEAKAGE_SOIL
        bruto       = max(0.0, bruto_pre - leakage)

    apos_inc, apos_buf, vcus = aplicar_descontos(bruto)
    preco    = PRECOS.get(tipo, 9)
    receita  = vcus * preco

    return {
        "tipo":            f"CCT-{tipo}",
        "metodologia":     {"SOIL": "VM0042 v2.2",
                            "REDD": "VM0015",
                            "ARR":  "VM0047"}[tipo],
        "area_ha":         round(area_ha, 1),
        "bruto_tco2e":     round(bruto, 2),
        "apos_incerteza":  apos_inc,
        "apos_buffer":     apos_buf,
        "vcus":            vcus,
        "preco_usd":       preco,
        "receita_usd":     round(receita, 2),
        "produtor_usd":    round(receita * 0.80, 2),
        "cc_usd":          round(receita * 0.20, 2),
    }


# ── PIPELINE PRINCIPAL ────────────────────────────────────────────────────────

def executar_mrv(payload: dict) -> dict:
    """
    Executa o cálculo MRV completo para uma fazenda.

    Input esperado:
    {
        "acao":       "calcular_mrv",
        "cpa_id":     "CPA-GO-001",
        "fazenda":    "Fazenda Piloto — Itumbiara, GO",
        "area_ha":    800,
        "periodo":    "2024-ciclo-1",
        "soc_t0":     1.800,
        "soc_t1":     1.811,
        "bd":         1.20,       (opcional)
        "areas": {                (opcional — distribuição das zonas)
            "solo_ha":   528,
            "reserva_ha": 267,
            "arr_ha":    40
        }
    }
    """
    cpa_id   = payload["cpa_id"]
    fazenda  = payload.get("fazenda", cpa_id)
    area_ha  = float(payload["area_ha"])
    soc_t0   = float(payload.get("soc_t0", 1.800))
    soc_t1   = float(payload.get("soc_t1", 1.811))
    bd       = float(payload.get("bd", BD_PADRAO))
    periodo  = payload.get("periodo", datetime.now().strftime("%Y-ciclo-1"))

    # Distribuição de áreas (pode vir do satellite.py ou usar padrão)
    areas    = payload.get("areas", {})
    solo_ha  = float(areas.get("solo_ha",    area_ha * 0.75))
    redd_ha  = float(areas.get("reserva_ha", area_ha * 0.20))
    arr_ha   = float(areas.get("arr_ha",     area_ha * 0.05))

    logger.info(f"Calculando MRV: {cpa_id} | {area_ha}ha | SOC {soc_t0}→{soc_t1}")

    # Calcula os 3 ativos
    soil = calcular_ativo("SOIL", solo_ha, soc_t0, soc_t1, bd)
    redd = calcular_ativo("REDD", redd_ha, soc_t0, soc_t1, bd)
    arr  = calcular_ativo("ARR",  arr_ha,
                          soc_t0 * 0.90,
                          soc_t0 * 0.90 + 0.014, bd)

    # Totais
    total_vcus    = soil["vcus"] + redd["vcus"] + arr["vcus"]
    total_receita = soil["receita_usd"] + redd["receita_usd"] + arr["receita_usd"]
    levy_verra    = round(total_vcus * 0.23, 2)

    resultado = {
        "cpa_id":          cpa_id,
        "fazenda":         fazenda,
        "area_ha":         area_ha,
        "periodo":         periodo,
        "soc_t0":          soc_t0,
        "soc_t1":          soc_t1,
        "ativos":          [soil, redd, arr],
        "total_vcus":      total_vcus,
        "total_receita_usd": round(total_receita, 2),
        "levy_verra_usd":  levy_verra,
        "cc_liquido_usd":  round(total_receita * 0.20 - levy_verra, 2),
        "timestamp":       datetime.now().isoformat(),
        "versao_dapp":     "2.0.0",
    }

    # Hash auditável — núcleo do diferencial Cartesi
    # Qualquer um pode re-executar este código com os mesmos inputs
    # e verificar que o hash é idêntico
    hash_payload = json.dumps({
        "cpa_id":  cpa_id,
        "soc_t0":  soc_t0,
        "soc_t1":  soc_t1,
        "area_ha": area_ha,
        "areas":   {"solo_ha": solo_ha, "reserva_ha": redd_ha, "arr_ha": arr_ha},
        "total_vcus": total_vcus,
    }, sort_keys=True)
    resultado["hash_mrv"] = hashlib.sha256(hash_payload.encode()).hexdigest()

    logger.info(f"✅ MRV concluído: {total_vcus} VCUs | USD {total_receita:.0f}")
    logger.info(f"   Hash: {resultado['hash_mrv'][:16]}...")

    # Atualiza estado interno
    _estado["calculos_realizados"] += 1
    _estado["ultimo_calculo"] = resultado

    return resultado


def montar_voucher_mint(resultado: dict) -> dict:
    """
    Monta o Voucher Cartesi para o CCTFactory.sol.
    O Voucher instrui o contrato a minar os tokens após aprovação.

    Estrutura do payload do Voucher (ABI-encoded para CCTFactory.sol):
      mintFromVoucher(cpa_id, vcus_soil, vcus_redd, vcus_arr, hash_mrv)
    """
    ativos = {a["tipo"]: a for a in resultado["ativos"]}

    # Endereço do CCTFactory (a ser preenchido após deploy em mainnet)
    CCT_FACTORY_ADDR = "0xfA4150eFd8a152a48B9332F68EA2589933FcBA1B"

    # ABI encode simplificado — versão completa usa eth_abi
    mint_data = {
        "function":  "mintFromVoucher",
        "cpa_id":    resultado["cpa_id"],
        "hash_mrv":  resultado["hash_mrv"],
        "vcus": {
            "CCT-SOIL": int(ativos.get("CCT-SOIL", {}).get("vcus", 0)),
            "CCT-REDD": int(ativos.get("CCT-REDD", {}).get("vcus", 0)),
            "CCT-ARR":  int(ativos.get("CCT-ARR",  {}).get("vcus", 0)),
        },
        "periodo":   resultado["periodo"],
    }

    return {
        "destination": CCT_FACTORY_ADDR,
        "payload":     "0x" + json.dumps(mint_data).encode("utf-8").hex(),
    }


# ── HANDLERS CARTESI ──────────────────────────────────────────────────────────

def handle_advance(data):
    """
    Processa uma nova transação enviada ao rollup.
    Decodifica o payload hex → JSON → executa a ação.
    """
    logger.info("── Advance recebido ──")
    try:
        payload_hex = data["payload"]
        payload_str = bytes.fromhex(payload_hex[2:]).decode("utf-8")
        payload     = json.loads(payload_str)
        acao        = payload.get("acao", "calcular_mrv")

        if acao == "calcular_mrv":
            resultado = executar_mrv(payload)

            # Notice: resultado completo gravado on-chain
            notice_hex = "0x" + json.dumps(resultado).encode("utf-8").hex()
            requests.post(rollup_server + "/notice",
                          json={"payload": notice_hex})

            # Voucher: instrução de mint para o smart contract
            voucher = montar_voucher_mint(resultado)
            requests.post(rollup_server + "/voucher",
                          json=voucher)

            logger.info(f"Notice + Voucher emitidos para {resultado['cpa_id']}")
            return "accept"

        elif acao == "registrar_cpa":
            cpa = {
                "cpa_id":    payload["cpa_id"],
                "fazenda":   payload.get("fazenda", ""),
                "area_ha":   payload.get("area_ha", 0),
                "municipio": payload.get("municipio", ""),
                "registrado_em": datetime.now().isoformat(),
            }
            _estado["cpas_registrados"].append(cpa)

            notice_hex = "0x" + json.dumps({
                "acao": "cpa_registrado", **cpa
            }).encode("utf-8").hex()
            requests.post(rollup_server + "/notice",
                          json={"payload": notice_hex})

            logger.info(f"CPA registrado: {cpa['cpa_id']}")
            return "accept"

        else:
            raise ValueError(f"Ação desconhecida: {acao}")

    except Exception as e:
        logger.error(f"Erro no advance: {e}")
        erro_hex = "0x" + json.dumps({
            "erro": str(e), "timestamp": datetime.now().isoformat()
        }).encode("utf-8").hex()
        requests.post(rollup_server + "/report",
                      json={"payload": erro_hex})
        return "reject"


def handle_inspect(data):
    """
    Responde consultas de leitura — não altera o estado.
    Usado para verificar o último resultado ou listar CPAs.
    """
    logger.info("── Inspect recebido ──")
    try:
        payload_hex = data["payload"]
        query_str   = bytes.fromhex(payload_hex[2:]).decode("utf-8")
        query       = json.loads(query_str) if query_str.startswith("{") else {"q": query_str}
        tipo        = query.get("q", "status")

        if tipo == "ultimo_calculo":
            resp = _estado["ultimo_calculo"] or {"msg": "nenhum cálculo realizado"}
        elif tipo == "cpas":
            resp = {"cpas": _estado["cpas_registrados"]}
        else:
            resp = {
                "dapp":                "CarbonChain MRV",
                "versao":              "2.0.0",
                "metodologias":        ["VM0042 v2.2", "VM0015", "VM0047"],
                "calculos_realizados": _estado["calculos_realizados"],
                "cpas_registrados":    len(_estado["cpas_registrados"]),
                "status":              "operacional",
            }

        report_hex = "0x" + json.dumps(resp).encode("utf-8").hex()
        requests.post(rollup_server + "/report",
                      json={"payload": report_hex})
        return "accept"

    except Exception as e:
        logger.error(f"Erro no inspect: {e}")
        return "reject"


# ── LOOP PRINCIPAL CARTESI ────────────────────────────────────────────────────

handlers = {"advance_state": handle_advance, "inspect_state": handle_inspect}

finish = {"status": "accept"}
while True:
    logger.info("Aguardando próximo input...")
    response = requests.post(rollup_server + "/finish", json=finish)

    if response.status_code == 202:
        logger.info("Sem inputs pendentes — aguardando")
        continue

    rollup_request = response.json()
    req_type       = rollup_request["request_type"]
    handler        = handlers.get(req_type)

    if handler:
        finish["status"] = handler(rollup_request["data"])
    else:
        logger.warning(f"Tipo de request desconhecido: {req_type}")
        finish["status"] = "reject"
