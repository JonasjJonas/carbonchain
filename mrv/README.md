# CarbonChain — MRV (mrv/)

Pipeline de Monitoramento, Relatório e Verificação (MRV) por satélite e sensor NIR.

---

## Scripts

| Arquivo | O que faz |
|---|---|
| `satellite.py` | Análise Sentinel-2 — classificação temporal de zonas (ΔNDVI úmido vs. seco), NDVI, SOC proxy, pontos de amostragem NIR |
| `nir_model.py` | Modelo AgroCares NIR calibrado para o Cerrado — estima SOC a partir de leituras espectrais em campo |
| `mrv_calculator.py` | Calculadora VM0042/VM0015/VM0047 — lê o JSON do satellite.py e calcula VCUs por ativo |

---

## Uso rápido (3 passos)

Todos os comandos a partir de `~/carbonchain`:

### Passo 1 — Prospecção + Satélite (pipeline completo)

```bash
cd prospeccao
python3 pipeline.py --municipio "Itumbiara" --estado GO --top 5 --api
```

Isso roda tudo: SICAR → MapBiomas → ranking → Sentinel-2 (úmido + seco) → classificação temporal → JSON + mapa.

Se já tiver o CSV de prospecção de uma rodada anterior:

```bash
python3 pipeline.py --municipio "Itumbiara" --estado GO --top 5 --api \
  --csv ../data/prospeccao/itumbiara_go_vm0047.csv
```

### Passo 2 — Calcular créditos de carbono

```bash
cd ~/carbonchain

# Uma fazenda (pelo CPA ID)
python mrv/mrv_calculator.py --farm CPA-GO-001

# Todas as fazendas de uma vez
python mrv/mrv_calculator.py --all
```

### Passo 3 — Verificar resultados

```
data/prospeccao/CPA-GO-001/
├── mapa_ndvi_CPA-GO-001.png         ← 4 painéis: NDVI úmido, NDVI seco, zonas ΔNDVI, pontos NIR
├── resultado_sat_CPA-GO-001.json    ← dados satellite.py
└── resultado_mrv_CPA-GO-001.json    ← VCUs por ativo → CCTFactory.sol (mint)
```

---

## Opções avançadas

### mrv_calculator.py

```bash
# Caminho completo do JSON (em vez de CPA ID)
python mrv/mrv_calculator.py --farm data/prospeccao/CPA-GO-002/resultado_sat_CPA-GO-002.json

# Override manual de SOC (se tiver dados NIR de campo)
python mrv/mrv_calculator.py --farm CPA-GO-001 --soc-t0 2.1 --soc-t1 2.12
```

Sem `--soc-t0`/`--soc-t1`, o SOC é derivado automaticamente do `soc_proxy` do JSON.

### satellite.py avulso (sem prospecção, dados sintéticos)

```bash
python mrv/satellite.py --farm itumbiara
python mrv/satellite.py --all
```

---

## Fluxo interno

```
prospeccao/pipeline.py
  └→ mrv/satellite.py
       → busca 2 imagens Sentinel-2 (úmido + seco) via buscar_sentinel2_bitemporal()
       → aplica máscara do polígono real (SICAR)
       → calcula NDVI, NDWI, SOC proxy, BSI, NBR
       → classifica zonas por ΔNDVI temporal
       → normaliza áreas para bater com o CAR
       → gera mapa 4 painéis PNG + resultado_sat_{CPA_ID}.json

mrv/mrv_calculator.py
  → lê resultado_sat_{CPA_ID}.json
  → deriva SOC do soc_proxy (ou aceita valores manuais)
  → aplica VM0042 (solo), VM0015 (REDD+), VM0047 (ARR)
  → aplica incerteza 20% + buffer 15% + leakage
  → gera resultado_mrv_{CPA_ID}.json → CCTFactory.sol (mint)
```

---

## Classificação temporal de zonas

O `satellite.py` busca automaticamente duas imagens Sentinel-2 (úmido + seco) e usa o ΔNDVI para separar lavoura de reserva — resolvendo a ambiguidade de NDVI alto durante a safra.

| ΔNDVI | Classificação | Destino MRV |
|---|---|---|
| > 0.35 | Lavoura anual (solo exposto pós-colheita) | SOIL (VM0042) |
| 0.20–0.35 | Zona cinza (safrinha / pasto manejado) | SOIL (conservadorismo) |
| 0.10–0.20 | Cerrado aberto / pastagem nativa | Vegetação moderada |
| < 0.10 | Reserva densa (mata / cerradão) | REDD (VM0015) |

A zona cinza é tratada como solo agrícola por conservadorismo — melhor subestimar reserva do que inflar REDD+.

As áreas são normalizadas proporcionalmente para bater com a área declarada no CAR.

---

## Mapa de saída (4 painéis)

| Painel | O que mostra |
|---|---|
| NDVI — Período Úmido | Imagem Sentinel-2 jan-mar (lavoura no pico vegetativo) |
| NDVI — Período Seco | Imagem Sentinel-2 jun-ago (lavoura colhida, reserva estável) |
| Classificação Temporal | Mapa categórico de zonas por ΔNDVI |
| Pontos de Amostragem NIR | Distribuição dos pontos para coleta em campo |

---

## Metodologias

| Ativo | Metodologia | Fórmula principal |
|---|---|---|
| CCT-SOIL | VM0042 v2.2 | ΔC_SOC = (SOC_t1 − SOC_t0) × BD × D × 10.000 × (44/12) |
| CCT-REDD | VM0015 | REDD = área × taxa_desmat × carbono_total × C_to_CO₂ × (1 − leakage) |
| CCT-ARR | VM0047 | Sequestro por restauração de área degradada |

Todos os cálculos aplicam: incerteza 20% + buffer de permanência 15%.

---

## Dependências

```
sentinelhub>=3.9.0
numpy>=1.24.0
scipy>=1.10.0
matplotlib>=3.7.0
python-dotenv>=1.0.0
```
