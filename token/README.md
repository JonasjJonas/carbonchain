# CarbonChain — Smart Contracts (token/)

Três contratos ERC-20 independentes para emissão e aposentadoria dos Carbon Credit Tokens, com ambiente Hardhat completo para compilação, testes e deploy.

---

## O que é isso

Um token na blockchain é um certificado digital que não pode ser falsificado, editado ou duplicado. Cada CCT-* representa 1 tCO₂e certificado pela Verra — transferível entre carteiras, auditável por qualquer pessoa e aposentável pelo comprador como prova de neutralização.

Ao contrário de um PDF ou planilha, um token na blockchain é imutável: depois de emitido, o registro existe para sempre e qualquer pessoa pode verificar sua autenticidade consultando o endereço do contrato.

---

## Contratos

| Contrato | Símbolo | Metodologia | 1 token |
|---|---|---|---|
| `CCTSoil.sol` | **CCT-SOIL** | VM0042 v2.2 | 1 tCO₂e solo agrícola |
| `CCTRedd.sol` | **CCT-REDD** | VM0015 | 1 tCO₂e REDD+ |
| `CCTArr.sol` | **CCT-ARR** | VM0047 | 1 tCO₂e restauração |
| `CCTFactory.sol` | — | — | Gateway Cartesi → mint |

Cada token tem endereço próprio na blockchain — aparecem separados em qualquer carteira (MetaMask, etc.) sem ambiguidade.

---

## Deploy na Sepolia (testnet)

Os contratos estão deployados na Ethereum Sepolia — uma blockchain real com blocos confirmados por validadores reais ao redor do mundo. A diferença da Mainnet é que o ETH não tem valor monetário, mas a tecnologia é idêntica.

| Contrato | Endereço (Sepolia) |
|---|---|
| CCTSoil | `0xB01fB4d36d78aFddaF4D35D6D97e5a84734e22b4` |
| CCTRedd | `0x5D5dA00f1d58084CaDdFfb4321EcD19aE257C3C8` |
| CCTArr | `0x1d65651c9120845eb81245493b184F5E86A0fb7B` |
| CCTFactory | `0xfA4150eFd8a152a48B9332F68EA2589933FcBA1B` |

Verificável em: [sepolia.etherscan.io](https://sepolia.etherscan.io)

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
│   └── CCTContracts.test.js  ← testes automáticos (14 passando)
├── deployments/
│   └── sepolia.json      ← endereços do deploy na testnet
├── hardhat.config.js     ← configuração do ambiente
├── package.json
├── .env.example          ← modelo de variáveis de ambiente
└── README.md
```

---

## Como o processo funciona

**Hardhat** é o ambiente de desenvolvimento para contratos Solidity. Ele compila o código `.sol` em bytecode que a blockchain entende, roda os testes em blockchain local sem internet, e publica os contratos na rede escolhida.

**Deploy** é o momento em que o contrato sai do computador e vai para a blockchain permanentemente. Após o deploy, cada contrato recebe um endereço único — como um CNPJ — e o código não pode mais ser alterado por ninguém, nem pelo autor.

**Sepolia vs Mainnet** — Sepolia é uma cópia de teste da blockchain Ethereum. Os contratos deployados na Sepolia são reais e verificáveis, mas o ETH usado não tem valor monetário. Para produção, o processo é idêntico com `--network mainnet`.

**CCTFactory** é o único ponto de entrada para criação de tokens. Somente o Cartesi Rollup pode chamar `mintFromVoucher()` — isso garante que todo crédito emitido vem de um cálculo MRV verificável on-chain. O Factory chama os três tokens internamente, então o `dapp.py` só precisa conhecer o endereço do Factory.

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
# Preencher PRIVATE_KEY e SEPOLIA_RPC_URL
```

Para obter RPC gratuito: [alchemy.com](https://alchemy.com) → crie app → Ethereum Sepolia.

Para ETH de teste: [sepolia-faucet.pk910.de](https://sepolia-faucet.pk910.de)

---

## Uso

```bash
npm run compile        # compila os .sol
npm test               # 14 testes em blockchain local
npm run deploy:local   # deploy local para explorar
npm run deploy:sepolia # deploy na testnet
npm run deploy:mainnet # deploy em produção
```

Após o deploy, atualizar o `dapp.py`:
```python
CCT_FACTORY_ADDR = "0xfA4150eFd8a152a48B9332F68EA2589933FcBA1B"
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
