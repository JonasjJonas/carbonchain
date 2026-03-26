# CarbonChain

Plataforma brasileira que conecta produtores rurais ao mercado voluntário global de créditos de carbono, com MRV auditável on-chain via Cartesi.

---

## O que é

O CarbonChain automatiza todo o ciclo de vida de um crédito de carbono agrícola — da identificação da fazenda à emissão do token verificado na blockchain — sem que o produtor precise entender nada de carbono, certificação ou tecnologia.

```
Fazenda identificada → MRV por satélite + sensor NIR → Cálculo VM0042/VM0047/REDD+
→ Verificação Verra → Token CCT-* on-chain → Venda no mercado voluntário → Pagamento ao produtor
```

---

## Metodologias suportadas

| Metodologia | Escopo | Status |
|---|---|---|
| **VM0042 v2.2** | Melhoria de práticas agrícolas — solo | ✅ Implementado |
| **VM0047** | Agricultura regenerativa — carbono no solo | ✅ Implementado |
| **VM0015 (REDD+)** | Proteção de Reserva Legal | ✅ Implementado |
| **ARR** | Restauração e reflorestamento | ⏳ Em desenvolvimento |

---

## Diferencial técnico

O cálculo MRV roda dentro de uma máquina Linux verificável (RISC-V) via **Cartesi Rollup**. O resultado é gravado on-chain com hash único — qualquer auditor pode re-executar o cálculo e verificar que o hash bate. Nenhum projeto de carbono faz isso hoje.

```
validator-1  | INFO: CarbonChain — nova solicitação de cálculo MRV
validator-1  | INFO: Calculando créditos para: fazenda_rio_verde_001 | 600ha
validator-1  | INFO: Créditos vendáveis: 1750.32 tCO₂e
validator-1  | INFO: Hash: 361e58690c58236e8fe6d1fad12c77441639d251e96c16c2783432ac373ba5e3
validator-1  | INFO: ✅ Cálculo concluído e gravado on-chain
```

---

## Stack técnica

| Componente | Tecnologia | O que faz |
|---|---|---|
| Prospecção | SICAR WFS + MapBiomas API | Identifica fazendas candidatas por município |
| Satélite | Sentinel-2 / Copernicus | NDVI, NDWI, SOC proxy, mapa de zonas |
| Solo | AgroCares NIR (calibração Cerrado) | Medição direta de carbono orgânico no solo |
| Cálculo MRV | Python (VM0042/VM0047/VM0015) | ~831 VCUs por fazenda de 800ha |
| On-chain | Cartesi Rollup + Voucher mint | Execução auditável, hash verificável |
| Token | CCT-* ERC-20 (Fase 2) | 1 token = 1 tCO₂e certificado |
| Certificação | Verra Registry | VCU com ID único gravado nos metadados |

---

## Estrutura do repositório

```
carbonchain/
├── mrv/
│   ├── satellite.py        # Análise Sentinel-2: NDVI, NDWI, SOC proxy, pontos NIR
│   ├── nir_model.py        # Modelo AgroCares NIR — calibração Cerrado
│   └── mrv_calculator.py   # Cálculo VM0042 + VM0015 + VM0047
│
├── cartesi/
│   └── dapp/carbonchain-mrv/
│       └── dapp.py         # MRV on-chain, Voucher mint via Cartesi Rollup
│
├── prospeccao/
│   ├── prospectar.py       # Pré-qualificação: SICAR + MapBiomas + ranking VM0047
│   ├── pipeline.py         # Integração prospecção → MRV satélite
│   └── README.md           # Documentação do pipeline
│
├── token/                  # Smart contracts CCT-* (Fase 2)
│
├── docs/
│   └── calculo_gravado_onchain.png
│
├── data/                   # Outputs gerados localmente (não versionado)
│   └── prospeccao/
│       └── CPA-GO-00X/
│           ├── mapa_ndvi_CPA-GO-00X.png
│           └── resultado_sat_CPA-GO-00X.json
│
├── .env                    # Credenciais Copernicus (não versionado)
└── requirements.txt
```

---

## Início rápido


Documentação completa de instalação, argumentos e outputs: [`prospeccao/README.md`](prospeccao/README.md)

---

## Pipeline de prospecção

O pipeline identifica e prioriza fazendas candidatas em qualquer município brasileiro:

1. **SICAR** — busca todos os imóveis com CAR ativo via WFS GeoServer
2. **MapBiomas** — consulta uso do solo 2022–2024 via API
3. **Ranking** — classifica por % de uso agrícola (perfil VM0047)
4. **Satélite** — analisa as top N fazendas com Sentinel-2

Resultado por fazenda:
- Mapa visual NDVI + SOC proxy + pontos de amostragem NIR
- JSON estruturado para consumo pelo `mrv_calculator.py`
- Estimativa de elegibilidade por metodologia

---

## Prova de execução on-chain

Hash de exemplo:
`361e58690c58236e8fe6d1fad12c77441639d251e96c16c2783432ac373ba5e3`

---

## Licença

Proprietary License

Copyright (c) 2026 JonasjJonas 
All rights reserved.
