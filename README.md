# Chest Link 0.3

App independente com a **interface de armazenamento do PKSM adaptada para PC, DS/DSi e 3DS**, para copiar Pokémon selecionados ou uma ou várias boxes entre os bancos do **Pokémon Chest no DS/DSi** e do **PKSM no 3DS**, pela rede local. Há uma versão `.nds`, uma versão `.3dsx` e uma **caixa postal no PC com interface gráfica**, feita em Python e aberta no navegador local. Ambos os consoles podem enviar e receber diretamente ou pelo PC.

O PC funciona como a secretária que tu pediste: recebe e guarda as boxes quando o outro console está desligado. Para uma transferência direta, o destino fica na tela inicial e o listener pergunta automaticamente se deve aceitar; o PC também pode enviar diretamente ao listener informando IP e PIN. O PC conserva o backup mesmo após a entrega.

**Esta é uma versão experimental. Os executáveis foram compilados e os testes no PC passaram. Wi-Fi, carregamento e gravação nos consoles reais ainda precisam de validação. Na primeira execução, mantém os backups que tu já tens e testa uma única box.**

O app lê os bancos de armazenamento do Chest e do PKSM. Para transferir Pokémon que ainda estão nas boxes do SoulSilver, guarda-os primeiro no banco do Chest e salva. Depois de receber, a inserção deles no jogo de destino é feita pelo Chest ou pelo PKSM.

## O que vem no pacote

| Arquivo ou pasta | Uso |
|---|---|
| `DS/ChestLink_DS.nds` | App para DS, DS Lite ou DSi |
| `3ds/ChestLink_3DS/ChestLink_3DS.3dsx` | App para o Homebrew Launcher do 3DS |
| `3ds/ChestLink_3DS/ChestLink_3DS.smdh` | Ícone e identificação no launcher |
| `PC/servidor.py` | Servidor da caixa postal, Python 3.9 ou superior, sem pacotes adicionais |
| `PC/interface.py`, `PC/pokemon.py`, `PC/web/` | Interface gráfica e recursos offline; mantém junto do servidor |
| `PC/iniciar-linux.sh` | Atalho para iniciar o servidor no Linux |
| `PC/iniciar-windows.bat` | Atalho para iniciar o servidor no Windows |
| `codigo/` | Código completo, Makefiles e testes |
| `VALIDACAO.txt` | Resultados dos testes e das compilações |
| `SHA256SUMS.txt` | Hashes dos apps e dos arquivos do servidor entregues |

## Escolher a forma de transferência

| Opções no Chest Link | Quem precisa estar ligado |
|---|---|
| **Enviar ao console** | O destino abre Chest Link e aguarda o listener; a confirmação aparece automaticamente |
| **Enviar ao PC** | Console de origem e PC com o servidor aberto |
| **Enviar do PC ao console** | PC e console de destino com Chest Link aberto; informa IP/PIN do listener |

Essas opções copiam as boxes que tu selecionas. O destino recebe um banco `linkNNNN`, e os bancos existentes são preservados. A escolha **Enviar ao PC** encaminha a cópia para a caixa postal; a entrega automática ocorre quando o console já tem IP/PIN do PC salvos. Para a primeira entrega a um console sem essa configuração, usa o envio direto do PC com o IP/PIN mostrados pelo listener.

## Instalação — feita no PC, uma vez

1. Extrai o ZIP.
2. **Cartão do DS/DS Lite:** copia `DS/ChestLink_DS.nds` para o cartão da flashcard que tu já usas para abrir o Pokémon Chest. Pode ficar na raiz do cartão. No console, abre-o pelo menu da flashcard.
3. **Cartão do DSi:** copia o mesmo `.nds` para o SD interno e abre-o pelo TWiLight Menu++. Para usar WPA2, ele precisa iniciar em **modo DSi**. Um DSi executando homebrew em modo DS tem as limitações de Wi-Fi do DS.
4. **Cartão do 3DS:** copia a pasta `3ds/ChestLink_3DS` do pacote para a pasta `3ds` do cartão. O resultado deve ser `SD:/3ds/ChestLink_3DS/ChestLink_3DS.3dsx`, com o `.smdh` ao lado. No console, abre **Chest Link** pelo Homebrew Launcher.
5. Recoloca os cartões nos consoles. Para a ligação direta, abre Chest Link nos dois aparelhos; o destino não precisa de um botão de recebimento. Para a caixa postal, prepara o servidor do PC conforme a seção seguinte.

Se tu já instalaste a versão 0.1 ou 0.2, substitui os arquivos `.nds`, `.3dsx` e `.smdh` pelos deste pacote. No PC, atualiza **todos os arquivos da pasta PC**, incluindo `interface.py`, `pokemon.py` e a pasta `web`, conservando a tua pasta `dados`. Os nomes e caminhos dos apps continuam iguais.

## Iniciar a secretária — feito no PC

1. Extrai o ZIP para uma pasta permanente do PC. Dentro dela haverá a pasta **PC**. Não executes o servidor de dentro do ZIP.
2. O servidor precisa de **Python 3.9 ou superior**. No Linux Mint, normalmente já há Python 3. No Windows, instala Python se não estiver instalado; o atalho aceita o launcher `py` e também o comando `python`.
3. **Linux:** abre a pasta **PC** no gerenciador de arquivos, clica com o botão direito em uma área vazia e escolhe **Abrir no terminal**. Executa:

   ```sh
   python3 servidor.py
   ```

   Também podes executar `bash iniciar-linux.sh` nesse mesmo terminal.

4. **Windows:** abre a pasta **PC** e dá dois cliques em **iniciar-windows.bat**. Se preferires o terminal, abre-o nessa pasta e executa `py -3 servidor.py`.
5. O navegador abrirá a **interface gráfica de boxes** automaticamente. A janela do terminal também mostrará **IP do PC**, **PIN** de seis dígitos e **porta TCP 40992**. A interface gráfica também exibe esses números no topo. Esses são os números que tu vais informar nos consoles. Se houver mais de um IP, escolhe o da rede local em que estão os consoles.
6. Se o navegador não abrir, copia o link **Interface de boxes neste PC** exibido no terminal e abre-o no navegador desse mesmo PC. Esse link inclui a chave da interface; usa o link completo. A interface não precisa de internet.
7. Deixa a janela do terminal aberta enquanto um console estiver enviando ou buscando. O PC pode estar ligado ao roteador por Wi-Fi ou cabo de rede, desde que consiga comunicar-se com os consoles na mesma rede local.

O servidor cria a pasta **PC/dados**. Ela contém o PIN salvo, as cópias completas e as marcações de entrega. O PIN é reutilizado nos próximos inícios. Para encerrar, aperta **Ctrl+C** na janela do PC. Para voltar a usar, inicia o mesmo servidor, na mesma pasta. As cópias continuam guardadas mesmo com o PC desligado; para um console buscar, liga o PC e abre o servidor novamente.

**Conserva a pasta `dados` ao mudar ou atualizar o servidor.** Para usar uma pasta de dados existente em outro local, inicia com `python3 servidor.py --data "/caminho/para/dados"` no Linux, ou `py -3 servidor.py --data "C:\\caminho\\para\\dados"` no Windows. O comando não altera a localização dos bancos nos consoles.

Se o firewall do PC bloquear a conexão, permite a entrada do Python na rede privada/local ou libera **TCP 40992**. Usa a porta padrão: os apps dos consoles conectam-se à 40992. A ligação direta entre consoles usa a 40991.

O 3DS precisa de um ambiente homebrew já funcionando. O DS usa a mesma flashcard ou ambiente homebrew com que tu abres o Chest.

## Preparar o Wi-Fi — feito nos consoles

Configura os aparelhos para acessar **a mesma rede local**. O app usa TCP: **40991** na ligação direta e **40992** no servidor do PC. A rede precisa permitir comunicação entre os aparelhos; redes de convidados com isolamento de clientes podem bloquear isso. Não precisa de Internet nem dos servidores da Nintendo. Usar o PC como intermediário mantém as mesmas exigências de Wi-Fi do DS.

| Aparelho e modo | Rede compatível |
|---|---|
| DS / DS Lite | 2,4 GHz, com suporte a 802.11b; aberta ou WEP |
| DSi em modo DS | As mesmas limitações do DS |
| DSi em modo DSi | Pode usar WPA2, com conexão configurada no console |
| 3DS executando o `.3dsx` | Usa a conexão de Wi-Fi das configurações do 3DS |

Se tu tens um DS/DS Lite, um hotspot configurado apenas com WPA2 não resolve a conexão desse aparelho. Nesse caso, é necessária uma rede local compatível com o DS; uma rede temporária e separada pode cumprir essa função.

## Preparar os Pokémon — feito no Chest ou no PKSM

1. Abre o app que contém os Pokémon que tu queres enviar.
2. Coloca-os no **banco de armazenamento desse app** e salva.
3. Fecha o Chest ou o PKSM e abre Chest Link.
4. No primeiro uso, entra em **Consultar bancos** para conferir os nomes dos bancos e das boxes.

No DS, o app procura os bancos do Chest no SD interno e na flashcard. Se houver dois armazenamentos, ele permite escolher.

No 3DS, as opções são:

- **PKSM (ExtData):** usa o armazenamento interno de dados do PKSM, quando o 3DS permite acessá-lo.
- **PKSM (SD):** usa os bancos da pasta `/3ds/PKSM/banks`. Escolhe esta opção quando **Use ExtData** está desligado no PKSM.
- **Chest (SD):** aparece se o Chest também mantém bancos nesse cartão, por exemplo quando usado pelo TWiLight Menu++.

Escolhe o armazenamento em que aparecem os mesmos bancos que tu usas no app original. Se o PKSM estiver usando ExtData e tu receberes em **PKSM (SD)**, a cópia ficará no SD e só aparecerá no PKSM quando ele estiver configurado para usar esse armazenamento.

Se **PKSM (ExtData)** não aparecer, pode faltar permissão para montar esse arquivo ou não existir um cadastro de bancos nele. O caminho alternativo é desativar **Use ExtData** nas configurações do próprio PKSM, concluir e salvar a alteração para que o PKSM passe a usar os bancos no SD, e então usar **PKSM (SD)** no Chest Link. Confere os bancos em **Consultar bancos** antes do primeiro envio.

## Interface de boxes — PC e consoles

A tela de armazenamento mantém **30 espaços por box, em 6 colunas e 5 linhas**, barra com o nome da box, sprites, cursor e resumo do Pokémon. Ao abrir **Consultar bancos**, a tela mostra as boxes e, embaixo, somente **Enviar ao PC** e **Enviar ao outro console**. O menu inicial contém apenas **Consultar bancos**, **Créditos** e **Sair**; o status do listener aparece nele. O PC usa um painel próprio, mais limpo, sem imitar a tela do PKSM.

| Ação no DS/3DS | Controle |
|---|---|
| Escolher Pokémon | Direcional, ou toque no espaço da tela inferior |
| Marcar/desmarcar um Pokémon | **A**, ou toque no sprite |
| Marcar/desmarcar a box inteira | **Y**, ou botão **Y: Box** |
| Marcar todas as boxes / limpar todas | **X**, ou botão **X: Todas** |
| Box anterior / próxima | **L/R**, ou setas ao lado do nome da box |
| Continuar para o envio | **START**, ou botão **START: Enviar** |
| Voltar | **B**, ou botão de voltar |

Em **Consultar bancos**, **A** ou um toque no Pokémon marca ou desmarca a seleção, e **L/R** trocam a box. Os botões inferiores enviam a seleção ao PC ou ao outro console.

No PC:

1. **No console**, salva e fecha Chest/PKSM, abre Chest Link e usa **Enviar ao PC**. Escolhe o destinatário DS ou 3DS e conclui o envio. O outro console pode estar desligado.
2. **No PC**, a cópia aparece na lista **Bancos guardados no PC**. Seleciona o banco nessa lista.
3. **No PC**, escolhe a box no campo **Box** ou nas setas do painel inferior. Clica no Pokémon para marcá-lo. **Box inteira** marca os 30 espaços; **Todas** marca todas as boxes do banco. A parte inferior destaca a seleção.
4. **No PC**, clica **Enviar seleção ao DS** ou **Enviar seleção ao 3DS**, informa o IP e o PIN mostrados na tela inicial do console e confirma. O console perguntará se aceita a transferência antes de gravar; o PC também mantém o backup.
5. **No console de destino**, confirma a oferta. A entrega cria um banco `linkNNNN`; fecha Chest Link, abre Chest/PKSM e seleciona esse banco.

O teclado do PC também permite navegar: depois de clicar no painel inferior, usa as setas para o cursor, **A** ou **Espaço** para marcar, **Y** para a box, **X** para todas e **L/R** para trocar a box. Os contadores de seleção mostram espaços marcados; a confirmação da transferência informa quantos Pokémon realmente estão presentes.

Para iniciar somente o servidor, sem interface, usa `python3 servidor.py --no-ui`. `--no-browser` mantém a interface disponível pelo link exibido, sem abrir o navegador automaticamente. A interface fica disponível somente no próprio PC; a comunicação com os consoles continua na porta TCP 40992.

## DS → PC → 3DS — o 3DS pode estar desligado durante o envio

1. **No PC:** inicia `servidor.py` como explicado acima. Deixa a janela aberta e anota o IP e o PIN mostrados nela.
2. **No DS/DSi:** depois de salvar e fechar o Chest, abre Chest Link e escolhe **Enviar ao PC**.
3. **No DS/DSi:** escolhe o armazenamento, se aparecer essa pergunta, e o banco do Chest. A grade mostra os 30 espaços da box e os sprites dos Pokémon. Usa o direcional para mover o cursor e **A** para marcar um Pokémon; **Y** marca a box inteira e **X** marca todas as boxes. **L/R** troca a box. Aperta **START** ou toca **START: Enviar** para continuar.
4. **No DS/DSi:** confirma as quantidades. Na pergunta sobre qual console receberá depois, escolhe **3DS / PKSM**.
5. **No DS/DSi:** informa o **IP do PC**, confirma com **A** e informa o **PIN do PC**. Esquerda/direita muda o campo; cima/baixo altera o valor. O app lembra o IP e o PIN do servidor para os próximos usos.
6. **No DS/DSi:** aguarda **PC confirmou a copia** e o ID mostrado. Essa confirmação significa que a cópia completa foi conferida e publicada na pasta de dados. A origem continua intacta. Agora tu podes desligar o DS; o 3DS não precisava estar ligado.
7. **Depois, no PC:** deixa ou abre novamente o mesmo servidor. Se tu desligaste o PC, as boxes estarão na mesma pasta de dados quando ele voltar.
8. **No 3DS:** abre Chest Link; o listener mostra IP e PIN na tela inicial. Se o 3DS já tiver IP/PIN do PC salvos, uma cópia pendente será oferecida automaticamente.
9. **No PC:** na interface, escolhe a cópia, clica **Enviar seleção ao 3DS** e informa o IP/PIN do listener do 3DS.
10. **No 3DS:** confirma a transferência. Aguarda a gravação e anota o banco indicado, como **link0001**.
11. **No 3DS:** fecha Chest Link, abre o PKSM e seleciona esse banco. O servidor mantém o backup original.

## 3DS → PC → DS — o DS pode estar desligado durante o envio

1. **No PC:** deixa o servidor aberto.
2. **No 3DS:** salva e fecha PKSM, abre Chest Link e escolhe **Enviar ao PC**.
3. **No 3DS:** escolhe o armazenamento correto do PKSM e o banco. Marca Pokémon com **A**, a box inteira com **Y**, ou todas com **X**; **L/R** troca a box. Usa **START** ou o botão de envio na tela para continuar. Confirma e escolhe **DS / Pokemon Chest** como destinatário.
4. **No 3DS:** informa o IP/PIN do **PC** e aguarda a confirmação de que ele guardou a cópia. Depois podes desligar o 3DS.
5. **Mais tarde, no DS/DSi:** abre Chest Link e deixa o listener visível na tela inicial.
6. **No PC:** seleciona a cópia, clica **Enviar seleção ao DS**, informa o IP/PIN do DS e aguarda a confirmação no console. Depois, abre o Chest e seleciona o banco indicado.

Para um destino em flashcard/modo DS, envia no máximo **50 boxes de cada vez**. Um pacote maior pode ficar guardado no PC, mas será recusado por esse destino. Gerações que o Chest não aceita são recusadas antes do envio para sua fila.

## Cópias de segurança no PC

O PC mantém todos os backups na interface. A entrega direta ao console usa o listener; se uma transferência já tiver sido enfileirada, o console pode recebê-la automaticamente quando seus dados de conexão do PC estiverem salvos.

Quando um console recebe uma cópia do PC, o backup original continua disponível na lista e pode ser reenviado.

O console verifica cópias pendentes automaticamente se já tiver o IP e o PIN do PC salvos. Se encontrar uma, pergunta antes de receber. Repetir o mesmo envio reutiliza um banco `linkNNNN` que ainda tenha exatamente o mesmo conteúdo e os mesmos nomes de boxes. Se tu já editaste esse banco ou moveste Pokémon dele, uma nova cópia pode ser necessária e receberá outro nome.

O servidor guarda até **512 MiB e 1.000 pacotes** por padrão, contando também os entregues. Ele não apaga backups automaticamente. Se ficar cheio, podes reiniciá-lo com `python3 servidor.py --max-mib 1024 --max-items 2000`, por exemplo. No Windows, usa `py -3` em vez de `python3`.

## Transferir DS → 3DS — tudo daqui em diante é nos consoles

1. **No 3DS**, abre Chest Link e deixa a tela inicial aberta. O listener mostrará **IP** e **PIN**.
2. Escolhe **PKSM (ExtData)** ou **PKSM (SD)** conforme a configuração do teu PKSM.
3. **No DS/DSi**, abre Chest Link e escolhe **Consultar bancos**.
4. Escolhe o banco do Chest. Usa o direcional para navegar pelos **Pokémon** da box. **A** marca ou desmarca o Pokémon sob o cursor; também podes tocar no sprite na tela inferior. **Y** marca a box atual; **X** marca todas as boxes, ou limpa a seleção se todas já estiverem marcadas. **L/R** troca a box.
5. Aperta **START** ou toca **START: Enviar** para preparar o envio. Confere a quantidade de boxes e Pokémon e confirma com **A**.
6. **No DS/DSi**, escolhe **Enviar ao outro console**, informa o IP e o PIN mostrados no 3DS e confirma.
7. **No 3DS**, aparecerá a quantidade de boxes e Pokémon oferecidos. Confirma com **A** para receber.
9. Aguarda a conferência e a gravação. Ambos os consoles devem mostrar confirmação e o nome do banco novo, como **`link0001`**.
10. **No 3DS**, fecha Chest Link, abre PKSM e seleciona esse banco novo no seletor de bancos. Os Pokémon estarão nas boxes desse banco. A partir daí, usa o PKSM para colocá-los no jogo que tu escolheres.

Para o primeiro teste, envia só uma box. Confere o conteúdo recebido e a box de origem antes de enviar o restante.

## Transferir 3DS → DS

O procedimento é o mesmo, com os papéis invertidos:

1. **No DS/DSi:** abre Chest Link e deixa o listener na tela inicial; seleciona o armazenamento do Chest.
2. **No 3DS:** abre **Consultar bancos**, seleciona o banco do PKSM e marca as boxes com Y ou X.
3. **No 3DS:** escolhe **Enviar ao outro console** e informa o IP/PIN exibidos no DS/DSi.
4. **No DS/DSi:** confirma o recebimento com A.
5. **No DS/DSi:** depois da confirmação, abre o Chest e seleciona o banco `linkNNNN` criado na importação.

## Como a cópia é gravada

- O banco de origem permanece intacto. A operação sempre faz uma **cópia**.
- As boxes escolhidas são reunidas, na ordem em que aparecem no banco, em um **banco novo**. Boxes 2 e 7 da origem, por exemplo, viram boxes 1 e 2 do banco recebido, conservando seus nomes e as posições dos 30 slots. Na seleção individual, os slots não marcados ficam vazios na cópia nova.
- O conteúdo dos registros é preservado. O app não converte um Pokémon de SoulSilver para o formato de Emerald; essa compatibilidade é resolvida pelo app que o insere no jogo.
- O receptor confere tamanho, versão, gerações, nomes de boxes e **SHA-256** do banco e dos nomes antes da importação, e confere novamente os arquivos gravados.
- O cadastro `banks.json` recebe o número exato de boxes do banco novo. As entradas dos bancos existentes são mantidas.
- Antes da atualização do cadastro, uma cópia dele fica na pasta `chest-link` do armazenamento escolhido, com nome como `registry0001.json`. Essa é uma cópia do **cadastro**, não um backup completo de todos os bancos.

Essas verificações detectam falhas de transporte e gravação. A validação parte dos dados existentes na origem; não comprova a legalidade de cada Pokémon nem corrige um banco que já estava danificado.

## Se a operação for interrompida

Se a conexão cair durante o recebimento, os dados parciais não são cadastrados como banco. A origem continua intacta.

Se faltar energia durante a importação, **abre Chest Link novamente antes de abrir Chest/PKSM**. O app procura seu diário e tenta concluir a recuperação do cadastro a partir da cópia verificada. Se o diário ou seu backup estiver danificado, ele interrompe a recuperação e mostra um erro para preservar os arquivos.

Se o envio falhar **depois da gravação no receptor**, a confirmação de rede pode ter se perdido. Consulta os bancos `linkNNNN` no receptor antes de repetir, para evitar uma cópia duplicada.

**Pelo PC:** um upload incompleto não entra na fila. Uma busca incompleta permanece pendente. Se o console mostrar que a cópia foi gravada, mas que o PC não confirmou, esse banco já está salvo localmente; tenta buscar novamente para concluir a confirmação. Um banco `linkNNNN` ainda idêntico será reutilizado. Um erro de leitura/hash do backup do PC preserva os arquivos e recusa a entrega.

Se tu errares o PIN ou recusares a oferta, mantém Chest Link aberto no destino e repete o envio a partir da origem ou do PC.

## Limites desta versão

- Leitura dos bancos PKSMBANK versões 1, 2 e 3; saída na versão 3.
- Até 500 boxes por banco no PKSM e no Chest em SD interno com modo DSi. O destino em flashcard/modo DS fica limitado a 50 por envio; divide a seleção em grupos menores se necessário.
- No sentido **PKSM → Chest**, registros de gerações 1 e 2 são recusados para manter compatibilidade com o formato e leitor conferidos do Chest v2.2. Registros de gerações desconhecidas também são recusados.
- Seleção individual, de boxes inteiras ou de todas as boxes, com grade 6 × 5 e sprites. A transferência preserva os dados e posições dos registros selecionados.
- Esta é a interface **de armazenamento** do PKSM adaptada ao Chest Link. As ações são as de consulta, seleção e transferência; editores de atributos, saves, Pokédex, scripts e trocas de geração continuam sendo funções do Chest/PKSM.
- As 898 espécies até a geração VIII têm ícones offline. Há ícones adicionais para 20 formas comuns. As demais formas usam o ícone básico e conservam o número de forma no resumo e todos os dados na transferência. Um registro cujo resumo não puder ser lido aparece como **Registro** e continua preservado na cópia.
- O PC mostra as cópias já enviadas ao servidor. Bancos dos consoles são lidos pelo app no respectivo console; para vê-los no PC, envia uma cópia ao PC. O PC não consulta um console desligado.
- O importador para quando o cadastro já tem 89 bancos, para manter o seletor dos apps utilizável.
- O PIN é exibido no console receptor ou no servidor do PC, conforme a opção escolhida. O recebimento exige confirmação no console. O tráfego não é criptografado; usa a tua rede local.
- O app cria cópias para reduzir o risco de perda durante a transferência. O problema de exclusão que tu observaste no Chest ainda não foi diagnosticado ou corrigido por este projeto.

## Compilar e testar — opcional, no PC

Dentro de `codigo/`, com GCC/G++ e make:

```sh
make test
make mailbox-test
make gui-test
make gui-sanitize
make sanitize
make mailbox-sanitize
make all
```

O último comando cria a ferramenta de diagnóstico `build/chest-link-cli`. Os apps dos consoles dispensam essa ferramenta tanto na ligação direta quanto pelo servidor Python. `mailbox-test` executa o servidor com TCP real e chama o cliente C++ compartilhado pelos apps, incluindo quedas de conexão, reinício do PC, limite de espaço e recuperação após interrupção.

Em ambientes onde LeakSanitizer não consegue ler `/proc`, acrescenta `ASAN_OPTIONS=detect_leaks=0` aos comandos `make sanitize`, `make mailbox-sanitize` e `make gui-sanitize` para executar AddressSanitizer/UndefinedBehaviorSanitizer sem a detecção de vazamentos.

Para o DS, instala [BlocksDS/Wonderful](https://blocksds.skylyrac.net/docs/setup/linux/) e executa `make ds`. Para o 3DS, instala [devkitARM e libctru](https://devkitpro.org/wiki/Getting_Started) e executa `make 3ds`.

Os recursos gráficos estão incorporados aos executáveis dos consoles. O PC carrega a pasta `web/assets` incluída no pacote. Para regenerar os recursos nativos, o comando de desenvolvimento `python3 tools/pack_assets.py` exige Pillow e uma fonte DejaVu Sans Mono; isso é opcional e não é exigido para usar o app ou compilar as fontes já geradas.

Os Makefiles permitem configurar `BLOCKSDS`, `WONDERFUL_TOOLCHAIN`, `DEVKITPRO` e `DEVKITARM`. Os SDKs não vêm no ZIP. Os detalhes do formato e do protocolo estão em `docs/`.

Licença do código: GPL-3.0-or-later. Projeto independente dos mantenedores do Pokémon Chest e do PKSM.
