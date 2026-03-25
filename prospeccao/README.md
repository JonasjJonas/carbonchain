# CarbonChain — Pipeline de Prospecção e MRV

Esta pasta contém dois scripts que formam o pipeline completo de entrada de fazendas no CarbonChain: desde a identificação de candidatos até a análise de satélite.

---

## Scripts

### `prospectar.py` — Pré-qualificação de fazendas
Identifica fazendas candidatas em qualquer município brasileiro cruzando dados do SICAR com uso do solo do MapBiomas.

### `pipeline.py` — Integração prospecção → MRV satélite
Executa o `prospectar.py` e alimenta automaticamente o `mrv/satellite.py` com as fazendas qualificadas, gerando mapas NDVI e dados de amostragem NIR para cada uma.

---

## Fluxo completo

```
prospectar.py                    pipeline.py
─────────────                    ───────────
API IBGE           →   Resolve código do município
WFS SICAR          →   Busca imóveis rurais com CAR
Filtro área        →   Remove fazendas < área mínima
API MapBiomas      →   Consulta uso do solo 2022-2024
Ranking            →   Classifica por % agrícola (VM0047)
                   →   Seleciona top N (PRIORIDADE_1)
                   →   Busca geometrias (bbox) no SICAR
                   ↓
              mrv/satellite.py
                   →   Analisa cada fazenda (NDVI, SOC, BSI)
                   →   Gera mapa visual PNG
                   →   Gera JSON com pontos de amostragem NIR
                   →   Salva em data/prospeccao/{CPA_ID}/
```

---

## Instalação

```bash
cd prospeccao
python3 -m venv venv
source venv/bin/activate
pip install requests pandas tqdm numpy matplotlib scipy
```

---

## Uso

### Só prospecção (sem satélite)
```bash
python3 prospectar.py --municipio "Itumbiara" --estado GO
python3 prospectar.py --municipio "Rio Verde" --estado GO --area-min 500
python3 prospectar.py --municipio "Sorriso" --estado MT --area-min 1000
```
Gera um CSV rankeado com todas as fazendas candidatas.

### Pipeline completo (prospecção + satélite)
```bash
python3 pipeline.py --municipio "Itumbiara" --estado GO --top 10
python3 pipeline.py --municipio "Rio Verde" --estado GO --area-min 500 --top 20
```

### Pipeline com cache (pula SICAR + MapBiomas se CSV já existe)
```bash
# Usa CSV gerado anteriormente — muito mais rápido
python3 pipeline.py --municipio "Itumbiara" --estado GO --top 10 \
  --csv ../data/prospeccao/itumbiara_go_vm0047.csv
```

### Pipeline com dados reais Copernicus (requer credenciais)
```bash
python3 pipeline.py --municipio "Itumbiara" --estado GO --top 5 --api
```

---

## Argumentos

| Argumento | Descrição | Default |
|---|---|---|
| `--municipio` | Nome do município | obrigatório |
| `--estado` | Sigla do estado (GO, MT, SP...) | obrigatório |
| `--area-min` | Área mínima em hectares | 200 |
| `--top` | Quantas fazendas enviar para o satélite | 10 |
| `--csv` | CSV de prospecção já gerado (pula SICAR + MapBiomas) | — |
| `--api` | Usar API Copernicus real | False |
| `--output` | Pasta de saída | `data/prospeccao/` |

---

## Outputs

```
data/prospeccao/
├── itumbiara_go_vm0047.csv         ← cache da prospecção (todas as fazendas)
├── itumbiara_go_mrv_resumo.json    ← resumo consolidado do MRV
├── CPA-GO-001/
│   ├── mapa_ndvi_CPA-GO-001.png   ← mapa visual NDVI + SOC + pontos NIR
│   └── resultado_sat_CPA-GO-001.json  ← dados MRV para mrv_calculator.py
├── CPA-GO-002/
│   └── ...
└── ...
```

> A pasta `data/` é ignorada pelo git (`.gitignore`). Cada rodada gera os outputs localmente.

---

## Classificação de prioridade (prospectar.py)

| Prioridade | Critério | Ação recomendada |
|---|---|---|
| `PRIORIDADE_1` | 80–100% agrícola | Enviar para MRV satélite |
| `PRIORIDADE_2` | 60–80% agrícola | Segunda rodada |
| `VERIFICAR` | 100–130% agrícola | Verificar manualmente |
| `FORA_ESCOPO` | < 60% agrícola | Descartar |
| `DESCARTAR` | > 130% agrícola | Erro de cadastro |

---

## Credenciais Copernicus (modo `--api`)

Para usar dados reais Sentinel-2, crie um arquivo `.env` na raiz do repositório:

```
SH_CLIENT_ID=seu_client_id
SH_CLIENT_SECRET=seu_client_secret
```

Conta gratuita em: https://dataspace.copernicus.eu

---

## Posição no repositório

```
carbonchain/
├── mrv/
│   ├── satellite.py        ← análise de satélite (chamado pelo pipeline)
│   ├── nir_model.py
│   └── mrv_calculator.py
├── prospeccao/
│   ├── prospectar.py       ← pré-qualificação SICAR + MapBiomas
│   ├── pipeline.py         ← integração completa
│   └── README.md           ← este arquivo
├── cartesi/
├── token/
└── data/                   ← outputs gerados (não versionado)
    └── prospeccao/
        └── CPA-GO-00X/
```
