# CarbonChain 🌱

Carbon credit certification platform for Brazilian farmers — MRV on-chain via Cartesi.

## O que é
Plataforma que conecta produtores rurais brasileiros ao mercado global de créditos 
de carbono, usando satélite + sensor NIR + blockchain (Cartesi) para emitir créditos 
certificados pela Verra VM0042.

## Stack técnico
- **MRV:** Python · Sentinel-2 API · sensor NIR (AgroCares)
- **Blockchain:** Cartesi rollup · Polygon
- **Certificação:** Verra VM0042 v2.1 · ICVCM CCP

## Estrutura
| Pasta | Conteúdo |
|---|---|
| `mrv/` | Cálculo de carbono — VM0042, satélite, NIR |
| `cartesi/` | Rollup on-chain — dApp Cartesi |
| `token/` | Smart contracts |
| `docs/` | Whitepaper, one-pager, pitch deck |
| `notebooks/` | Análises e demonstrações |
| `data/` | Dados de exemplo — fazenda 200ha |

## Como rodar
```bash
pip install -r requirements.txt
python mrv/satellite.py
```

## Status
🚧 Em desenvolvimento ativo

## Licença
MIT
