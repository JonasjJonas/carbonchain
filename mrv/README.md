# CarbonChain — MRV (mrv/)

Pipeline completo de Monitoramento, Relatório e Verificação (MRV) por satélite e sensor NIR.

---

## Scripts

| Arquivo | O que faz |
|---|---|
| `satellite.py` | Análise Sentinel-2 via API Copernicus — NDVI, SOC proxy, mapa de zonas, pontos de amostragem NIR |
| `nir_model.py` | Modelo AgroCares NIR calibrado para o Cerrado — estima SOC a partir de leituras espectrais em campo |
| `mrv_calculator.py` | Calculadora VM0042/VM0015/VM0047 — lê o JSON do satellite.py e calcula VCUs por ativo |

---

## Fluxo

```
satellite.py
→ coleta imagens Sentinel-2 via API Copernicus
→ aplica máscara do polígono real da fazenda (SICAR)
→ calcula NDVI, NDWI, SOC proxy, BSI, NBR
→ gera mapa visual PNG + resultado JSON

nir_model.py
→ recebe leituras do sensor NIR em campo
→ aplica calibração Cerrado (AgroCares)
→ estima SOC_t0 e SOC_t1 por ponto de amostragem

mrv_calculator.py
→ lê resultado_sat_{CPA_ID}.json
→ aplica VM0042 v2.2 (solo), VM0015 (REDD+), VM0047 (ARR)
→ aplica incerteza (20%) + buffer (15%) + leakage
→ calcula VCUs vendáveis por ativo
→ gera resultado_mrv_{CPA_ID}.json → CCTFactory.sol
```

---

## Metodologias

| Ativo | Metodologia | Fórmula principal |
|---|---|---|
| CCT-SOIL | VM0042 v2.2 | ΔC_SOC = (SOC_t1 − SOC_t0) × BD × D × 10.000 × (44/12) |
| CCT-REDD | VM0015 | REDD = área × taxa_desmat × carbono_total × C_to_CO₂ × (1 − leakage) |
| CCT-ARR | VM0047 | Sequestro por restauração de área degradada |

Todos os cálculos aplicam: incerteza 20% + buffer de permanência 15%.

---

## Uso

```bash
# Análise satélite — dados sintéticos (sem credenciais)
python mrv/satellite.py --farm itumbiara

# Análise satélite — dados reais Sentinel-2
python mrv/satellite.py --farm itumbiara --api

# Período seco (jun-ago) — melhor para distinguir floresta de lavoura
python mrv/satellite.py --farm itumbiara --api --periodo seco

# Calcular VCUs a partir do resultado do satellite.py
python mrv/mrv_calculator.py --input data/prospeccao/CPA-GO-001/resultado_sat_CPA-GO-001.json
```

Para o pipeline completo integrado com prospecção, use o `prospeccao/pipeline.py`.

---

## Outputs

```
data/prospeccao/{CPA_ID}/
├── mapa_ndvi_{CPA_ID}.png          ← mapa NDVI + SOC proxy + pontos NIR
├── resultado_sat_{CPA_ID}.json     ← dados MRV para mrv_calculator.py
└── resultado_mrv_{CPA_ID}.json     ← VCUs por ativo → CCTFactory.sol
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
