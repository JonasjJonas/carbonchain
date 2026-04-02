# CarbonChain — Prospecção (prospeccao/)

Pipeline de entrada de fazendas no CarbonChain: da identificação de candidatos via SICAR até a análise de satélite com dados reais do Sentinel-2.

---

## Scripts

| Script | O que faz |
|---|---|
| `prospectar.py` | Busca fazendas por município no SICAR, cruza com MapBiomas e gera ranking de candidatos VM0047 |
| `pipeline.py` | Integra prospectar.py com mrv/satellite.py — roda prospecção e análise satélite em sequência |

---

## Setup

```bash
cd ~/carbonchain/prospeccao
python3 -m venv venv
source venv/bin/activate
pip install requests pandas tqdm numpy matplotlib scipy python-dotenv sentinelhub
```

### Credenciais Copernicus (obrigatório para dados reais)

1. Crie conta gratuita em [dataspace.copernicus.eu](https://dataspace.copernicus.eu)
2. Vá em **User Settings → OAuth Clients → Create** (Never expire)
3. Adicione ao `.env` na raiz do repositório:

```
SH_CLIENT_ID=seu_client_id
SH_CLIENT_SECRET=seu_client_secret
```

---

## Uso

Sempre ative o venv antes de rodar:

```bash
cd ~/carbonchain/prospeccao
source venv/bin/activate
```

### Só prospecção (ranking de fazendas, sem satélite)

```bash
python3 prospectar.py --municipio "Itumbiara" --estado GO
python3 prospectar.py --municipio "Rio Verde" --estado GO --area-min 500
python3 prospectar.py --municipio "Sorriso" --estado MT --area-min 1000
```

Gera um CSV rankeado com todas as fazendas do município.

### Pipeline completo (prospecção + satélite)

```bash
# Primeira rodada — roda SICAR + MapBiomas + Sentinel-2
python3 pipeline.py --municipio "Itumbiara" --estado GO --top 5 --api

# Rodadas seguintes — usa cache CSV (pula SICAR + MapBiomas)
python3 pipeline.py --municipio "Itumbiara" --estado GO --top 5 --api \
  --csv ../data/prospeccao/itumbiara_go_vm0047.csv
```

O pipeline busca automaticamente duas imagens Sentinel-2 (úmido + seco) para cada fazenda e faz a classificação temporal de zonas.

Ao final, cada fazenda terá seus resultados em `data/prospeccao/{CPA_ID}/`.

> Para calcular os créditos de carbono (VCUs) a partir dos resultados, veja `mrv/README.md`.

---

## Argumentos

### prospectar.py

| Argumento | Descrição | Default |
|---|---|---|
| `--municipio` | Nome do município | obrigatório |
| `--estado` | Sigla do estado (GO, MT, SP...) | obrigatório |
| `--area-min` | Área mínima em hectares | 200 |
| `--output` | Nome do CSV de saída | `{municipio}_vm0047.csv` |

### pipeline.py

| Argumento | Descrição | Default |
|---|---|---|
| `--municipio` | Nome do município | obrigatório |
| `--estado` | Sigla do estado | obrigatório |
| `--area-min` | Área mínima em hectares | 200 |
| `--top` | Quantas fazendas PRIORIDADE_1 analisar | 10 |
| `--api` | Usar API Copernicus com dados reais | False |
| `--csv` | CSV já gerado — pula SICAR + MapBiomas | — |
| `--output` | Pasta de saída | `data/prospeccao/` |

---

## Fluxo

```
prospectar.py                    pipeline.py
─────────────                    ───────────
API IBGE           →   Resolve código do município
WFS SICAR          →   Busca imóveis rurais com CAR
Filtro área        →   Remove fazendas < área mínima
API MapBiomas      →   Consulta uso do solo 2022-2024
Ranking            →   Classifica por % agrícola (VM0047)
                   →   Seleciona top N (PRIORIDADE_1)
                   →   Busca geometrias (polígono) no SICAR
                   ↓
              mrv/satellite.py
                   →   Busca 2 imagens Sentinel-2 (úmido + seco)
                   →   Aplica máscara do polígono real
                   →   Classifica zonas por ΔNDVI temporal
                   →   Normaliza áreas para o CAR
                   →   Gera mapa 4 painéis PNG + JSON
                   →   Salva em data/prospeccao/{CPA_ID}/
```

---

## Classificação temporal

O pipeline busca **duas imagens** Sentinel-2 para cada fazenda: período úmido (jan-mar) e período seco (jun-ago). A diferença de NDVI entre elas revela o uso real do solo:

- Lavoura: NDVI alto na chuva → baixo na seca (colhida) → **ΔNDVI > 0.35**
- Reserva: NDVI alto na chuva → ainda alto na seca (perene) → **ΔNDVI < 0.10**

---

## Classificação de prioridade

| Prioridade | Critério | Ação |
|---|---|---|
| `PRIORIDADE_1` | 80–100% agrícola | Enviar para análise satélite |
| `PRIORIDADE_2` | 60–80% agrícola | Segunda rodada |
| `VERIFICAR` | 100–130% agrícola | Verificar manualmente |
| `FORA_ESCOPO` | < 60% agrícola | Descartar |
| `DESCARTAR` | > 130% agrícola | Erro de cadastro |

---

## Outputs

```
data/prospeccao/
├── itumbiara_go_vm0047.csv              ← cache da prospecção
├── itumbiara_go_mrv_resumo.json         ← resumo consolidado
├── CPA-GO-001/
│   ├── mapa_ndvi_CPA-GO-001.png        ← mapa 4 painéis
│   └── resultado_sat_CPA-GO-001.json   ← dados para mrv_calculator.py
└── ...
```
