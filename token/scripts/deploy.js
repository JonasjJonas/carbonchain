/**
 * scripts/deploy.js
 * Deploy dos contratos CCT-SOIL, CCT-REDD, CCT-ARR e CCTFactory.
 *
 * Ordem obrigatória:
 *   1. Deploy CCTSoil
 *   2. Deploy CCTRedd
 *   3. Deploy CCTArr
 *   4. Deploy CCTFactory (precisa dos 3 endereços acima)
 *   5. Conceder MINTER_ROLE ao CCTFactory nos 3 tokens
 *
 * Uso:
 *   npm run deploy:local    — blockchain local (testes)
 *   npm run deploy:sepolia  — testnet Ethereum (validação)
 *   npm run deploy:mainnet  — produção (só após validação)
 */

const hre = require("hardhat");

async function main() {
  const [deployer] = await hre.ethers.getSigners();
  const network = hre.network.name;

  console.log("\n==============================================");
  console.log("  CarbonChain — Deploy dos Contratos CCT-*");
  console.log(`  Rede:      ${network}`);
  console.log(`  Deployer:  ${deployer.address}`);
  console.log("==============================================\n");

  // ── 1. Deploy CCTSoil ──────────────────────────────────────────────────────
  console.log("📦 Deployando CCTSoil (CCT-SOIL | VM0042)...");
  const CCTSoil = await hre.ethers.getContractFactory("CCTSoil");
  const cctSoil = await CCTSoil.deploy(deployer.address);
  await cctSoil.waitForDeployment();
  const soilAddr = await cctSoil.getAddress();
  console.log(`   ✅ CCTSoil: ${soilAddr}`);

  // ── 2. Deploy CCTRedd ──────────────────────────────────────────────────────
  console.log("📦 Deployando CCTRedd (CCT-REDD | VM0015)...");
  const CCTRedd = await hre.ethers.getContractFactory("CCTRedd");
  const cctRedd = await CCTRedd.deploy(deployer.address);
  await cctRedd.waitForDeployment();
  const reddAddr = await cctRedd.getAddress();
  console.log(`   ✅ CCTRedd: ${reddAddr}`);

  // ── 3. Deploy CCTArr ───────────────────────────────────────────────────────
  console.log("📦 Deployando CCTArr (CCT-ARR | VM0047)...");
  const CCTArr = await hre.ethers.getContractFactory("CCTArr");
  const cctArr = await CCTArr.deploy(deployer.address);
  await cctArr.waitForDeployment();
  const arrAddr = await cctArr.getAddress();
  console.log(`   ✅ CCTArr: ${arrAddr}`);

  // ── 4. Deploy CCTFactory ───────────────────────────────────────────────────
  // Na testnet/mainnet: substituir CARTESI_ROLLUP pelo endereço real do CartesiDApp
  // Na rede local: usa o deployer como placeholder para testes
  const CARTESI_ROLLUP = process.env.CARTESI_ROLLUP_ADDR || deployer.address;
  const TESOURARIA     = process.env.TESOURARIA_ADDR     || deployer.address;

  console.log("📦 Deployando CCTFactory...");
  console.log(`   Cartesi Rollup: ${CARTESI_ROLLUP}`);
  console.log(`   Tesouraria:     ${TESOURARIA}`);

  const CCTFactory = await hre.ethers.getContractFactory("CCTFactory");
  const cctFactory = await CCTFactory.deploy(
    soilAddr,
    reddAddr,
    arrAddr,
    CARTESI_ROLLUP,
    TESOURARIA
  );
  await cctFactory.waitForDeployment();
  const factoryAddr = await cctFactory.getAddress();
  console.log(`   ✅ CCTFactory: ${factoryAddr}`);

  // ── 5. Conceder MINTER_ROLE ao CCTFactory ──────────────────────────────────
  console.log("\n🔑 Concedendo MINTER_ROLE ao CCTFactory...");
  const MINTER_ROLE = hre.ethers.keccak256(hre.ethers.toUtf8Bytes("MINTER_ROLE"));

  await (await cctSoil.grantRole(MINTER_ROLE, factoryAddr)).wait();
  console.log("   ✅ CCTSoil → CCTFactory: MINTER_ROLE concedido");

  await (await cctRedd.grantRole(MINTER_ROLE, factoryAddr)).wait();
  console.log("   ✅ CCTRedd → CCTFactory: MINTER_ROLE concedido");

  await (await cctArr.grantRole(MINTER_ROLE, factoryAddr)).wait();
  console.log("   ✅ CCTArr  → CCTFactory: MINTER_ROLE concedido");

  // ── Resumo final ───────────────────────────────────────────────────────────
  const enderecos = {
    rede:        network,
    CCTSoil:     soilAddr,
    CCTRedd:     reddAddr,
    CCTArr:      arrAddr,
    CCTFactory:  factoryAddr,
    deployer:    deployer.address,
    timestamp:   new Date().toISOString(),
  };

  console.log("\n==============================================");
  console.log("  Deploy concluído!");
  console.log("==============================================");
  console.log(JSON.stringify(enderecos, null, 2));
  console.log("\n⚠️  Guarde esses endereços e atualize o dapp.py:");
  console.log(`   CCT_FACTORY_ADDR = "${factoryAddr}"`);
  console.log("==============================================\n");

  // Salva endereços em arquivo para referência
  const fs = require("fs");
  const path = require("path");
  const outDir = path.join(__dirname, "..", "deployments");
  fs.mkdirSync(outDir, { recursive: true });
  fs.writeFileSync(
    path.join(outDir, `${network}.json`),
    JSON.stringify(enderecos, null, 2)
  );
  console.log(`📄 Endereços salvos em: deployments/${network}.json`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
