# Projetos e dependências

Chest Link é um app independente. O código de leitura dos bancos, protocolos, servidor da caixa postal, JSON, SHA-256 e adaptador ExtData foi escrito para este projeto. A interface de armazenamento foi adaptada do visual do PKSM; o resumo dos registros usa rotinas e tabelas derivadas de PKSM-Core. Pokémon Chest, PKSM, PKSM-Core e Checkpoint não foram modificados.

## Interface, dados e arte

- **PKSM / FlagBrew:** recursos `bg_*_greyscale`, `bg_style_*`, `bar_arc_*_green`, `bar_boxname_with_arrows`, `button_editor`, `button_back`, `button_wireless_no_y` e `pointer_arrow`, além da organização da tela de armazenamento. Copyright © 2016–2022 Bernardo Giordano, Admiral Fish, piepie62 e contribuidores. Recursos conferidos na revisão `9e18c8068ede315f73a99f4c834819630393b5c5` do [código original](https://github.com/FlagBrew/PKSM). Modificações: fundos compostos com a coloração verde de armazenamento, fonte alternativa, resumo simplificado e controles de cópia/caixa postal, com adaptação à resolução do DS. A marca Chest Link identifica a versão adaptada.
- **PKSM-Core:** tabelas de espécies das gerações I/III, nomes das espécies e descrição/rotinas dos blocos dos registros PK1/2/3/4/5/6/8/PB7, usadas em `catalog.hpp`, `pokemon.cpp` e `server/pokemon.py`. Copyright © 2016–2022 Bernardo Giordano, Admiral Fish, piepie62. [Fontes](https://github.com/FlagBrew/PKSM-Core). Modificações: leitores pequenos e somente de consulta, sem edição de registros ou dependências do editor completo.
- PKSM e PKSM-Core usam **GPL-3.0-or-later** com termos adicionais de seção **7(b) e 7(c)**: preservar avisos legais/atribuição e não representar material modificado como se fosse o original. Esses avisos são preservados nos arquivos derivados, neste documento e nos créditos dos apps. O texto da GPL está em `LICENSE`.
- **Ícones Pokémon:** [PokeAPI/sprites](https://github.com/PokeAPI/sprites), revisão `961f4fcc85b159f9c5fff356356dee1bf9069898`, diretórios `generation-vii/icons` e `generation-viii/icons`. Os ícones foram recortados/centralizados em 34 × 30 pixels; os consoles usam paletas de até 15 cores visíveis por ícone. A arte Pokémon pertence a **Nintendo, Creatures e GAME FREAK**; a licença do código não atribui a Chest Link a propriedade dessa arte. Formas básicas 1–898 e 20 ícones adicionais estão no atlas; ícones de ovo/registro desconhecido são desenhos simples feitos para este projeto. A procedência está também em `assets/pksm/provenance.json`.
- **DejaVu Sans Mono / Bitstream Vera:** fonte convertida em bitmaps para os consoles. Copyright e termos completos em `licenses/dejavu.txt`. Os bitmaps são derivados da fonte, que conserva sua licença própria.

Os formatos de bancos e IDs foram conferidos no [Pokémon Chest](https://github.com/Universal-Team/pkmn-chest), [PKSM](https://github.com/FlagBrew/PKSM) e [PKSM-Core](https://github.com/FlagBrew/PKSM-Core). Créditos desses projetos: Universal-Team, FlagBrew e seus contribuidores.

Os executáveis foram compilados com:

- [BlocksDS](https://github.com/blocksds/sdk), [libnds](https://github.com/blocksds/libnds), [DSWiFi](https://github.com/blocksds/dswifi) e [Wonderful Toolchain](https://wonderful.asie.pl/). Créditos incluem Antonio Niño Díaz, asie, Stephen Stair, Dave Murphy e os contribuidores das bibliotecas.
- [devkitARM/devkitPro](https://devkitpro.org/) e [libctru](https://github.com/devkitPro/libctru), por seus respectivos mantenedores e contribuidores.
- Os runtimes C/C++ dos SDKs, incluindo GCC, libstdc++, Picolibc/newlib, e componentes de rede como lwIP.

As bibliotecas mantêm suas próprias licenças. O SDK BlocksDS distribui componentes sob Zlib, MIT, BSD e CC0; libctru usa Zlib. Os runtimes GCC/libstdc++ incluem a GCC Runtime Library Exception. Os respectivos repositórios/SDKs contêm as licenças e fontes completas dessas dependências. `licenses/` inclui os textos genéricos distribuídos pelo SDK BlocksDS.

O servidor do PC usa somente a biblioteca padrão do Python. O runtime do Python é instalado pelo usuário e não está incluído neste pacote.

Os ícones do Chest Link foram criados para este projeto. Pokémon e nomes dos jogos pertencem aos seus titulares; este projeto não inclui ROMs, saves reais, Pokémon de usuários, credenciais ou dados de conexão privados.
