# CarbonChain — Cartesi dApp (cartesi/)

Execução do pipeline MRV dentro de uma máquina Linux verificável (RISC-V) via Cartesi Rollup. O resultado é gravado on-chain com hash SHA-256 — qualquer auditor pode re-executar o cálculo e confirmar que o hash bate.

---

## O que é o Cartesi

Cartesi é uma plataforma que permite rodar código Linux arbitrário dentro de uma máquina virtual verificável on-chain. Isso resolve um problema central do mercado de carbono: qualquer um pode afirmar que fez o cálculo correto, mas ninguém pode verificar.

Com Cartesi, o cálculo MRV roda dentro de uma máquina RISC-V determinística. O resultado é gravado na blockchain com um hash único — qualquer auditor pode re-executar exatamente o mesmo código com os mesmos inputs e verificar que o hash é idêntico. Nenhum projeto de carbono faz isso hoje.

---

## Estrutura

```
cartesi/
└── dapp/
    └── carbonchain-mrv/
        ├── dapp.py       ← pipeline MRV on-chain + emissão de Vouchers
        └── Dockerfile    ← imagem Linux para o Cartesi Machine
```

---

## O que o dapp.py faz

Aceita dois tipos de input via `advance`:

**`calcular_mrv`** — recebe dados de uma fazenda e calcula os VCUs:
```json
{
  "acao": "calcular_mrv",
  "cpa_id": "CPA-GO-001",
  "fazenda": "Fazenda Piloto — Itumbiara, GO",
  "area_ha": 800,
  "soc_t0": 1.800,
  "soc_t1": 1.811,
  "areas": {
    "solo_ha": 528,
    "reserva_ha": 267,
    "arr_ha": 40
  }
}
```

**`registrar_cpa`** — registra uma nova fazenda no PoA.

Outputs por execução:
- **Notice** — resultado completo com VCUs, receitas e hash SHA-256
- **Voucher** — instrução de mint para o `CCTFactory.sol`

---

## Metodologias implementadas

| Token | Metodologia | Cálculo |
|---|---|---|
| CCT-SOIL | VM0042 v2.2 | ΔC_SOC × BD × profundidade × C_to_CO₂ |
| CCT-REDD | VM0015 | área × taxa_desmat × carbono_total × (1 - leakage) |
| CCT-ARR | VM0047 | sequestro por restauração de área degradada |

Todos os cálculos aplicam: incerteza (20%) + buffer de permanência (15%) + leakage.

---

## Fluxo completo

```
Input JSON (advance)
       ↓
dapp.py executa cálculo MRV dentro do Cartesi
       ↓
Hash SHA-256 gerado sobre os inputs e resultado
       ↓
Notice → resultado gravado on-chain (auditável)
Voucher → instrução mintFromVoucher() para CCTFactory
       ↓
CCTFactory.sol minta CCT-SOIL + CCT-REDD + CCT-ARR
```

---

## CCT_FACTORY_ADDR

O endereço do `CCTFactory` deployado deve ser atualizado no `dapp.py`:

```python
# cartesi/dapp/carbonchain-mrv/dapp.py
CCT_FACTORY_ADDR = "0xfA4150eFd8a152a48B9332F68EA2589933FcBA1B"  # Sepolia testnet
```

Após deploy na Mainnet, substituir pelo endereço de produção.

---

## Rodar localmente

```bash
cd cartesi/dapp/carbonchain-mrv
pip install requests
python dapp.py
```

Para rodar dentro do Cartesi Machine completo, consultar a documentação oficial em [docs.cartesi.io](https://docs.cartesi.io).
