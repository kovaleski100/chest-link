# Compatibilidade dos bancos

Implementação independente a partir dos formatos usados nos projetos Pokémon Chest e PKSM. O app copia os registros opacos; não usa PKSM-Core para transformar ou validar legalidade dos Pokémon.

## PKSMBANK

| Versão | Cabeçalho | Registro | Quantidade de boxes |
|---|---:|---:|---|
| 1 | 12 bytes | 264 bytes | Derivada do tamanho do arquivo |
| 2 | 16 bytes | 264 bytes | Campo little endian em offset 12 |
| 3 | 16 bytes | 336 bytes (`0x150`) | Campo little endian em offset 12 |

O cabeçalho começa por `PKSMBANK` (8 bytes), seguido da versão (4 bytes). Há 30 registros por box. O leitor rejeita arquivos truncados, dados excedentes, versões futuras e divergência entre a quantidade do arquivo e do cadastro.

No registro v3, os primeiros quatro bytes são o ID da geração; há 328 bytes de dados e quatro bytes de padding. Um slot vazio usa geração `0xffffffff`. Para v1/v2, os primeiros 264 bytes são mantidos e os bytes adicionais são preenchidos com `0xff`, seguindo a migração do formato.

## IDs de geração

Estes valores são IDs de **armazenamento**, não o número normal da geração:

| ID | Geração |
|---:|---|
| 0 | 4 — inclui SoulSilver |
| 1 | 5 |
| 2 | 6 |
| 3 | 7 |
| 4 | Let's Go Pikachu/Eevee |
| 5 | 8 |
| 6 | 3 — inclui Emerald |
| 7 | 1 |
| 8 | 2 |
| `0xffffffff` | Slot vazio |

O destino Chest aceita IDs 0–6 nesta versão; o destino PKSM aceita 0–8. IDs futuros são recusados. Não se altera o ID para converter o registro: mudar só esse campo corromperia sua interpretação.

## Arquivos relacionados

`banks/{nome}.bnk` contém os registros; `banks/{nome}.json` contém o array de nomes das boxes; **`banks.json`**, no nível acima da pasta de bancos, contém o objeto `{nome: quantidade_de_boxes}`.

O cadastro precisa corresponder ao tamanho do banco. O Chest pode redimensionar o banco para a contagem do cadastro durante o carregamento. Por isso, a importação registra a contagem exata depois de conferir os arquivos.

Raízes acessadas:

- Chest: `sd:/_nds/pkmn-chest` ou `fat:/_nds/pkmn-chest`, conforme o dispositivo.
- PKSM no SD: `sdmc:/3ds/PKSM`.
- PKSM em ExtData: arquivo SD com ID `0xEC100`, montado virtualmente como `pksm:` pelo app 3DS.

## Fontes primárias consultadas

- [Chest v2.2 — Bank.hpp](https://github.com/Universal-Team/pkmn-chest/blob/v2.2/arm9/include/utils/Bank.hpp) e [Bank.cpp](https://github.com/Universal-Team/pkmn-chest/blob/v2.2/arm9/source/utils/Bank.cpp).
- [Chest v2.2 — cadastro dos bancos](https://github.com/Universal-Team/pkmn-chest/blob/v2.2/arm9/source/utils/banks.cpp).
- [PKSM — BankFile.hpp](https://github.com/FlagBrew/PKSM/blob/master/common/include/BankFile.hpp) e [BankFile.cpp](https://github.com/FlagBrew/PKSM/blob/master/common/source/BankFile.cpp).
- [PKSM 10.4.1 — Archive.cpp](https://github.com/FlagBrew/PKSM/blob/10.4.1/3ds/source/io/Archive.cpp) e [Makefile com ExtData ID](https://github.com/FlagBrew/PKSM/blob/10.4.1/3ds/Makefile).
- [PKSM-Core — IDs de geração](https://github.com/FlagBrew/PKSM-Core/blob/master/include/enums/Generation.hpp).
- [libctru — driver de arquivos](https://github.com/devkitPro/libctru/blob/master/libctru/source/archive_dev.c).
- [BlocksDS/DSWiFi — modo de rede](https://blocksds.skylyrac.net/dswifi/md_documentation_2internet__mode.html).
