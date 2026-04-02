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

## Pré-requisito

O `prospeccao/pipeline.py` gera os JSONs de satélite para cada fazenda. Rode-o primeiro (ver `prospeccao/README.md`).

---

## Uso

Ative o venv e volte para a raiz do projeto:

```bash
cd ~/carbonchain
source prospeccao/venv/bin/activate
```

### Calcular créditos de uma fazenda

```bash
python mrv/mrv_calculator.py --farm CPA-GO-001
```

Aceita tanto o CPA ID (resolve o JSON automaticamente) quanto o caminho completo:

```bash
python mrv/mrv_calculator.py --farm data/prospeccao/CPA-GO-002/resultado_sat_CPA-GO-002.json
```

### Calcular todas as fazendas de uma vez

```bash
python mrv/mrv_calculator.py --all
```

Busca JSONs em `data/prospeccao/` e `data/sample_farm/`.

### Override manual de SOC (com dados NIR de campo)

```bash
python mrv/mrv_calculator.py --farm CPA-GO-001 --soc-t0 2.1 --soc-t1 2.12
```

Sem `--soc-t0`/`--soc-t1`, o SOC é derivado automaticamente do `soc_proxy` do JSON.

---

## Fluxo

```
resultado_sat_{CPA_ID}.json        (gerado pelo prospeccao/pipeline.py)
  ↓
mrv/mrv_calculator.py
  → lê o JSON
  → deriva SOC do soc_proxy (ou aceita valores manuais)
  → calcula 3 ativos:
      SOIL (VM0042) — solo agrícola em transição regenerativa
      REDD (VM0015) — Reserva Legal com vegetação nativa preservada
      ARR  (VM0047) — área em restauração ativa
  → aplica incerteza 20% + buffer 15% + leakage
  → gera resultado_mrv_{CPA_ID}.json → CCTFactory.sol (mint)
```

---

## Outputs

```
data/prospeccao/{CPA_ID}/
├── mapa_ndvi_{CPA_ID}.png         ← mapa 4 painéis (gerado pelo satellite.py)
├── resultado_sat_{CPA_ID}.json    ← input do mrv_calculator.py
└── resultado_mrv_{CPA_ID}.json    ← VCUs por ativo → CCTFactory.sol (mint)
```

---

## Classificação temporal de zonas

O `satellite.py` (chamado pelo pipeline) busca duas imagens Sentinel-2 (úmido + seco) e usa o ΔNDVI para classificar o uso do solo:

| ΔNDVI | Classificação | Destino MRV |
|---|---|---|
| > 0.35 | Lavoura anual | SOIL (VM0042) |
| 0.20–0.35 | Zona cinza (safrinha / pasto) | SOIL (conservadorismo) |
| 0.10–0.20 | Cerrado aberto | Vegetação moderada |
| < 0.10 | Reserva densa | REDD (VM0015) |

As áreas são normalizadas proporcionalmente para bater com a área declarada no CAR.

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
