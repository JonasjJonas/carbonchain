# CarbonChain — Guia de Tokens e Transações

Este documento explica como os Carbon Credit Tokens (CCT-*) funcionam na prática — tanto para equipes técnicas quanto para compradores corporativos tradicionais.

---

## O que é um CCT-*

Um Carbon Credit Token é um certificado digital de carbono gravado na blockchain. Cada token representa 1 tCO₂e verificado e certificado pela Verra, com todas as informações do cálculo MRV auditáveis publicamente.

Diferente de um PDF ou número em planilha, um token na blockchain:
- Não pode ser falsificado ou editado por ninguém
- É verificável por qualquer pessoa no mundo, a qualquer momento
- Transfere de titular automaticamente, sem intermediários
- Quando aposentado (retired), o registro é permanente e público

---

## Os três tipos de crédito

| Token | Origem | Preço referência |
|---|---|---|
| **CCT-SOIL** | Solo agrícola — VM0042 | ~USD 9/tCO₂e |
| **CCT-REDD** | Reserva Legal preservada — VM0015 | ~USD 54/tCO₂e |
| **CCT-ARR** | Restauração e reflorestamento — VM0047 | ~USD 76/tCO₂e |

Cada tipo tem seu próprio contrato na blockchain — aparecem separados em qualquer carteira ou plataforma, sem possibilidade de confusão.

---

## Fluxo para empresas tradicionais (sem conhecimento em blockchain)

A CarbonChain abstrai toda a complexidade técnica. O comprador corporativo não precisa instalar nenhum software, criar carteiras ou comprar ETH.

```
1. Empresa solicita créditos (ex: 500 tCO₂e CCT-SOIL)
         ↓
2. Negociação e contrato fora da blockchain
         ↓
3. Pagamento via PIX, TED ou wire transfer em reais/dólares
         ↓
4. CarbonChain executa a transferência on-chain
   (paga o gas — custo de ~R$ 2,50 por operação)
         ↓
5. Empresa recebe:
   - Certificado PDF com QR code
   - Link do Etherscan para verificação pública
   - Hash da transação como comprovante imutável
         ↓
6. Para neutralização: CarbonChain executa o retire()
   em nome da empresa, com a declaração de uso gravada
   permanentemente na blockchain
```

A empresa nunca precisa saber que existe blockchain — ela compra créditos e recebe um certificado verificável.

---

## O que é gas e quem paga

Gas é a taxa de processamento cobrada pela rede Ethereum para executar qualquer operação na blockchain. É cobrado em ETH e é muito barato:

| Operação | Custo estimado em gas |
|---|---|
| Transferir tokens | ~USD 0,10 |
| Aposentar créditos (retire) | ~USD 0,20 |
| Deploy de contrato | ~USD 5,00 (único) |

Para compradores corporativos, a CarbonChain absorve esse custo e inclui no preço do crédito — o comprador nunca precisa comprar ETH.

Para compradores que preferem custódia própria (grandes instituições, fundos), a CarbonChain pode transferir os tokens para a carteira do comprador e ele mesmo executa o retire quando quiser.

---

## Dois modelos de custódia

### Modelo custodial (padrão para empresas tradicionais)
A CarbonChain mantém os tokens em nome do cliente. O cliente recebe um certificado e pode verificar os créditos no Etherscan a qualquer momento. A CarbonChain executa todas as operações on-chain.

**Vantagem:** zero fricção para o comprador — processo idêntico a comprar qualquer outro produto.

### Modelo auto-custodial (para clientes avançados)
O cliente tem sua própria carteira (MetaMask, Ledger, etc.) e recebe os tokens diretamente. Ele controla a transferência e o retire.

**Vantagem:** soberania total — a CarbonChain não pode reter ou mover os tokens.

---

## O que é uma carteira (wallet)

Uma carteira blockchain é um endereço único — como um número de conta bancária — onde os tokens ficam armazenados. Exemplo:

```
0xc9e3f6838a9c8147D48AC53eA95250B9473ae7Fd
```

Qualquer pessoa pode ver o saldo de qualquer endereço publicamente no Etherscan. Ninguém pode mover os tokens de uma carteira sem a chave privada do titular.

---

## O que é retire (aposentadoria)

Retire é o ato de queimar o token para comprovar neutralização de emissões. Quando uma empresa chama `retire()`, acontece:

1. Os tokens são destruídos permanentemente
2. Uma declaração de uso é gravada on-chain (ex: "Neutralização emissões 2025 — Empresa XYZ")
3. O registro fica público para sempre — qualquer auditor pode verificar

Isso é diferente de vender o crédito para outra empresa. Uma vez aposentado, o crédito não pode ser transferido nem usado novamente.

---

## Verificação pública

Qualquer operação pode ser verificada em:

**[sepolia.etherscan.io](https://sepolia.etherscan.io)** (testnet atual)

**[etherscan.io](https://etherscan.io)** (mainnet — após go-live)

Exemplos de consulta:
- Ver todos os tokens emitidos para uma fazenda: buscar pelo endereço da tesouraria
- Verificar um lote específico: buscar pelo hash MRV gravado no contrato
- Confirmar aposentadoria de créditos: ver eventos `CreditoAposentado` no contrato

---

## Sepolia vs Mainnet

| | Sepolia (atual) | Mainnet (produção) |
|---|---|---|
| ETH tem valor real | Não | Sim |
| Transações são reais | Sim | Sim |
| Verificável publicamente | Sim | Sim |
| Custo de operação | Gratuito | ~USD 0,10–0,20 |
| Uso | Desenvolvimento e testes | Clientes reais |

Os contratos atuais na Sepolia validam toda a lógica de negócio. O deploy na Mainnet é o mesmo processo com `--network mainnet`.

---

## Endereços dos contratos (Sepolia)

```
CCTSoil    → 0xB01fB4d36d78aFddaF4D35D6D97e5a84734e22b4
CCTRedd    → 0x5D5dA00f1d58084CaDdFfb4321EcD19aE257C3C8
CCTArr     → 0x1d65651c9120845eb81245493b184F5E86A0fb7B
CCTFactory → 0xfA4150eFd8a152a48B9332F68EA2589933FcBA1B
```
