"""
prospeccao/pipeline.py
-----------------------
Integração entre prospectar.py e mrv/satellite.py.

Fluxo:
  1. Busca fazendas via SICAR + MapBiomas (prospectar.py)
  2. Filtra por prioridade e tamanho mínimo
  3. Para cada fazenda qualificada, extrai o bbox da geometria WFS
  4. Alimenta o satellite.py com os dados de cada fazenda
  5. Salva os resultados de MRV em data/{cpa_id}/resultado_sat.json

Uso:
    python3 prospeccao/pipeline.py --municipio "Itumbiara" --estado GO
    python3 prospeccao/pipeline.py --municipio "Itumbiara" --estado GO --top 10
    python3 prospeccao/pipeline.py --municipio "Itumbiara" --estado GO --api

Dependências:
    pip install requests pandas tqdm numpy matplotlib scipy
"""

import argparse
import sys
import json
import time
from pathlib import Path
import numpy as np

# Garante que mrv/ está no path independente de onde o script é chamado
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mrv.satellite import analisar_fazenda, rodar_teste_local, buscar_sentinel2_api, FAZENDAS

# Importa funções do prospectar.py
sys.path.insert(0, str(ROOT / "prospeccao"))
from prospectar import (
    resolver_municipio,
    buscar_imoveis_sicar,
    filtrar_por_area,
    consultar_todos_mapbiomas,
    montar_ranking,
    get_json,
    WFS_URL,
    ESTADO_LAYER,
)

import pandas as pd
import urllib3
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


# ── EXTRAÇÃO DE BBOX E GEOMETRIA DO WFS ──────────────────────────────────────

def buscar_geometrias_sicar(cod_ibge: str, estado: str) -> dict:
    """
    Busca os imóveis do SICAR incluindo geometria (MultiPolygon).
    Retorna dict: cod_imovel → {bbox, area_ha, geometria}
    """
    layer = ESTADO_LAYER.get(estado.upper())
    print(f"\n📡 Buscando geometrias SICAR — município {cod_ibge}...")

    params = {
        "service":      "WFS",
        "version":      "2.0.0",
        "request":      "GetFeature",
        "typeName":     layer,
        "outputFormat": "application/json",
        "CQL_FILTER":   f"cod_municipio_ibge={cod_ibge}",
        "count":        "10000",
    }

    data = get_json(WFS_URL, params=params)
    features = data.get("features", [])
    print(f"   Geometrias recebidas: {len(features)}")

    geometrias = {}
    for f in features:
        props = f.get("properties", {})
        geom  = f.get("geometry", {})
        cod   = props.get("cod_imovel", "")

        if not cod or not geom:
            continue

        # Calcular bbox a partir das coordenadas do MultiPolygon
        bbox = extrair_bbox(geom)
        if bbox is None:
            continue

        geometrias[cod] = {
            "bbox":       bbox,
            "geojson":    geom,   # geometria GeoJSON completa para máscara de polígono
            "area_ha":    float(props.get("area", 0)),
            "municipio":  props.get("municipio", ""),
            "uf":         props.get("uf", estado),
            "status":     props.get("status_imovel", ""),
        }

    return geometrias


def extrair_bbox(geom: dict) -> list | None:
    """
    Extrai [lon_min, lat_min, lon_max, lat_max] de uma geometria GeoJSON.
    Suporta Polygon e MultiPolygon.
    """
    try:
        tipo = geom.get("type", "")
        coords = geom.get("coordinates", [])

        all_lons, all_lats = [], []

        if tipo == "Polygon":
            for ring in coords:
                for pt in ring:
                    all_lons.append(pt[0])
                    all_lats.append(pt[1])

        elif tipo == "MultiPolygon":
            for poly in coords:
                for ring in poly:
                    for pt in ring:
                        all_lons.append(pt[0])
                        all_lats.append(pt[1])
        else:
            return None

        if not all_lons:
            return None

        return [
            round(min(all_lons), 6),
            round(min(all_lats), 6),
            round(max(all_lons), 6),
            round(max(all_lats), 6),
        ]

    except Exception:
        return None


# ── PREPARAR FAZENDA_INFO PARA satellite.py ───────────────────────────────────

def montar_fazenda_info(cod_imovel: str, geo: dict, rank: int) -> dict:
    """
    Monta o dict fazenda_info esperado pelo satellite.py:
      nome, municipio, bbox, area_ha, cpa_id
    """
    # CPA ID usa o rank para facilitar identificação
    cpa_id = f"CPA-{geo['uf']}-{rank:03d}"

    return {
        "nome":      f"Fazenda #{rank} — {geo['municipio']}, {geo['uf']}",
        "municipio": geo["municipio"],
        "bbox":      geo["bbox"],
        "area_ha":   geo["area_ha"],
        "cpa_id":    cpa_id,
        "cod_imovel": cod_imovel,   # referência ao CAR original
    }


# ── PIPELINE PRINCIPAL ────────────────────────────────────────────────────────

def rodar_pipeline(
    municipio: str,
    estado: str,
    area_min: float = 200,
    top_n: int = 10,
    usar_api: bool = False,
    output_dir: Path = None,
    csv_cache: Path = None,   # se fornecido, pula etapas 1-4 e usa CSV existente
    periodo: str = "recente", # "recente" | "seco" (junho-agosto, ideal para Cerrado)
):
    estado = estado.upper()
    output_dir = output_dir or ROOT / "data" / "prospeccao"
    output_dir.mkdir(parents=True, exist_ok=True)

    print(f"\n{'='*60}")
    print(f"  CarbonChain — Pipeline Prospecção → MRV Satélite")
    print(f"  Município: {municipio} | Estado: {estado}")
    print(f"  Área mínima: {area_min} ha | Top N: {top_n}")
    print(f"{'='*60}")

    # ── Etapa 1: Resolver município ──────────────────────────────────────────
    cod_ibge, nome_oficial = resolver_municipio(municipio, estado)

    # ── Etapa 2-4: Prospecção (ou carregar cache) ────────────────────────────
    if csv_cache and Path(csv_cache).exists():
        print(f"\n⚡ Cache encontrado — pulando prospecção SICAR + MapBiomas")
        print(f"   Carregando: {csv_cache}")
        ranking = pd.read_csv(csv_cache, sep=";", encoding="utf-8-sig")
        print(f"   {len(ranking)} fazendas carregadas do cache")
    else:
        # Prospecção completa
        df_sicar = buscar_imoveis_sicar(cod_ibge, estado)
        candidatos = filtrar_por_area(df_sicar, area_min)

        if candidatos.empty:
            print(f"\n⚠️  Nenhuma fazenda com {area_min}+ ha encontrada.")
            return

        df_mb = consultar_todos_mapbiomas(candidatos)
        ranking = montar_ranking(candidatos, df_mb)

        # Salva cache automaticamente para próximas rodadas
        cache_path = output_dir / f"{municipio.lower().replace(' ', '_')}_{estado.lower()}_vm0047.csv"
        ranking.to_csv(cache_path, sep=";", index=False, encoding="utf-8-sig")
        print(f"\n💾 Cache salvo em: {cache_path}")
    p1 = ranking[ranking["prioridade"] == "PRIORIDADE_1"]
    selecionadas = p1.head(top_n)

    print(f"\n🎯 Fazendas selecionadas para MRV satélite:")
    print(f"   PRIORIDADE_1 disponíveis: {len(p1)}")
    print(f"   Enviando para satellite.py: {len(selecionadas)}")

    if selecionadas.empty:
        print("⚠️  Nenhuma fazenda PRIORIDADE_1 encontrada.")
        return

    # ── Etapa 5: Buscar geometrias ────────────────────────────────────────────
    geometrias = buscar_geometrias_sicar(cod_ibge, estado)
    # geometrias inclui 'bbox' e 'geojson' do WFS para máscara de polígono

    # ── Etapa 6: Rodar satellite.py para cada fazenda ─────────────────────────
    resultados_mrv = []
    erros = []

    print(f"\n🛰️  Iniciando análise satélite...\n")

    for rank, (_, row) in enumerate(selecionadas.iterrows(), start=1):
        cod = row["cod_imovel"]
        geo = geometrias.get(cod)

        if geo is None:
            print(f"  ⚠️  [{rank}/{len(selecionadas)}] {cod[:30]}... — geometria não encontrada, pulando")
            erros.append({"cod_imovel": cod, "erro": "geometria_nao_encontrada"})
            continue

        fazenda_info = montar_fazenda_info(cod, geo, rank)
        print(f"  [{rank}/{len(selecionadas)}] {fazenda_info['nome']}")
        print(f"   CAR: {cod}")
        print(f"   BBox: {geo['bbox']}")
        print(f"   Área: {geo['area_ha']:.0f} ha")

        try:
            # Redireciona DATA_DIR do satellite.py para a pasta desta fazenda
            import mrv.satellite as sat_module
            farm_dir = output_dir / fazenda_info["cpa_id"]
            farm_dir.mkdir(parents=True, exist_ok=True)
            sat_module.DATA_DIR = farm_dir

            if usar_api:
                b4, b8, b11, b12, cloud, _, data_img = buscar_sentinel2_api(
                    fazenda_key=None, data_inicio=None, data_fim=None,
                    fazenda_override=fazenda_info, periodo=periodo,
                )
                geom = geo.get("geojson")
                resultado = analisar_fazenda(
                    b4, b8, b11, b12, fazenda_info,
                    cloud_mask=cloud, data_imagem=data_img,
                    geometria=geom
                )
            else:
                b4, b8, b11, b12, _ = rodar_teste_local_com_info(fazenda_info)
                geom = geo.get("geojson")
                resultado = analisar_fazenda(b4, b8, b11, b12, fazenda_info, geometria=geom)

            # O satellite.py já salva o JSON com nome resultado_sat_{cpa_id}.json
            # Apenas referencia o path correto para o resumo
            json_path = farm_dir / f"resultado_sat_{fazenda_info['cpa_id']}.json"

            resultados_mrv.append({
                "rank":       rank,
                "cpa_id":     fazenda_info["cpa_id"],
                "cod_imovel": cod,
                "fazenda":    fazenda_info["nome"],
                "area_ha":    geo["area_ha"],
                "pct_agro":   float(row.get("pct_agro", 0)),
                "ndvi_medio": resultado["indices"]["ndvi_medio"],
                "soc_proxy":  resultado["indices"]["soc_proxy"],
                "solo_ha":    resultado["elegibilidade"]["solo_agricola_ha"],
                "reserva_ha": resultado["elegibilidade"]["reserva_ha"],
                "n_pontos_nir": resultado["amostragem"]["n_pontos"],
                "json_path":  str(json_path),
            })

            # Mover arquivos de data/sample_farm/ para a pasta correta da fazenda
            # satellite.py salva internamente em DATA_DIR antes de retornar
            import shutil
            sample_dir = ROOT / "data" / "sample_farm"
            cpa_id_str = fazenda_info["cpa_id"]
            for ext in [".png", ".json"]:
                padrao = f"*{cpa_id_str}*{ext}"
                for arq in sample_dir.glob(padrao):
                    destino = farm_dir / arq.name
                    shutil.move(str(arq), str(destino))

            print(f"   ✅ NDVI: {resultado['indices']['ndvi_medio']:.3f} | SOC proxy: {resultado['indices']['soc_proxy']:.3f}\n")
            time.sleep(0.5)  # pausa entre fazendas

        except Exception as e:
            print(f"   ❌ Erro: {e}\n")
            erros.append({"cod_imovel": cod, "erro": str(e)})

    # ── Resumo final ──────────────────────────────────────────────────────────
    if resultados_mrv:
        resumo_path = output_dir / f"{municipio.lower().replace(' ', '_')}_{estado.lower()}_mrv_resumo.json"
        with open(resumo_path, "w", encoding="utf-8") as f:
            json.dump({
                "municipio":   nome_oficial,
                "estado":      estado,
                "gerado_em":   pd.Timestamp.now().isoformat(),
                "total_analisadas": len(resultados_mrv),
                "erros":       len(erros),
                "fazendas":    resultados_mrv,
            }, f, ensure_ascii=False, indent=2)

        print(f"\n{'='*60}")
        print(f"  Pipeline concluído")
        print(f"  Fazendas analisadas: {len(resultados_mrv)}")
        print(f"  Erros:               {len(erros)}")
        print(f"  Resumo MRV:          {resumo_path}")
        print(f"{'='*60}\n")

        # Tabela resumo no terminal
        df_res = pd.DataFrame(resultados_mrv)
        cols = ["rank", "cpa_id", "area_ha", "pct_agro", "ndvi_medio", "soc_proxy", "solo_ha", "n_pontos_nir"]
        print(df_res[cols].to_string(index=False))

    else:
        print("\n❌ Nenhuma fazenda foi analisada com sucesso.")


# ── TESTE LOCAL COM BBOX REAL ─────────────────────────────────────────────────

def rodar_teste_local_com_info(fazenda_info: dict):
    """
    Wrapper sobre rodar_teste_local do satellite.py.
    Usa o area_ha real da fazenda, mantém dados sintéticos.
    Permite testar o pipeline completo sem credenciais Copernicus.
    """
    from mrv.satellite import rodar_teste_local

    # Cria uma entrada temporária no dict FAZENDAS com o bbox real
    FAZENDAS["_pipeline_tmp"] = fazenda_info
    b4, b8, b11, b12, fazenda = rodar_teste_local("_pipeline_tmp")
    del FAZENDAS["_pipeline_tmp"]
    return b4, b8, b11, b12, fazenda


# ── MAIN ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="CarbonChain — Pipeline Prospecção → MRV Satélite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Exemplos:
  python3 prospeccao/pipeline.py --municipio "Itumbiara" --estado GO
  python3 prospeccao/pipeline.py --municipio "Itumbiara" --estado GO --top 5
  python3 prospeccao/pipeline.py --municipio "Rio Verde" --estado GO --area-min 500 --top 20
  python3 prospeccao/pipeline.py --municipio "Itumbiara" --estado GO --api
        """
    )
    parser.add_argument("--municipio", required=True, help="Nome do município")
    parser.add_argument("--estado",    required=True, help="Sigla do estado (ex: GO)")
    parser.add_argument("--area-min",  default=200, type=float, help="Área mínima em ha (default: 200)")
    parser.add_argument("--top",       default=10,  type=int,   help="Quantas fazendas PRIORIDADE_1 analisar (default: 10)")
    parser.add_argument("--api",       action="store_true",     help="Usar API Copernicus real (requer .env)")
    parser.add_argument("--csv",       default=None,            help="CSV de prospecção já gerado — pula SICAR + MapBiomas")
    parser.add_argument("--periodo",   default="recente",       choices=["recente", "seco"], help="Período das imagens: recente (últimos 30 dias) ou seco (jun-ago, melhor para Cerrado)")
    parser.add_argument("--output",    default=None,            help="Pasta de output (default: data/prospeccao/)")
    args = parser.parse_args()

    output_dir = Path(args.output) if args.output else None

    rodar_pipeline(
        municipio=args.municipio,
        estado=args.estado,
        area_min=args.area_min,
        top_n=args.top,
        usar_api=args.api,
        output_dir=output_dir,
        csv_cache=Path(args.csv) if args.csv else None,
        periodo=args.periodo,
    )


if __name__ == "__main__":
    main()
