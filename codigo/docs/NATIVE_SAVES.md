# Native Saves

O Native Saves importa um dump de save pelo PC e lê os dados sem alterar o
arquivo escolhido. A aplicação guarda uma cópia identificada por SHA-256 e um
snapshot normalizado. O fluxo principal agora é Pokémon FireRed; o parser HGSS
anterior continua compatível. Bancos PKSMBANK, Pokémon Chest, mailbox,
protocolos e transferências seguem separados desse leitor.

## Componentes

- `include/save_source.hpp` define a origem, seus metadados, o resultado da
  leitura e a interface `SaveSource`.
- `host/native_saves/raw_file_save_source.cpp` lê um arquivo em modo binário,
  limita a leitura a 64 MiB por padrão e calcula o SHA-256 dos bytes retornados.
- `server/native_saves.py` separa aquisição, detecção, parsers FireRed/HGSS,
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

O importador reconhece FireRed/LeafGreen por estrutura em dumps brutos de
128 KiB (`0x20000`) e identifica HeartGold (`0x47`) e SoulSilver (`0x53`) em
dumps HGSS de 512 KiB (`0x80000`). Arquivos reconhecidos com tamanho, setores
ou checksums inválidos são identificados como inválidos; outros formatos ficam
preservados como não suportados. Cópias antigas são reprocessadas na inicialização
quando um parser passa a reconhecê-las, sem reescrever os bytes do save.

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

O parser FireRed lê nome do treinador, IDs, sexo, dinheiro e tempo; party e
boxes; registros PK3 descriptografados e validados; flags seen/caught para 386
espécies; oito badges; vitória na Indigo League; National Dex; flags
observáveis das quests das Ilhas Sevii; e dados do Fame Checker, Trainer Tower
e minigames usados pelo perfil de completude. Registros Pokémon
com checksum inválido ficam visíveis como inválidos e não entram na contagem de
espécies extraídas.

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
local e a validação física são reportadas separadamente. As alterações desta
fase são de PC/host e não mudam os executáveis DS/3DS nem sua versão central em
`include/version.hpp`.
