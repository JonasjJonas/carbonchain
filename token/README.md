# CarbonChain — Smart Contracts (token/)

Três contratos ERC-20 independentes para emissão e aposentadoria dos Carbon Credit Tokens.

---

## Contratos

| Arquivo | Símbolo | Metodologia | Escopo |
|---|---|---|---|
| `CCTSoil.sol` | **CCT-SOIL** | VM0042 v2.2 | Solo agrícola |
| `CCTRedd.sol` | **CCT-REDD** | VM0015 | Reserva Legal / REDD+ |
| `CCTArr.sol` | **CCT-ARR** | VM0047 | Restauração / reflorestamento |
| `CCTFactory.sol` | — | — | Gateway Cartesi → mint |

1 token = 1 tCO₂e certificado pela Verra.

Cada token tem seu próprio endereço de contrato e símbolo — aparecem separados em qualquer carteira (MetaMask, etc.) sem ambiguidade.

---

## Fluxo completo

```
Pipeline MRV (satellite.py + nir_model.py + mrv_calculator.py)
         ↓
   dapp.py (Cartesi Rollup)
   → cálculo on-chain + hash SHA-256 auditável
   → Voucher: mintFromVoucher(cpa_id, periodo, hash_mrv, vcus_soil, vcus_redd, vcus_arr)
         ↓
   CCTFactory.mintFromVoucher()
   → valida hash e previne double-mint
   → CCTSoil.mintLote()   →  CCT-SOIL na tesouraria
   → CCTRedd.mintLote()   →  CCT-REDD na tesouraria
   → CCTArr.mintLote()    →  CCT-ARR  na tesouraria
         ↓
   Venda no mercado voluntário
   → 80% produtor rural
   → 20% CarbonChain
         ↓
   Comprador chama retire(quantidade, motivo)
   → tokens queimados permanentemente
   → aposentadoria gravada on-chain
```

---

## Deploy

```bash
# 1. Instalar dependências
npm install --save-dev hardhat @openzeppelin/contracts

# 2. Deploy dos três tokens (ordem qualquer)
npx hardhat run scripts/deploy_tokens.js --network <rede>
# guarde os três endereços retornados

# 3. Deploy do CCTFactory
# Parâmetros:
#   _cctSoil       = endereço CCTSoil
#   _cctRedd       = endereço CCTRedd
#   _cctArr        = endereço CCTArr
#   _cartesiRollup = endereço do CartesiDApp na mesma rede
#   _tesouraria    = endereço multisig da CarbonChain
npx hardhat run scripts/deploy_factory.js --network <rede>

# 4. Conceder MINTER_ROLE ao CCTFactory nos três tokens
CCTSoil.grantRole(MINTER_ROLE, endereço_CCTFactory)
CCTRedd.grantRole(MINTER_ROLE, endereço_CCTFactory)
CCTArr.grantRole(MINTER_ROLE, endereço_CCTFactory)

# 5. Atualizar CCT_FACTORY_ADDR no dapp.py com o endereço deployado
```

---

## Segurança

- `mintFromVoucher()` — somente o endereço do Cartesi Rollup pode chamar
- Double-mint — cada par `(cpa_id + periodo)` só pode ser mintado uma vez
- Hash MRV — cada lote registra o hash do cálculo on-chain, auditável no Cartesi
- `retire()` — queima permanente, impossível reverter

---

## Dependências

```json
{
  "@openzeppelin/contracts": "^5.0.0"
}
```
