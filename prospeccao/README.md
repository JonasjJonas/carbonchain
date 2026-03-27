# CarbonChain — Pipeline de Prospecção e MRV

Pipeline completo de entrada de fazendas no CarbonChain: da identificação de candidatos via SICAR até a análise de satélite com dados reais do Sentinel-2.

---

## Scripts

| Script | O que faz |
|---|---|
| `prospectar.py` | Busca fazendas por município no SICAR, cruza com MapBiomas e gera ranking de candidatos VM0047 |
| `pipeline.py` | Integra prospectar.py com mrv/satellite.py — roda prospecção e análise satélite em sequência |

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
                   →   Busca geometrias (polígono) no SICAR
                   →   Aplica máscara do polígono real
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
python3 -m venv venv
source venv/bin/activate
pip install requests pandas tqdm numpy matplotlib scipy python-dotenv sentinelhub
```

### Credenciais Copernicus (para dados reais de satélite)

1. Crie conta gratuita em [dataspace.copernicus.eu](https://dataspace.copernicus.eu)
2. Vá em **User Settings → OAuth Clients → Create** (Never expire)
3. Adicione ao `.env` na raiz do repositório:

```
SH_CLIENT_ID=seu_client_id
SH_CLIENT_SECRET=seu_client_secret
```

---

## Uso

### Só prospecção
```bash
python3 prospectar.py --municipio "Itumbiara" --estado GO
python3 prospectar.py --municipio "Rio Verde" --estado GO --area-min 500
python3 prospectar.py --municipio "Sorriso" --estado MT --area-min 1000
```

### Pipeline completo (prospecção + satélite)
```bash
# Dados sintéticos — sem credenciais Copernicus
python3 pipeline.py --municipio "Itumbiara" --estado GO --top 10

# Dados reais Sentinel-2 — período recente (últimos 30 dias)
python3 pipeline.py --municipio "Itumbiara" --estado GO --top 10 --api

# Dados reais — período seco (junho-agosto, recomendado para Cerrado)
python3 pipeline.py --municipio "Itumbiara" --estado GO --top 10 --api --periodo seco

# Com cache de prospecção já gerado (pula SICAR + MapBiomas)
python3 pipeline.py --municipio "Itumbiara" --estado GO --top 10 --api --periodo seco \
  --csv ../data/prospeccao/itumbiara_go_vm0047.csv
```

---

## Argumentos

| Argumento | Descrição | Default |
|---|---|---|
| `--municipio` | Nome do município | obrigatório |
| `--estado` | Sigla do estado (GO, MT, SP...) | obrigatório |
| `--area-min` | Área mínima em hectares | 200 |
| `--top` | Quantas fazendas PRIORIDADE_1 analisar | 10 |
| `--api` | Usar API Copernicus com dados reais | False |
| `--periodo` | `recente` (últimos 30 dias) ou `seco` (jun-ago) | recente |
| `--csv` | CSV já gerado — pula SICAR + MapBiomas | — |
| `--output` | Pasta de saída | `data/prospeccao/` |

---

## Por que usar `--periodo seco`

No Cerrado, o período chuvoso (outubro–março) é problemático para classificação de uso do solo por satélite. Lavoura de soja, cana e milho em estágio vegetativo pleno atinge NDVI 0.70–0.85 — idêntico ao de floresta nativa.

Com `--periodo seco` o pipeline busca imagens de **junho a agosto**, quando:
- Lavouras já foram colhidas → NDVI baixo (~0.15–0.25)
- Floresta nativa mantém NDVI alto (~0.60–0.80)
- A distinção entre área agrícola e reserva legal é clara

> No período chuvoso (outubro–março), lavoura em estágio vegetativo tem NDVI idêntico ao de floresta nativa — o que gera classificações incorretas. Usando imagens do período seco (junho–agosto), quando a lavoura já foi colhida e o NDVI cai para 0.15–0.25, a distinção entre área agrícola e reserva legal fica clara e confiável.

---

## Máscara de polígono

O Sentinel-2 retorna um retângulo (bbox) que é sempre maior do que a fazenda. O pipeline aplica o polígono real do CAR como máscara antes de qualquer cálculo — pixels fora da propriedade são descartados (NaN).

Isso garante que:
- As zonas calculadas correspondem à área real da fazenda
- Os pontos de amostragem NIR ficam todos dentro do polígono
- As porcentagens de floresta/lavoura são da propriedade, não da região

---

## Densidade de amostragem NIR

Os pontos de coleta com sensor NIR seguem a VM0042 §7.3:

```
n_pontos = max(30, min(200, area_ha ÷ 8))
```

Exemplos para fazendas de Itumbiara:

| Fazenda | Área | Pontos NIR |
|---|---|---|
| CPA-GO-001 | 817 ha | 102 pontos |
| CPA-GO-002 | 595 ha | 74 pontos |
| CPA-GO-003 | 229 ha | 29 pontos |

---

## Outputs

```
data/prospeccao/
├── itumbiara_go_vm0047.csv              ← cache da prospecção (todas as fazendas)
├── itumbiara_go_mrv_resumo.json         ← resumo consolidado do MRV
├── CPA-GO-001/
│   ├── mapa_ndvi_CPA-GO-001.png        ← mapa NDVI + SOC proxy + pontos NIR
│   └── resultado_sat_CPA-GO-001.json   ← dados MRV para mrv_calculator.py
└── ...
```

> A pasta `data/` não é versionada — cada rodada gera os outputs localmente.

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
            ├── mapa_ndvi_CPA-GO-00X.png
            └── resultado_sat_CPA-GO-00X.json
```
