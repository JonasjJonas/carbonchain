# CarbonChain — Smart Contracts (token/)

Três contratos ERC-20 independentes para emissão e aposentadoria dos Carbon Credit Tokens, com ambiente Hardhat completo para compilação, testes e deploy.

---

## Estrutura

```
token/
├── contracts/
│   ├── CCTSoil.sol       ← CCT-SOIL (VM0042 — solo agrícola)
│   ├── CCTRedd.sol       ← CCT-REDD (VM0015 — REDD+)
│   ├── CCTArr.sol        ← CCT-ARR  (VM0047 — restauração)
│   └── CCTFactory.sol    ← gateway Cartesi → mint
├── scripts/
│   └── deploy.js         ← deploy automático na ordem correta
├── test/
│   └── CCTContracts.test.js  ← testes automáticos
├── deployments/          ← endereços gerados após cada deploy (auto)
├── hardhat.config.js     ← configuração do ambiente
├── package.json
├── .env.example          ← modelo de variáveis de ambiente
└── README.md
```

---

## Tokens

| Contrato | Símbolo | Metodologia | 1 token |
|---|---|---|---|
| `CCTSoil.sol` | **CCT-SOIL** | VM0042 v2.2 | 1 tCO₂e solo agrícola |
| `CCTRedd.sol` | **CCT-REDD** | VM0015 | 1 tCO₂e REDD+ |
| `CCTArr.sol` | **CCT-ARR** | VM0047 | 1 tCO₂e restauração |

Cada token tem endereço próprio na blockchain — aparecem separados em qualquer carteira (MetaMask, etc.) sem ambiguidade.

---

## Instalação

```bash
cd token
npm install
```

---

## Configuração

```bash
cp .env.example .env
# Editar .env com sua PRIVATE_KEY e SEPOLIA_RPC_URL
```

Para obter um RPC gratuito da Sepolia:
1. Acesse [alchemy.com](https://alchemy.com) → crie conta gratuita
2. Crie um app → selecione Ethereum Sepolia
3. Copie o HTTPS endpoint para `SEPOLIA_RPC_URL`

Para ETH de teste na Sepolia (gratuito):
- [sepoliafaucet.com](https://sepoliafaucet.com)
- [faucets.chain.link](https://faucets.chain.link/sepolia)

---

## Uso

### 1. Compilar os contratos
```bash
npm run compile
```
Verifica se o Solidity está correto e gera os artefatos em `artifacts/`.

### 2. Rodar os testes localmente
```bash
npm test
```
Roda todos os testes em blockchain local — gratuito, sem internet, resultado em segundos.

### 3. Deploy local (para explorar)
```bash
# Terminal 1 — inicia blockchain local
npm run node

# Terminal 2 — faz o deploy
npm run deploy:local
```

### 4. Deploy na Sepolia (testnet)
```bash
npm run deploy:sepolia
```
Requer `PRIVATE_KEY` e `SEPOLIA_RPC_URL` no `.env` e ETH de teste na carteira.

### 5. Atualizar dapp.py após deploy
Após o deploy, o script salva os endereços em `deployments/sepolia.json`.
Copie o endereço do `CCTFactory` para o `dapp.py`:
```python
# cartesi/dapp/carbonchain-mrv/dapp.py
CCT_FACTORY_ADDR = "0x..."  ← endereço do CCTFactory deployado
```

---

## Fluxo completo

```
Pipeline MRV → dapp.py (Cartesi) → Voucher mintFromVoucher()
      ↓
CCTFactory valida + previne double-mint
      ↓
CCTSoil.mintLote()  →  CCT-SOIL na tesouraria
CCTRedd.mintLote()  →  CCT-REDD na tesouraria
CCTArr.mintLote()   →  CCT-ARR  na tesouraria
      ↓
Venda → comprador chama retire() → tokens queimados permanentemente
```

---

## Dependências

```json
{
  "@nomicfoundation/hardhat-toolbox": "^5.0.0",
  "@openzeppelin/contracts": "^5.0.0",
  "hardhat": "^2.22.0"
}
```
