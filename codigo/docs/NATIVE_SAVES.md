# Native Saves

O Native Saves importa um dump de save pelo PC e lê os dados sem alterar o
arquivo escolhido. A aplicação guarda uma cópia identificada por SHA-256 e um
snapshot normalizado. O jogo é detectado pelo formato do arquivo; os seletores
de geração e jogo ficam dentro da aba Pokédex e escolhem qual save importado
consultar. Bancos PKSMBANK, Pokémon Chest, mailbox, protocolos e transferências
seguem separados desse leitor.

O app de console também tem um fluxo separado, **Ler saves Pokemon**, para
copiar boxes de arquivos `.sav` do SD/flashcard para um banco novo do Chest
Link. Esse fluxo não usa este parser do servidor e também não lê saves ativos
de cartuchos ou da memória de títulos instalados.

## Cópia de boxes `.sav` no console

No DS/DSi e no 3DS, o Chest Link procura arquivos `.sav` nos diretórios de
saves conhecidos e no armazenamento montado, aceitando somente extensões e
tamanhos dos layouts brutos Pokémon das Gerações I–IV. A estrutura e os
checksums são validados antes de um arquivo aparecer como jogo. Saves de outros
jogos e formatos de save não reconhecidos são ignorados. As boxes são
normalizadas para registros PKSM em memória; o arquivo de origem nunca é
alterado.

A tela inferior permite trocar entre os saves encontrados e suas boxes. O
usuário pode copiar um Pokémon válido para o rascunho da tela superior ou
substituí-lo pela box inteira. Ao salvar, o app cria um banco novo no Chest ou
PKSM selecionado, que depois pode ser enviado ao PC em **Consultar bancos**.
Esse fluxo não sobrescreve bancos existentes. Gerações I e II aparecem quando
o destino é PKSM no 3DS, pois o formato Chest do DS aceita Gerações III–IV.
Os formatos brutos lidos correspondem às versões já catalogadas na Pokédex
offline.

Esta leitura de arquivos no SD/flashcard não ativa leitura direta de
cartuchos. Tampouco grava Pokémon nos saves dos jogos: a escrita de save
continua fora do escopo e sem `GameSaveWriter`.

## Componentes

- `include/save_source.hpp` define a origem, seus metadados, o resultado da
  leitura e a interface `SaveSource`.
- `host/native_saves/raw_file_save_source.cpp` lê um arquivo em modo binário,
  limita a leitura a 64 MiB por padrão e calcula o SHA-256 dos bytes retornados.
- `server/native_saves.py` separa aquisição, detecção, parsers Gen I/II/III/HGSS,
  comparação, critérios de conclusão e armazenamento dos snapshots.
- `server/frlg_trainers.json` e `server/frlg_hidden_items.json` guardam nomes e
  localizações usados pelos guias da aba Miscelânea.
- `server/interface.py` expõe a API local autenticada. A interface web permite
  importar e consultar os dados sem passar por Pokémon Chest ou PKSM.
- `tests/test_native_saves.py` usa fixtures para validar offsets,
  criptografia/checksum PK3 e PK4, seleção de slots, armazenamento e comparações.

Os dados importados ficam em `native-saves/saves/`, com snapshots em
`native-saves/snapshots/` e metadados no mesmo diretório dentro da pasta de
dados do servidor. O hash identifica bytes, não a identidade real do jogador.
Uma importação repetida do mesmo hash não cria outra observação.

## Formatos suportados

O importador reconhece Red, Blue e Yellow em saves brutos de 32 KiB (`0x8000`)
e Gold, Silver e Crystal nos formatos internacionais de 32 KiB e japoneses de
64 KiB (`0x10000`). Crystal e Yellow têm marcadores estruturais próprios.
Red/Blue e Gold/Silver compartilham o mesmo formato de save; o arquivo bruto
não permite distingui-los com segurança. Nesses dois casos, a Pokédex mostra a
geração e o usuário escolhe o título no seletor dentro da própria área. As
flags capturado/visto lidas do save permanecem as mesmas para ambos.

Em Gen I/II, o parser lê as flags da Pokédex e as insígnias de Kanto/Johto.
As demais abas mostram que esses dados ainda não estão disponíveis para essas
gerações. FireRed/LeafGreen continuam reconhecidos em dumps brutos de 128 KiB
(`0x20000`) e HeartGold (`0x47`)/SoulSilver (`0x53`) em dumps HGSS de 512 KiB
(`0x80000`). Arquivos reconhecidos com tamanho, estrutura ou checksums inválidos
são identificados como inválidos; outros formatos ficam preservados como não
suportados. Cópias antigas são reprocessadas na inicialização quando um parser
passa a reconhecê-las, sem reescrever os bytes do save.

Na Geração III, o mesmo dump bruto de 128 KiB (`0x20000`) pode ser FireRed,
LeafGreen, Ruby, Sapphire ou Emerald. A assinatura, os 14 setores de cada slot
e seus checksums distinguem os layouts de FRLG, Ruby/Sapphire e Emerald. Ruby e
Sapphire compartilham o mesmo layout, assim como FireRed e LeafGreen; quando o
nome do arquivo não identifica a versão, o seletor de jogo associa o snapshot
ao título escolhido. Essa associação é usada em todas as abas e para os dados
de disponibilidade da Pokédex. Não se presume que o conteúdo seja FireRed só
porque outro save foi aberto antes.

O reconhecedor Gen I/II segue os marcadores de listas de party/box usados pelo
[PKHeX SaveUtil](https://github.com/kwsch/PKHeX/blob/master/PKHeX.Core/Saves/Util/SaveUtil.cs).
Os offsets das flags seguem as estruturas públicas de [SAV1](https://github.com/kwsch/PKHeX/blob/master/PKHeX.Core/Saves/SAV1.cs),
[SAV1Offsets](https://github.com/kwsch/PKHeX/blob/master/PKHeX.Core/Saves/Substructures/Gen12/SAV1Offsets.cs),
[SAV2](https://github.com/kwsch/PKHeX/blob/master/PKHeX.Core/Saves/SAV2.cs) e
[SAV2Offsets](https://github.com/kwsch/PKHeX/blob/master/PKHeX.Core/Saves/Substructures/Gen12/SAV2Offsets.cs).
As listas usadas para reconhecer Red/Blue também são descritas nas
[disassemblies pret/pokered](https://github.com/pret/pokered/blob/master/engine/menus/save.asm).

| Estrutura FireRed/LeafGreen | Regra usada | Fonte técnica |
| --- | --- | --- |
| Setores | 32 setores de 4 KiB; cada save tem dois slots de 14 setores; Hall of Fame e Trainer Tower ocupam os quatro setores restantes | [`save.c`](https://github.com/pret/pokefirered/blob/master/src/save.c) |
| Setor normal | Dados de 3968 bytes; ID, checksum, assinatura `0x08012025` e contador no rodapé | [`save.h`](https://github.com/pret/pokefirered/blob/master/include/save.h) |
| Slot ativo | Todos os 14 IDs precisam estar presentes, checksums válidos e contador consistente; comparação usa aritmética de 32 bits | [`save.c`](https://github.com/pret/pokefirered/blob/master/src/save.c) |
| SaveBlock2 | Seção 0 (`0xF24`): treinador, tempo e flags da Pokédex | [`global.h`](https://github.com/pret/pokefirered/blob/master/include/global.h) |
| SaveBlock1 | Seções 1–4 (`0x3D68`): party, flags de progresso, Fame Checker e Trainer Tower | [`global.h`](https://github.com/pret/pokefirered/blob/master/include/global.h) |
| Boxes | 14 boxes × 30 PK3; current box no byte 0, registros alinhados em `0x1` ou `0x4` conforme checksums PK3, nomes em `0x8344` | [`pokemon_storage_system.h`](https://github.com/pret/pokefirered/blob/master/include/pokemon_storage_system.h) |
| Pokédex | `owned` e `seen` em `SaveBlock2.Pokedex`; 386 espécies nacionais | [`global.h`](https://github.com/pret/pokefirered/blob/master/include/global.h) |
| Progresso | Badges, campeão, Pokédex Nacional, flags das Ilhas Sevii e quests Ruby/Sapphire | [`flags.h`](https://github.com/pret/pokefirered/blob/master/include/constants/flags.h), [`event_data.c`](https://github.com/pret/pokefirered/blob/master/src/event_data.c) |
| Hall da Fama | Setores físicos 28–29; o checksum dos 3968 bytes fica no campo `id` do rodapé, enquanto `checksum` e contador não são usados; até 50 equipes de seis Pokémon, com personalidade (permite calcular natureza), mas sem data, item ou golpes por entrada | [`save.c`](https://github.com/pret/pokefirered/blob/master/src/save.c), [`save.h`](https://github.com/pret/pokefirered/blob/master/include/save.h), [`hall_of_fame.c`](https://github.com/pret/pokefirered/blob/master/src/hall_of_fame.c) |
| Miscelânea | 654 IDs de treinador (89–742) e 183 flags de itens ocultos associados a eventos de mapa; oito posições reservadas são excluídas | [`opponents.h`](https://github.com/pret/pokefirered/blob/master/include/constants/opponents.h), [`flags.h`](https://github.com/pret/pokefirered/blob/master/include/constants/flags.h), [`data/maps`](https://github.com/pret/pokefirered/tree/master/data/maps), [`renewable_hidden_items.c`](https://github.com/pret/pokefirered/blob/master/src/renewable_hidden_items.c) |

Para Ruby, Sapphire e Emerald, os checksums por setor são lidos conforme os
layouts públicos de [`pokeruby`](https://github.com/pret/pokeruby/blob/master/src/save.c)
e [`pokeemerald`](https://github.com/pret/pokeemerald/blob/master/src/save.c).
Ruby/Sapphire usam SaveBlock1 de `0x3AC0` e SaveBlock2 de `0x890`; Emerald usa
`0x3D88` e `0xF2C`, respectivamente. O mapa de setores, os offsets de flags e
os campos específicos de Emerald seguem os respectivos [`global.h` de Ruby](https://github.com/pret/pokeruby/blob/master/include/global.h)
e [`global.h` de Emerald](https://github.com/pret/pokeemerald/blob/master/include/global.h).

O arquivo precisa conter ao menos um slot completo. Um dump de 128 KiB
preenchido com `FF` não é um save utilizável e recebe uma mensagem de arquivo
inválido, em vez de aparecer como um jogo desconhecido.

O dump FireRed fornecido tem três bytes entre o contador de box atual e o
primeiro PK3; o parser escolhe entre esse alinhamento e o alinhamento padrão
validando os checksums dos registros, sem depender do nome do arquivo.

No HGSS, o contador seleciona o bloco antes de validar seu checksum. Se a cópia
ativa falhar no magic ou checksum, a importação é recusada; o parser não troca
silenciosamente para uma cópia antiga. O estado de checksum da cópia reserva é
registrado separadamente. No FireRed/LeafGreen, o parser escolhe o slot válido
mais recente e rejeita saves sem nenhum slot completo.

## Snapshot e dados lidos

O snapshot JSON normalizado tem `schemaVersion`, jogo/versão, hash e data de
observação, treinador, party, boxes, lista de Pokémon observados, Pokédex,
badges, progresso, coleções, `miscellany`, `hallOfFame` e metadados de
origem/cópias/checksum. Cada campo
que pode não ser seguro de interpretar carrega um estado (`supported`,
`partial`, `unknown` ou `unsupported`) e valor explícito.

O parser Gen I/II lê as flags seen/caught de 151/251 espécies, o ID do treinador,
o tempo de jogo e as insígnias disponíveis em Kanto/Johto. Ainda não decodifica
os registros individuais de Pokémon, o nome do treinador ou as demais flags de
progresso dessas gerações. O resumo da interface só mostra os campos que o
parser reconhece para cada formato; a estrutura visual é compartilhada, mas os
campos variam entre jogos. Sem o nome do treinador decodificado, snapshots Gen
I/II não são comparados entre si apenas com base no ID numérico.

O parser FireRed lê nome do treinador, IDs, sexo, dinheiro e tempo; party e
boxes; registros PK3 descriptografados e validados; flags seen/caught para 386
espécies; oito badges; vitória na Indigo League; National Dex; flags
observáveis das quests das Ilhas Sevii; e dados do Fame Checker, Trainer Tower
e minigames usados pelo perfil de completude. Registros Pokémon
com checksum inválido ficam visíveis como inválidos e não entram na contagem de
espécies extraídas.

O parser Ruby/Sapphire/Emerald também lê treinador, IDs, sexo, dinheiro,
tempo, party e boxes PK3, flags seen/caught para as 386 espécies, oito
insígnias de Hoenn, história observável, Hall da Fama e registros de revanche.
Emerald inclui os flags de Battle Frontier e seus recordes Pokémon Jump e
Dodrio Berry Picking. Flags de itens ocultos de Hoenn e conteúdo não persistido
como eventos ou instalações individuais da Battle Frontier ainda são mostrados
como indisponíveis; a interface não reaproveita flags de FireRed para esses
jogos. A Pokédex offline da Geração III tem os 386 Pokémon e separa a ordem
regional de Hoenn (202) da ordem de Kanto dos remakes (151), além das
disponibilidades e encontros por versão.

A aba Miscelânea mostra quantos flags de vitória dos 654 IDs de treinadores
estão ativos e oferece uma lista pesquisável desses registros. Os IDs incluem
variantes internas de revanche, então não representam a quantidade de NPCs.
Também detalha os 183 itens ocultos com seu item e mapa. Dos itens ocultos, 122
são tratados como únicos; os outros 61 são renováveis, e a interface mostra
quais estão disponíveis no ciclo atual. O jogo pode sortear esses flags
novamente após 1.500 passos, portanto eles não fornecem um histórico confiável
de coleta. A aba Hall da Fama lê os setores especiais com checksum válido,
mostra cada equipe em uma grade de três colunas por duas linhas e ordena as
equipes da mais recente para a mais antiga. A natureza é derivada da
personalidade salva; item e golpes não são incluídos pelo jogo nesses registros,
e não há data por entrada.

O parser HGSS continua lendo os 493 flags de Pokédex, 16 badges, campeão de
Johto, estado de Kanto, Battle Points e formas de Unown. Campos HGSS não
suportados seguem desconhecidos; não são estimados.

O parser FireRed segue os fatos de formato documentados em `pret/pokefirered`;
o parser HGSS segue as estruturas documentadas em PKHeX. O projeto não copia
código-fonte desses projetos. Campos PK4 e tabela Gen IV de caracteres também
estão descritos em [`PK4.cs`](https://github.com/kwsch/PKHeX/blob/master/PKHeX.Core/PKM/PK4.cs)
e [`StringConverter4Util.cs`](https://github.com/kwsch/PKHeX/blob/master/PKHeX.Core/PKM/Strings/StringConverter4Util.cs).

## Collection e identidade

Cada registro válido da party/box aparece como uma observação com jogo, hash,
data, área e posição. O identificador interno UUIDv5 é derivado de dados
estáveis do Pokémon e treinador; nenhum ID é escrito no PK3/PK4. Cópias duplicadas
no mesmo snapshot recebem identificadores separados, pois não há evidência
para uni-las.

- `OBSERVED`: primeira ocorrência dessa assinatura no conjunto de snapshots.
- `INFERRED`: a mesma assinatura está em snapshots do mesmo treinador ou há
  duplicata ambígua. A interface deixa essa inferência visível.
- `CONFIRMED`: reservado para uma transferência direta confirmada pelo Chest
  Link. O fluxo atual não cria esse estado, pois a importação de save é somente
  leitura e não confirma transferências.

Esses identificadores são uma ferramenta local de histórico; não provam
identidade biológica quando os campos do save não bastam para distinguir dois
registros.

## Comparação, Journey e Completion Tracker

`SnapshotComparator` compara apenas snapshots do mesmo jogo e treinador. Pode
reportar novos/removidos badges, flags seen/caught, flags de história FireRed,
BP, formas Unown, tempo e contagens de Pokémon. O delta de tempo e a primeira aparição entre leituras são
`INFERRED`: o instante real do acontecimento não é conhecido. O snapshot mais
recente também apresenta esses deltas na interface Native Saves quando há uma
leitura anterior comparável.

Trainer Journey apresenta:

- `DIRECT`: estado que estava presente no snapshot lido, com a data da leitura;
- `INFERRED`: mudança observada entre dois snapshots;
- `MANUAL`: nota inserida pelo usuário.

O perfil `FireRed observável` considera 500 objetivos: oito badges, dez flags
da história e Sevii, 380 capturas do conjunto nacional elegível, 96 pistas do
Fame Checker, quatro modos da Trainer Tower e dois recordes de minigame. As
380 capturas excluem Mew, Lugia, Ho-Oh, Celebi, Jirachi e Deoxys, que o próprio
jogo exclui do marco de Pokédex completa. O save permanece imutável; quando a
API do Tracker é consultada, o servidor confere o hash da cópia guardada e
extrai esses campos em memória, inclusive para snapshots criados antes desta
expansão. A interface mostra só os agregados de captura nesta aba; espécies e
estados detalhados aparecem na Pokédex.

Em Journey, `Eventos de FireRed/LeafGreen` acompanha Mew, Lugia, Ho-Oh e
Deoxys pela flag de captura da Pokédex. Mew podia ser distribuído diretamente
para um save de FireRed/LeafGreen; Lugia e Ho-Oh são encontros liberados pelo
MysticTicket, e Deoxys pelo AuroraTicket. Celebi e Jirachi ficam fora desse
grupo porque suas distribuições de geração III vinham de Pokémon Colosseum ou
Pokémon Channel; eles continuam visíveis na Pokédex caso tenham sido obtidos e
registrados no save. Journey mostra apenas os ícones e seus estados. Em
Completude, cada objetivo abre um checklist com a descrição dos passos e o
estado lido do snapshot; no Fame Checker, cada personagem reúne suas seis
pistas, e uma única conversa ou batalha pode marcar mais de uma linha. As
espécies continuam detalhadas somente na Pokédex. A correspondência das pistas
segue os textos e scripts do projeto
[`pret/pokefirered`](https://github.com/pret/pokefirered), em especial
[`data/text/fame_checker.inc`](https://github.com/pret/pokefirered/blob/master/data/text/fame_checker.inc)
e [`data/scripts/fame_checker.inc`](https://github.com/pret/pokefirered/blob/master/data/scripts/fame_checker.inc).

Os offsets e limites usados vêm das estruturas SaveBlock1/SaveBlock2, IDs de
estatísticas, campos do Fame Checker e modos da Trainer Tower do projeto
[`pret/pokefirered`](https://github.com/pret/pokefirered): [`global.h`](https://github.com/pret/pokefirered/blob/master/include/global.h),
[`game_stat.h`](https://github.com/pret/pokefirered/blob/master/include/constants/game_stat.h),
[`fame_checker.c`](https://github.com/pret/pokefirered/blob/master/src/fame_checker.c),
[`trainer_tower.h`](https://github.com/pret/pokefirered/blob/master/include/constants/trainer_tower.h)
e [`pokedex.c`](https://github.com/pret/pokefirered/blob/master/src/pokedex.c).
A porcentagem resume os 500 critérios da aba Completude. Os flags de vitórias e
itens ocultos aparecem separadamente em Miscelânea; o perfil HGSS anterior
segue disponível.

## Fases que continuam bloqueadas

- A leitura direta no 3DS (`CTRGameSaveSource`) não foi ativada. Ela precisa de
  integração com os serviços nativos de save e validação por leitura/releitura
  no hardware e nos títulos-alvo. Checkpoint e a API [libctru FS](https://github.com/devkitPro/libctru/blob/master/libctru/include/3ds/services/fs.h)
  servem de referência de investigação, não de evidência de suporte neste app.
- A leitura de cartucho DS/DS Lite (`NDSCartridgeSaveSource`) não foi ativada.
  O Slot-1 concorre com o meio de inicialização do aplicativo, e tamanho/tipo
  de save dependem do cartucho. É necessário validar a estratégia em hardware
  real sem presumir que troca de cartucho ou leitura via flashcart funciona.
- Não há `GameSaveWriter`. Os testes atuais usam fixtures sintéticas, não dumps
  reais comparados. Escrita só poderá começar após validar leitura, checksums,
  snapshots e dumps reais, além do fluxo de backup, hash, validação, confirmação,
  escrita, releitura e comparação definido no plano.
- O dump FireRed válido fornecido foi lido localmente, com checksums de setores
  e dos PK3 válidos. Ainda falta comparação com uma segunda ferramenta e
  validação em hardware real; não há adaptação de escrita nem conversão entre
  gerações.

Nenhum resultado desta documentação afirma teste em hardware. A validação
local e a validação física são reportadas separadamente. Esta documentação
abrange o parser de save do PC/host e, na seção indicada, descreve o leitor de
arquivos `.sav` incorporado aos consoles. As versões DS e 3DS continuam usando
o número central em `include/version.hpp`.
