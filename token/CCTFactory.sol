// SPDX-License-Identifier: UNLICENSED
// Copyright (c) 2026 CarbonChain. All rights reserved.
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/Ownable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "./CCTSoil.sol";
import "./CCTRedd.sol";
import "./CCTArr.sol";

/**
 * @title CCTFactory
 * @notice Recebe Vouchers do Cartesi Rollup e minta os três tokens CCT.
 *
 * Fluxo:
 *   1. Pipeline MRV roda on-chain no Cartesi (dapp.py)
 *   2. dapp.py emite Voucher: mintFromVoucher(cpa_id, periodo, hash_mrv, vcus_*)
 *   3. Após período de disputa, Voucher é executado → chama esta função
 *   4. CCTFactory minta CCT-SOIL, CCT-REDD e CCT-ARR separadamente
 *   5. Tokens aparecem na carteira com símbolos distintos — sem ambiguidade
 *
 * Segurança:
 *   - Somente o Cartesi Rollup pode chamar mintFromVoucher()
 *   - Cada par (cpa_id + periodo) só pode ser mintado uma vez
 *   - Hash MRV auditável — vincula o mint ao cálculo on-chain
 */
contract CCTFactory is Ownable, ReentrancyGuard {

    // ── Tokens ─────────────────────────────────────────────────────────────────
    CCTSoil public immutable cctSoil;
    CCTRedd public immutable cctRedd;
    CCTArr  public immutable cctArr;

    // ── Endereços autorizados ──────────────────────────────────────────────────
    address public cartesiRollup;  // único autorizado a chamar mintFromVoucher
    address public tesouraria;     // recebe os tokens mintados

    // ── Controle de double-mint ────────────────────────────────────────────────
    mapping(bytes32 => bool) public mintRealizado;

    // ── Estatísticas ───────────────────────────────────────────────────────────
    uint256 public totalMints;
    uint256 public totalVCUsMintados;

    // ── Eventos ────────────────────────────────────────────────────────────────
    event MintRealizado(
        string  indexed cpa_id,
        string  periodo,
        bytes32 hash_mrv,
        uint256 vcus_soil,
        uint256 vcus_redd,
        uint256 vcus_arr
    );
    event CartesiRollupAtualizado(address indexed anterior, address indexed novo);
    event TesourariaAtualizada(address indexed anterior, address indexed nova);

    // ── Modifier ───────────────────────────────────────────────────────────────
    modifier apenasCartesi() {
        require(msg.sender == cartesiRollup, "CCTFactory: somente Cartesi Rollup");
        _;
    }

    // ── Constructor ────────────────────────────────────────────────────────────
    constructor(
        address _cctSoil,
        address _cctRedd,
        address _cctArr,
        address _cartesiRollup,
        address _tesouraria
    ) Ownable(msg.sender) {
        require(_cctSoil       != address(0), "CCTFactory: soil zero");
        require(_cctRedd       != address(0), "CCTFactory: redd zero");
        require(_cctArr        != address(0), "CCTFactory: arr zero");
        require(_cartesiRollup != address(0), "CCTFactory: rollup zero");
        require(_tesouraria    != address(0), "CCTFactory: tesouraria zero");

        cctSoil       = CCTSoil(_cctSoil);
        cctRedd       = CCTRedd(_cctRedd);
        cctArr        = CCTArr(_cctArr);
        cartesiRollup = _cartesiRollup;
        tesouraria    = _tesouraria;
    }

    // ── Mint via Voucher ───────────────────────────────────────────────────────
    /**
     * @notice Executado pelo Cartesi Rollup após verificação do cálculo MRV.
     * Minta os três tipos de crédito separadamente — cada um no seu contrato ERC-20.
     *
     * @param cpa_id     Fazenda (ex: "CPA-GO-001")
     * @param periodo    Ciclo (ex: "2025-ciclo-1")
     * @param hash_mrv   Hash SHA-256 do cálculo on-chain — auditável no Cartesi
     * @param vcus_soil  Créditos CCT-SOIL a mintar
     * @param vcus_redd  Créditos CCT-REDD a mintar
     * @param vcus_arr   Créditos CCT-ARR a mintar
     */
    function mintFromVoucher(
        string  calldata cpa_id,
        string  calldata periodo,
        bytes32          hash_mrv,
        uint256          vcus_soil,
        uint256          vcus_redd,
        uint256          vcus_arr
    ) external apenasCartesi nonReentrant {
        require(vcus_soil + vcus_redd + vcus_arr > 0, "CCTFactory: zero VCUs");
        require(bytes(cpa_id).length > 0,             "CCTFactory: cpa_id vazio");
        require(bytes(periodo).length > 0,            "CCTFactory: periodo vazio");
        require(hash_mrv != bytes32(0),               "CCTFactory: hash vazio");

        bytes32 lote_id = keccak256(abi.encodePacked(cpa_id, periodo));
        require(!mintRealizado[lote_id], "CCTFactory: lote ja mintado");
        mintRealizado[lote_id] = true;

        // Minta cada token no seu contrato — aparecem separados na carteira
        if (vcus_soil > 0) cctSoil.mintLote(tesouraria, cpa_id, periodo, hash_mrv, vcus_soil);
        if (vcus_redd > 0) cctRedd.mintLote(tesouraria, cpa_id, periodo, hash_mrv, vcus_redd);
        if (vcus_arr  > 0) cctArr.mintLote( tesouraria, cpa_id, periodo, hash_mrv, vcus_arr);

        totalMints++;
        totalVCUsMintados += vcus_soil + vcus_redd + vcus_arr;

        emit MintRealizado(cpa_id, periodo, hash_mrv, vcus_soil, vcus_redd, vcus_arr);
    }

    // ── Admin ──────────────────────────────────────────────────────────────────
    function setCartesiRollup(address novo) external onlyOwner {
        require(novo != address(0), "CCTFactory: zero");
        emit CartesiRollupAtualizado(cartesiRollup, novo);
        cartesiRollup = novo;
    }

    function setTesouraria(address nova) external onlyOwner {
        require(nova != address(0), "CCTFactory: zero");
        emit TesourariaAtualizada(tesouraria, nova);
        tesouraria = nova;
    }

    // ── Views ──────────────────────────────────────────────────────────────────
    function loteJaMintado(string calldata cpa_id, string calldata periodo)
        external view returns (bool)
    {
        return mintRealizado[keccak256(abi.encodePacked(cpa_id, periodo))];
    }

    function saldoTesouraria()
        external view
        returns (uint256 soil, uint256 redd, uint256 arr)
    {
        soil = cctSoil.balanceOf(tesouraria) / 1e18;
        redd = cctRedd.balanceOf(tesouraria) / 1e18;
        arr  = cctArr.balanceOf(tesouraria)  / 1e18;
    }
}
