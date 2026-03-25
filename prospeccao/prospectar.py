"""
prospeccao/prospectar.py
------------------------
Pipeline de pré-qualificação de fazendas para o CarbonChain.

Etapas:
  1. Resolve nome do município → código IBGE (via API IBGE)
  2. Busca imóveis rurais via WFS GeoServer do SICAR
  3. Filtra por área mínima (default: 200 ha)
  4. Consulta uso do solo via API MapBiomas (2022-2024)
  5. Calcula % agrícola e classifica por prioridade VM0047
  6. Exporta CSV rankeado

Uso:
    python3 prospectar.py --municipio "Itumbiara" --estado GO
    python3 prospectar.py --municipio "Rio Verde" --estado GO --area-min 500
    python3 prospectar.py --municipio "Sorriso" --estado MT --area-min 1000

Dependências:
    pip install requests pandas tqdm
"""

import argparse
import time
import sys
import requests
import pandas as pd
from tqdm import tqdm
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ─── Configurações padrão ────────────────────────────────────────────────────

AREA_MIN_DEFAULT = 200   # hectares

# WFS GeoServer SICAR
WFS_URL = "https://geoserver.car.gov.br/geoserver/sicar/ows"

# MapBiomas API
MB_URL   = "https://prd.plataforma.mapbiomas.org/api/v1/brazil/statistics/area"
MB_YEARS = ["2022", "2023", "2024"]

# IBGE API (busca município por nome + UF)
IBGE_URL = "https://servicodados.ibge.gov.br/api/v1/localidades/municipios"

# Classes agrícolas VM0047 (MapBiomas Collection 9)
# 20=Cana, 21=Mosaico agro/pasto, 39=Soja, 40=Arroz, 41=Lavoura temporária, 62=Algodão
AGRO_CLASSES = [20, 21, 39, 40, 41, 62]

ALL_CLASSES = [
    1, 3, 4, 5, 6, 9, 11, 12, 15, 18, 19, 20, 21, 22, 23, 24,
    25, 26, 27, 29, 30, 31, 32, 33, 35, 36, 39, 40, 41, 46, 47,
    48, 49, 50, 62, 75
]

# Siglas dos estados → sufixo do layer WFS
ESTADO_LAYER = {
    "AC": "sicar:sicar_imoveis_ac", "AL": "sicar:sicar_imoveis_al",
    "AM": "sicar:sicar_imoveis_am", "AP": "sicar:sicar_imoveis_ap",
    "BA": "sicar:sicar_imoveis_ba", "CE": "sicar:sicar_imoveis_ce",
    "DF": "sicar:sicar_imoveis_df", "ES": "sicar:sicar_imoveis_es",
    "GO": "sicar:sicar_imoveis_go", "MA": "sicar:sicar_imoveis_ma",
    "MG": "sicar:sicar_imoveis_mg", "MS": "sicar:sicar_imoveis_ms",
    "MT": "sicar:sicar_imoveis_mt", "PA": "sicar:sicar_imoveis_pa",
    "PB": "sicar:sicar_imoveis_pb", "PE": "sicar:sicar_imoveis_pe",
    "PI": "sicar:sicar_imoveis_pi", "PR": "sicar:sicar_imoveis_pr",
    "RJ": "sicar:sicar_imoveis_rj", "RN": "sicar:sicar_imoveis_rn",
    "RO": "sicar:sicar_imoveis_ro", "RR": "sicar:sicar_imoveis_rr",
    "RS": "sicar:sicar_imoveis_rs", "SC": "sicar:sicar_imoveis_sc",
    "SE": "sicar:sicar_imoveis_se", "SP": "sicar:sicar_imoveis_sp",
    "TO": "sicar:sicar_imoveis_to",
}


# ─── Sessão HTTP com retry ────────────────────────────────────────────────────

def criar_sessao():
    session = requests.Session()
    adapter = requests.adapters.HTTPAdapter(
        max_retries=requests.adapters.Retry(
            total=3, backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504]
        )
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

SESSION = criar_sessao()


# ─── Etapa 1: Resolver município → IBGE ──────────────────────────────────────

def resolver_municipio(nome: str, estado: str) -> tuple[str, str]:
    """
    Recebe nome do município e sigla do estado.
    Retorna (codigo_ibge, nome_oficial).
    Exemplo: resolver_municipio("itumbiara", "GO") → ("5211503", "Itumbiara")
    """
    estado = estado.upper().strip()
    nome_normalizado = nome.strip().lower()

    print(f"\n🔍 Buscando município '{nome}' no estado {estado}...")

    # Busca todos os municípios do estado na API IBGE
    url = f"https://servicodados.ibge.gov.br/api/v1/localidades/estados/{estado}/municipios"
    r = SESSION.get(url, timeout=30)
    r.raise_for_status()
    municipios = r.json()

    # Busca por correspondência exata (sem acento)
    import unicodedata
    def normalizar(s):
        return ''.join(
            c for c in unicodedata.normalize('NFD', s.lower())
            if unicodedata.category(c) != 'Mn'
        )

    nome_norm = normalizar(nome_normalizado)
    encontrados = [
        m for m in municipios
        if normalizar(m["nome"]) == nome_norm
    ]

    if not encontrados:
        # Busca parcial como fallback
        encontrados = [
            m for m in municipios
            if nome_norm in normalizar(m["nome"])
        ]

    if not encontrados:
        nomes = [m["nome"] for m in municipios[:10]]
        raise ValueError(
            f"Município '{nome}' não encontrado em {estado}.\n"
            f"Exemplos disponíveis: {nomes}"
        )

    if len(encontrados) > 1:
        opcoes = [f"  {m['id']} — {m['nome']}" for m in encontrados]
        raise ValueError(
            f"Múltiplos municípios encontrados para '{nome}' em {estado}:\n"
            + "\n".join(opcoes)
            + "\n\nUse --municipio com o nome exato."
        )

    m = encontrados[0]
    print(f"   ✅ Encontrado: {m['nome']} (IBGE: {m['id']})")
    return str(m["id"]), m["nome"]


# ─── Etapa 2: SICAR WFS ──────────────────────────────────────────────────────

def buscar_imoveis_sicar(cod_ibge: str, estado: str) -> pd.DataFrame:
    layer = ESTADO_LAYER.get(estado.upper())
    if not layer:
        raise ValueError(f"Estado '{estado}' não reconhecido. Use a sigla (ex: GO, MT, SP).")

    print(f"\n📡 Consultando SICAR — município IBGE {cod_ibge} | layer {layer}...")

    params = {
        "service":      "WFS",
        "version":      "2.0.0",
        "request":      "GetFeature",
        "typeName":     layer,
        "outputFormat": "application/json",
        "CQL_FILTER":   f"cod_municipio_ibge={cod_ibge}",
        "count":        "10000",
    }

    r = SESSION.get(WFS_URL, params=params, verify=False, timeout=120)
    r.raise_for_status()

    data = r.json()
    features = data.get("features", [])
    total = data.get("numberMatched", len(features))

    print(f"   Total de imóveis no município: {total}")

    if not features:
        raise ValueError("Nenhum imóvel encontrado. Verifique o código IBGE e o estado.")

    return pd.DataFrame([f["properties"] for f in features])


# ─── Etapa 3: Filtro por área ─────────────────────────────────────────────────

def filtrar_por_area(df: pd.DataFrame, area_min: float) -> pd.DataFrame:
    df["area"] = pd.to_numeric(df["area"], errors="coerce")
    candidatos = df[df["area"] >= area_min].copy()
    candidatos = candidatos.sort_values("area", ascending=False).reset_index(drop=True)
    print(f"   Candidatos com {area_min}+ ha: {len(candidatos)} de {len(df)}")
    return candidatos


# ─── Etapa 4: MapBiomas ───────────────────────────────────────────────────────

def consultar_mapbiomas(cod_imovel: str) -> dict:
    params = [
        ("propertyCode", cod_imovel),
        ("subthemeKey", "coverage_lclu"),
        ("legendKey", "default"),
        ("spatialMethod", "union"),
    ]
    for y in MB_YEARS:
        params.append(("year", y))
    for v in ALL_CLASSES:
        params.append(("pixelValue", v))

    try:
        r = SESSION.get(MB_URL, params=params, verify=False, timeout=60)
        r.raise_for_status()
        data = r.json()

        total_agro, anos = 0, 0
        for stat in data.get("statistic", []):
            agro = sum(
                item["value"]
                for item in stat.get("items", [])
                if item["pixelValue"] in AGRO_CLASSES
            )
            total_agro += agro
            anos += 1

        area_agro = round(total_agro / anos, 1) if anos > 0 else 0
        return {"cod_imovel": cod_imovel, "area_agro_media_ha": area_agro, "ok": True}

    except Exception as e:
        return {"cod_imovel": cod_imovel, "area_agro_media_ha": 0, "ok": False, "erro": str(e)}


def consultar_todos_mapbiomas(candidatos: pd.DataFrame, lote: int = 10) -> pd.DataFrame:
    print(f"\n🌿 Consultando MapBiomas para {len(candidatos)} fazendas...")
    resultados = []
    codigos = candidatos["cod_imovel"].tolist()

    for i in tqdm(range(0, len(codigos), lote), desc="   Progresso"):
        batch = codigos[i:i + lote]
        for cod in batch:
            resultados.append(consultar_mapbiomas(cod))
        time.sleep(0.3)

    return pd.DataFrame(resultados)


# ─── Etapa 5: Classificação de prioridade ────────────────────────────────────

def classificar_prioridade(pct: float) -> str:
    if pct > 130: return "DESCARTAR"
    if pct > 100: return "VERIFICAR"
    if pct >= 80: return "PRIORIDADE_1"
    if pct >= 60: return "PRIORIDADE_2"
    return "FORA_ESCOPO"


def montar_ranking(candidatos: pd.DataFrame, mb_df: pd.DataFrame) -> pd.DataFrame:
    merged = candidatos.merge(
        mb_df[["cod_imovel", "area_agro_media_ha", "ok"]],
        on="cod_imovel", how="left"
    )
    merged["pct_agro"] = (
        (merged["area_agro_media_ha"] / merged["area"]) * 100
    ).round(1).fillna(0)

    merged["prioridade"] = merged["pct_agro"].apply(classificar_prioridade)

    ordem = {"PRIORIDADE_1": 0, "PRIORIDADE_2": 1, "VERIFICAR": 2, "FORA_ESCOPO": 3, "DESCARTAR": 4}
    merged["_ordem"] = merged["prioridade"].map(ordem)
    merged = merged.sort_values(["_ordem", "pct_agro"], ascending=[True, False]).reset_index(drop=True)
    merged["rank"] = merged.index + 1
    return merged.drop(columns=["_ordem"])


# ─── Etapa 6: Export e resumo ─────────────────────────────────────────────────

COLUNAS_OUTPUT = [
    "rank", "prioridade", "cod_imovel", "area",
    "area_agro_media_ha", "pct_agro",
    "status_imovel", "condicao", "municipio", "uf"
]

def exportar_csv(df: pd.DataFrame, output: str):
    cols = [c for c in COLUNAS_OUTPUT if c in df.columns]
    df[cols].to_csv(output, sep=";", index=False, encoding="utf-8-sig")
    print(f"\n✅ Arquivo salvo: {output}")


def imprimir_resumo(df: pd.DataFrame, municipio_nome: str):
    contagem = df["prioridade"].value_counts()
    p1 = contagem.get("PRIORIDADE_1", 0)
    p2 = contagem.get("PRIORIDADE_2", 0)
    print(f"\n{'='*55}")
    print(f"  CarbonChain — Pré-qualificação VM0047")
    print(f"  Município: {municipio_nome} | Total: {len(df)} fazendas")
    print(f"{'='*55}")
    for p in ["PRIORIDADE_1", "PRIORIDADE_2", "VERIFICAR", "FORA_ESCOPO", "DESCARTAR"]:
        n = contagem.get(p, 0)
        bar = "█" * (n // 5)
        print(f"  {p:<14} {str(n).rjust(4)}  {bar}")
    print(f"{'='*55}")
    print(f"  Lista limpa (P1+P2): {p1 + p2} fazendas")
    print(f"{'='*55}\n")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CarbonChain — pipeline de prospecção VM0047",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 prospectar.py --municipio "Itumbiara" --estado GO
  python3 prospectar.py --municipio "Rio Verde" --estado GO --area-min 500
  python3 prospectar.py --municipio "Sorriso" --estado MT --area-min 1000 --output sorriso.csv
        """
    )
    parser.add_argument("--municipio", required=True, help="Nome do município (ex: 'Itumbiara')")
    parser.add_argument("--estado",    required=True, help="Sigla do estado (ex: GO, MT, SP)")
    parser.add_argument("--area-min",  default=AREA_MIN_DEFAULT, type=float, help="Área mínima em hectares (default: 200)")
    parser.add_argument("--output",    default=None, help="Nome do arquivo CSV de saída (default: {municipio}_vm0047.csv)")
    args = parser.parse_args()

    estado = args.estado.upper()
    output = args.output or f"{args.municipio.lower().replace(' ', '_')}_{estado.lower()}_vm0047.csv"

    try:
        # 1. Resolver município → IBGE
        cod_ibge, nome_oficial = resolver_municipio(args.municipio, estado)

        # 2. SICAR
        df_sicar = buscar_imoveis_sicar(cod_ibge, estado)

        # 3. Filtro área
        candidatos = filtrar_por_area(df_sicar, args.area_min)
        if candidatos.empty:
            print(f"\n⚠️  Nenhuma fazenda com {args.area_min}+ ha encontrada em {nome_oficial}.")
            sys.exit(0)

        # 4. MapBiomas
        df_mb = consultar_todos_mapbiomas(candidatos)

        # 5. Ranking
        ranking = montar_ranking(candidatos, df_mb)

        # 6. Export
        exportar_csv(ranking, output)
        imprimir_resumo(ranking, nome_oficial)

    except KeyboardInterrupt:
        print("\n\n⚠️  Interrompido pelo usuário.")
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Erro: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
