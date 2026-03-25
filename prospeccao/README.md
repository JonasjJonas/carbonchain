# CarbonChain — Pipeline de Prospecção VM0047

Script de pré-qualificação de fazendas para o mercado voluntário de carbono,
focado na metodologia **VM0047** (melhoria de práticas agrícolas em solo).

---

## O que faz

Para qualquer município brasileiro, o script:

1. Busca o código IBGE do município pelo nome (via API IBGE)
2. Baixa todos os imóveis rurais com CAR ativo (via WFS GeoServer do SICAR)
3. Filtra por área mínima configurável
4. Consulta o uso do solo de cada fazenda nos últimos 3 anos (via API MapBiomas)
5. Calcula o percentual de uso agrícola e classifica por prioridade
6. Exporta um CSV rankeado pronto para prospecção

---

## Instalação

```bash
cd prospeccao
python3 -m venv venv
source venv/bin/activate
pip install requests pandas tqdm
```

---

## Uso

```bash
# Itumbiara-GO, fazendas 200+ ha (padrão)
python3 prospectar.py --municipio "Itumbiara" --estado GO

# Rio Verde-GO, fazendas 500+ ha
python3 prospectar.py --municipio "Rio Verde" --estado GO --area-min 500

# Sorriso-MT, fazendas 1000+ ha, arquivo nomeado
python3 prospectar.py --municipio "Sorriso" --estado MT --area-min 1000 --output sorriso_mt.csv
```

---

## Output

Arquivo CSV com separador `;`, colunas:

| Coluna | Descrição |
|---|---|
| `rank` | Posição no ranking |
| `prioridade` | Classificação (ver tabela abaixo) |
| `cod_imovel` | Número do CAR |
| `area` | Área total da fazenda (ha) |
| `area_agro_media_ha` | Área agrícola média 2022–2024 (ha) |
| `pct_agro` | Percentual de uso agrícola (%) |
| `status_imovel` | Status do CAR (AT = ativo) |
| `condicao` | Situação do CAR no SICAR |
| `municipio` | Nome do município |
| `uf` | Estado |

### Classificação de prioridade

| Prioridade | Critério | O que significa |
|---|---|---|
| `PRIORIDADE_1` | 80–100% agrícola | Perfil VM0047 confirmado — abordar primeiro |
| `PRIORIDADE_2` | 60–80% agrícola | Perfil compatível — segunda rodada |
| `VERIFICAR` | 100–130% agrícola | Artefato de pixel do MapBiomas — verificar manualmente |
| `FORA_ESCOPO` | < 60% agrícola | Baixo perfil agrícola |
| `DESCARTAR` | > 130% agrícola | Provável erro de cadastro no CAR |

---

## Fontes de dados

| Fonte | O que fornece | Acesso |
|---|---|---|
| [SICAR / WFS GeoServer](https://geoserver.car.gov.br) | Imóveis rurais com CAR | Público, sem autenticação |
| [MapBiomas](https://mapbiomas.org) | Uso do solo por satélite (Landsat 30m) | Público, sem autenticação |
| [API IBGE](https://servicodados.ibge.gov.br) | Códigos de municípios | Público, sem autenticação |

---

## Posição no repositório

```
carbonchain/
└── prospeccao/
    ├── prospectar.py   ← pipeline principal
    ├── README.md       ← este arquivo
    └── .gitignore      ← exclui venv/ e *.csv do git
```

> Os arquivos CSV gerados **não são versionados** — são outputs de prospecção,
> não código. Cada rodada gera um novo arquivo local.

---

## Próximos passos

- [ ] Integrar com `mrv/satellite.py` para pré-processar imagens Sentinel-2 das fazendas qualificadas
- [ ] Adicionar filtro por tipo de cultura (cana, soja, milho)
- [ ] Suporte a múltiplos municípios em uma única rodada
