// SPDX-License-Identifier: UNLICENSED
// Copyright (c) 2026 CarbonChain. All rights reserved.
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/token/ERC20/ERC20.sol";
import "@openzeppelin/contracts/access/AccessControl.sol";

/**
 * @title CCTRedd
 * @notice CarbonChain Carbon Token — Reserva Legal REDD+
 *
 * Símbolo:      CCT-REDD
 * Metodologia:  VM0015 (Avoided Unplanned Deforestation)
 * 1 token       = 1 tCO₂e certificado pela Verra
 *
 * Mintado pelo CCTFactory após Voucher do Cartesi Rollup.
 * Aposentado (queimado) pelo comprador via retire().
 */
contract CCTRedd is ERC20, AccessControl {

    bytes32 public constant MINTER_ROLE = keccak256("MINTER_ROLE");

    struct Lote {
        string  cpa_id;
        string  periodo;
        bytes32 hash_mrv;
        string  vcu_id;
        uint256 emitido_em;
    }

    mapping(bytes32 => Lote) public lotes;
    mapping(string => bytes32[]) public lotesPorCPA;

    struct Aposentadoria {
        address titular;
        uint256 quantidade;
        string  motivo;
        uint256 aposentado_em;
    }
    Aposentadoria[] public aposentadorias;
    uint256 public totalAposentado;

    event LoteMintado(string indexed cpa_id, string periodo, bytes32 hash_mrv, uint256 quantidade);
    event CreditoAposentado(address indexed titular, uint256 quantidade, string motivo, uint256 id);

    constructor(address admin) ERC20("CarbonChain REDD+ Credit", "CCT-REDD") {
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(MINTER_ROLE, admin);
    }

    function mintLote(
        address destinatario,
        string  calldata cpa_id,
        string  calldata periodo,
        bytes32 hash_mrv,
        uint256 quantidade
    ) external onlyRole(MINTER_ROLE) {
        require(quantidade > 0, "CCT-REDD: quantidade zero");

        bytes32 lote_id = keccak256(abi.encodePacked(cpa_id, periodo));
        require(lotes[lote_id].emitido_em == 0, "CCT-REDD: lote ja mintado");

        lotes[lote_id] = Lote({
            cpa_id:     cpa_id,
            periodo:    periodo,
            hash_mrv:   hash_mrv,
            vcu_id:     "",
            emitido_em: block.timestamp
        });
        lotesPorCPA[cpa_id].push(lote_id);

        _mint(destinatario, quantidade * 1e18);
        emit LoteMintado(cpa_id, periodo, hash_mrv, quantidade);
    }

    function retire(uint256 quantidade, string calldata motivo) external {
        require(quantidade > 0, "CCT-REDD: quantidade zero");
        require(balanceOf(msg.sender) >= quantidade * 1e18, "CCT-REDD: saldo insuficiente");

        _burn(msg.sender, quantidade * 1e18);
        totalAposentado += quantidade;

        uint256 id = aposentadorias.length;
        aposentadorias.push(Aposentadoria({
            titular:       msg.sender,
            quantidade:    quantidade,
            motivo:        motivo,
            aposentado_em: block.timestamp
        }));

        emit CreditoAposentado(msg.sender, quantidade, motivo, id);
    }

    function setVcuId(bytes32 lote_id, string calldata vcu_id)
        external onlyRole(DEFAULT_ADMIN_ROLE)
    {
        require(lotes[lote_id].emitido_em > 0, "CCT-REDD: lote inexistente");
        lotes[lote_id].vcu_id = vcu_id;
    }

    function lotesDeCPA(string calldata cpa_id) external view returns (bytes32[] memory) {
        return lotesPorCPA[cpa_id];
    }

    function decimals() public pure override returns (uint8) { return 18; }

    function supportsInterface(bytes4 interfaceId)
        public view override(AccessControl)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }
}
