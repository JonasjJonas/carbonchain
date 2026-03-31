# CarbonChain — MRV (mrv/)

Pipeline de Monitoramento, Relatório e Verificação (MRV) por satélite e sensor NIR.

---

## Scripts

| Arquivo | O que faz |
|---|---|
| `satellite.py` | Análise Sentinel-2 — NDVI, classificação temporal de zonas (ΔNDVI úmido vs. seco), SOC proxy, pontos de amostragem NIR |
| `nir_model.py` | Modelo AgroCares NIR calibrado para o Cerrado — estima SOC a partir de leituras espectrais em campo |
| `mrv_calculator.py` | Calculadora VM0042/VM0015/VM0047 — lê o JSON do satellite.py e calcula VCUs por ativo |

---

## Uso

### Pré-requisito: prospecção

O `prospeccao/pipeline.py` gera os JSONs de satélite para cada fazenda. Rode-o primeiro (ver `prospeccao/README.md`):

```bash
cd prospeccao
python3 pipeline.py --municipio "Itumbiara" --estado GO --api 
```

Ao final, cada fazenda terá um JSON em `data/prospeccao/{CPA_ID}/resultado_sat_{CPA_ID}.json`.

### Calcular créditos de carbono

A partir de `~/carbonchain`:

```bash
# Uma fazenda (pelo CPA ID — resolve o JSON automaticamente)
python mrv/mrv_calculator.py --farm CPA-GO-001

# Ou pelo caminho completo do JSON
python mrv/mrv_calculator.py --farm data/prospeccao/CPA-GO-002/resultado_sat_CPA-GO-002.json

# Todas as fazendas de uma vez (busca em data/prospeccao/ e data/sample_farm/)
python mrv/mrv_calculator.py --all
```

O SOC é derivado automaticamente do `soc_proxy` do JSON. Se tiver dados NIR de campo, pode passar manualmente:

```bash
python mrv/mrv_calculator.py --farm CPA-GO-001 --soc-t0 2.1 --soc-t1 2.12
```

### Rodar satellite.py avulso (sem prospecção)

Para análise rápida com dados sintéticos:

```bash
python mrv/satellite.py --farm itumbiara
python mrv/satellite.py --all
```

---

## Fluxo

```
prospeccao/pipeline.py
  └→ mrv/satellite.py
       → coleta imagens Sentinel-2 (úmido + seco)
       → aplica máscara do polígono real (SICAR)
       → calcula NDVI, NDWI, SOC proxy, BSI, NBR
       → classifica zonas por ΔNDVI temporal
       → gera mapa PNG + resultado_sat_{CPA_ID}.json

mrv/mrv_calculator.py
  → lê resultado_sat_{CPA_ID}.json
  → deriva SOC do soc_proxy (ou aceita valores manuais)
  → aplica VM0042 (solo), VM0015 (REDD+), VM0047 (ARR)
  → aplica incerteza 20% + buffer 15% + leakage
  → gera resultado_mrv_{CPA_ID}.json → CCTFactory.sol (mint)
```

---

## Classificação Temporal de Zonas

O `satellite.py` usa ΔNDVI entre período úmido (jan-mar) e seco (jun-ago) para separar lavoura de reserva — resolvendo a ambiguidade de NDVI alto durante a safra.

| ΔNDVI | Classificação | Destino MRV |
|---|---|---|
| > 0.35 | Lavoura anual (solo exposto pós-colheita) | SOIL (VM0042) |
| 0.20–0.35 | Zona cinza (safrinha / pasto manejado) | SOIL (conservadorismo) |
| 0.10–0.20 | Cerrado aberto / pastagem nativa | Vegetação moderada |
| < 0.10 | Reserva densa (mata / cerradão) | REDD (VM0015) |

A zona cinza é tratada como solo agrícola por conservadorismo — melhor subestimar reserva do que inflar REDD+.

Sem dados do período seco, o script usa classificação estática por NDVI como fallback.

---

## Metodologias

| Ativo | Metodologia | Fórmula principal |
|---|---|---|
| CCT-SOIL | VM0042 v2.2 | ΔC_SOC = (SOC_t1 − SOC_t0) × BD × D × 10.000 × (44/12) |
| CCT-REDD | VM0015 | REDD = área × taxa_desmat × carbono_total × C_to_CO₂ × (1 − leakage) |
| CCT-ARR | VM0047 | Sequestro por restauração de área degradada |

Todos os cálculos aplicam: incerteza 20% + buffer de permanência 15%.

---

## Outputs

```
data/prospeccao/{CPA_ID}/
├── mapa_ndvi_{CPA_ID}.png          ← mapa NDVI + SOC proxy + pontos NIR
├── resultado_sat_{CPA_ID}.json     ← dados satellite.py → mrv_calculator.py
└── resultado_mrv_{CPA_ID}.json     ← VCUs por ativo → CCTFactory.sol (mint)
```

---

## Dependências

```
sentinelhub>=3.9.0
numpy>=1.24.0
scipy>=1.10.0
matplotlib>=3.7.0
python-dotenv>=1.0.0
```

Instalar com o venv do pipeline:
```bash
cd prospeccao
source venv/bin/activate
pip install -r ../requirements.txt
```
