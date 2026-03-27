require("@nomicfoundation/hardhat-toolbox");
require("dotenv").config();

/**
 * Hardhat — CarbonChain Token Contracts
 *
 * Redes configuradas:
 *   localhost  — blockchain local para testes (gratuita, sem internet)
 *   sepolia    — testnet Ethereum (ETH de teste gratuito)
 *   mainnet    — Ethereum mainnet (deploy final, ETH real)
 *
 * Variáveis de ambiente necessárias (.env na pasta token/):
 *   PRIVATE_KEY     — chave privada da carteira de deploy
 *   SEPOLIA_RPC_URL — endpoint RPC da Sepolia (ex: Alchemy ou Infura)
 *   ETHERSCAN_API_KEY — para verificar contratos no Etherscan (opcional)
 */

const PRIVATE_KEY    = process.env.PRIVATE_KEY    || "0x" + "0".repeat(64);
const SEPOLIA_RPC    = process.env.SEPOLIA_RPC_URL || "https://rpc.sepolia.org";
const ETHERSCAN_KEY  = process.env.ETHERSCAN_API_KEY || "";

module.exports = {
  solidity: {
    version: "0.8.20",
    settings: {
      optimizer: { enabled: true, runs: 200 },
    },
  },

  networks: {
    // Blockchain local — para rodar testes sem internet
    localhost: {
      url: "http://127.0.0.1:8545",
    },

    // Testnet Ethereum — deploy de teste gratuito
    sepolia: {
      url: SEPOLIA_RPC,
      accounts: [PRIVATE_KEY],
      chainId: 11155111,
    },

    // Mainnet — apenas quando tudo estiver validado na testnet
    mainnet: {
      url: process.env.MAINNET_RPC_URL || "https://eth.llamarpc.com",
      accounts: [PRIVATE_KEY],
      chainId: 1,
    },
  },

  etherscan: {
    apiKey: ETHERSCAN_KEY,
  },

  paths: {
    sources:   "./contracts",
    tests:     "./test",
    cache:     "./cache",
    artifacts: "./artifacts",
  },
};
