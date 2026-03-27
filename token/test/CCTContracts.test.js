/**
 * test/CCTContracts.test.js
 * Testes automáticos para CCTSoil, CCTRedd, CCTArr e CCTFactory.
 *
 * Uso:
 *   npm test
 *
 * Roda em blockchain local — gratuito, sem internet, resultado imediato.
 */

const { expect }  = require("chai");
const { ethers }  = require("hardhat");

describe("CarbonChain — Contratos CCT-*", function () {

  let deployer, tesouraria, comprador;
  let cctSoil, cctRedd, cctArr, cctFactory;
  let MINTER_ROLE;

  const CPA_ID  = "CPA-GO-001";
  const PERIODO = "2025-ciclo-1";
  const HASH_MRV = ethers.keccak256(ethers.toUtf8Bytes("hash_teste_mrv"));

  beforeEach(async function () {
    [deployer, tesouraria, comprador] = await ethers.getSigners();
    MINTER_ROLE = ethers.keccak256(ethers.toUtf8Bytes("MINTER_ROLE"));

    // Deploy dos tokens
    const CCTSoil = await ethers.getContractFactory("CCTSoil");
    cctSoil = await CCTSoil.deploy(deployer.address);

    const CCTRedd = await ethers.getContractFactory("CCTRedd");
    cctRedd = await CCTRedd.deploy(deployer.address);

    const CCTArr = await ethers.getContractFactory("CCTArr");
    cctArr = await CCTArr.deploy(deployer.address);

    // Deploy do Factory (usa deployer como Cartesi para testes)
    const CCTFactory = await ethers.getContractFactory("CCTFactory");
    cctFactory = await CCTFactory.deploy(
      await cctSoil.getAddress(),
      await cctRedd.getAddress(),
      await cctArr.getAddress(),
      deployer.address,        // simula Cartesi Rollup
      tesouraria.address
    );

    // Concede MINTER_ROLE ao Factory
    await cctSoil.grantRole(MINTER_ROLE, await cctFactory.getAddress());
    await cctRedd.grantRole(MINTER_ROLE, await cctFactory.getAddress());
    await cctArr.grantRole(MINTER_ROLE, await cctFactory.getAddress());
  });

  // ── Tokens individuais ──────────────────────────────────────────────────────

  describe("CCTSoil", function () {
    it("tem símbolo e nome corretos", async function () {
      expect(await cctSoil.symbol()).to.equal("CCT-SOIL");
      expect(await cctSoil.name()).to.equal("CarbonChain Soil Credit");
    });

    it("não permite mint sem MINTER_ROLE", async function () {
      await expect(
        cctSoil.connect(comprador).mintLote(
          comprador.address, CPA_ID, PERIODO, HASH_MRV, 100
        )
      ).to.be.reverted;
    });
  });

  describe("CCTRedd", function () {
    it("tem símbolo e nome corretos", async function () {
      expect(await cctRedd.symbol()).to.equal("CCT-REDD");
      expect(await cctRedd.name()).to.equal("CarbonChain REDD+ Credit");
    });

    it("não permite mint sem MINTER_ROLE", async function () {
      await expect(
        cctRedd.connect(comprador).mintLote(
          comprador.address, CPA_ID, PERIODO, HASH_MRV, 100
        )
      ).to.be.reverted;
    });
  });

  describe("CCTArr", function () {
    it("tem símbolo e nome corretos", async function () {
      expect(await cctArr.symbol()).to.equal("CCT-ARR");
      expect(await cctArr.name()).to.equal("CarbonChain ARR Credit");
    });

    it("não permite mint sem MINTER_ROLE", async function () {
      await expect(
        cctArr.connect(comprador).mintLote(
          comprador.address, CPA_ID, PERIODO, HASH_MRV, 100
        )
      ).to.be.reverted;
    });
  });

  // ── CCTFactory ─────────────────────────────────────────────────────────────

  describe("CCTFactory — mint via Voucher", function () {
    it("minta os três tokens corretamente", async function () {
      await cctFactory.mintFromVoucher(
        CPA_ID, PERIODO, HASH_MRV,
        100,  // CCT-SOIL
        50,   // CCT-REDD
        10    // CCT-ARR
      );

      // Verifica saldo na tesouraria (em unidades, não wei)
      const soilBal = await cctSoil.balanceOf(tesouraria.address);
      const reddBal = await cctRedd.balanceOf(tesouraria.address);
      const arrBal  = await cctArr.balanceOf(tesouraria.address);

      expect(soilBal).to.equal(100n * 10n**18n);
      expect(reddBal).to.equal(50n  * 10n**18n);
      expect(arrBal).to.equal(10n  * 10n**18n);
    });

    it("impede double-mint do mesmo lote", async function () {
      await cctFactory.mintFromVoucher(CPA_ID, PERIODO, HASH_MRV, 100, 50, 10);

      await expect(
        cctFactory.mintFromVoucher(CPA_ID, PERIODO, HASH_MRV, 100, 50, 10)
      ).to.be.revertedWith("CCTFactory: lote ja mintado");
    });

    it("impede mint por endereço não autorizado", async function () {
      await expect(
        cctFactory.connect(comprador).mintFromVoucher(
          CPA_ID, PERIODO, HASH_MRV, 100, 50, 10
        )
      ).to.be.revertedWith("CCTFactory: somente Cartesi Rollup");
    });

    it("permite lotes diferentes do mesmo CPA", async function () {
      await cctFactory.mintFromVoucher(CPA_ID, "2025-ciclo-1", HASH_MRV, 100, 50, 10);
      await cctFactory.mintFromVoucher(CPA_ID, "2025-ciclo-2", HASH_MRV, 120, 60, 12);

      const soilBal = await cctSoil.balanceOf(tesouraria.address);
      expect(soilBal).to.equal(220n * 10n**18n);
    });

    it("emite evento MintRealizado", async function () {
      await expect(
        cctFactory.mintFromVoucher(CPA_ID, PERIODO, HASH_MRV, 100, 50, 10)
      ).to.emit(cctFactory, "MintRealizado")
        .withArgs(CPA_ID, PERIODO, HASH_MRV, 100, 50, 10);
    });
  });

  // ── Aposentadoria (retire) ──────────────────────────────────────────────────

  describe("Aposentadoria de créditos", function () {
    beforeEach(async function () {
      // Minta créditos e transfere alguns para o comprador
      await cctFactory.mintFromVoucher(CPA_ID, PERIODO, HASH_MRV, 100, 50, 10);
      await cctSoil.connect(tesouraria).transfer(
        comprador.address, 10n * 10n**18n
      );
    });

    it("comprador consegue aposentar créditos SOIL", async function () {
      await expect(
        cctSoil.connect(comprador).retire(
          5, "Neutralização emissões 2025 — Empresa Teste"
        )
      ).to.emit(cctSoil, "CreditoAposentado");

      // Saldo reduzido
      const bal = await cctSoil.balanceOf(comprador.address);
      expect(bal).to.equal(5n * 10n**18n);

      // Total aposentado atualizado
      expect(await cctSoil.totalAposentado()).to.equal(5);
    });

    it("não permite aposentar mais do que o saldo", async function () {
      await expect(
        cctSoil.connect(comprador).retire(
          999, "tentativa inválida"
        )
      ).to.be.revertedWith("CCT-SOIL: saldo insuficiente");
    });
  });

  // ── saldoTesouraria ─────────────────────────────────────────────────────────

  describe("saldoTesouraria", function () {
    it("retorna saldos corretos após mint", async function () {
      await cctFactory.mintFromVoucher(CPA_ID, PERIODO, HASH_MRV, 100, 50, 10);
      const [soil, redd, arr] = await cctFactory.saldoTesouraria();
      expect(soil).to.equal(100);
      expect(redd).to.equal(50);
      expect(arr).to.equal(10);
    });
  });
});
