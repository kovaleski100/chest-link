# Chest Link 0.4.28 — inicialização da recepção direta

## Causa e correção

O usuário confirmou que o 3DS já reconhece a rede na 0.4.27, mas continua
mostrando “Recepção direta indisponível”. Uma sondagem TCP aceitou conexão
na porta 40991. Isso não comprova que o app consegue processar transferências.

O teste de regressão reproduziu um defeito no fluxo após atualização:

1. A mensagem de limpeza das versões anteriores executava o listener antes
   do início explícito da recepção.
2. Depois da mensagem, a inicialização abria um segundo socket na mesma porta.
3. A falha de bind descartava a referência ao primeiro socket sem fechá-lo.
   A porta permanecia aberta, mas sem um listener controlado pelo app.

A recepção agora fica desabilitada durante os diálogos anteriores à
inicialização e depois do encerramento. A abertura é idempotente, preserva
o socket existente e prepara o acompanhamento da rede para não reabrir o
listener no primeiro frame do menu. Falhas posteriores à abertura fecham
o socket antes de uma nova tentativa. Mensagens de socket, modo não
bloqueante, bind e listen mostram a etapa e o código de erro.

O código é compartilhado pelos dois consoles. DS e 3DS recebem a versão
0.4.28; não há mudança nos drivers Wi-Fi do DS, WPA2, DHCP ou configuração
de rede nativa do 3DS. Não há alteração de bancos ou de backups de Pokémon.

## Validação

O teste usa as funções reais do app e da camada TCP, com plataforma, GUI e
operações de socket simuladas. Antes da correção, reproduziu a falha com
um socket ainda aberto e o listener indisponível. Depois da correção, passa
pelos diálogos de limpeza e encerramento, abertura repetida, primeiro frame,
troca de IP, desconexão/retorno, preservação do PIN e falhas de abertura.
Uma falha depois da criação do socket não deixa a porta ocupada; as novas
tentativas recuperam o listener.

- `make console-ports-test test mailbox-test gui-test`: passou. Inclui
  o teste do listener, rede 3DS, publicação conjunta, atualizador, núcleo,
  ExtData, regressões do DS, caixa postal e interface.
- `make console-ports-sanitize ASAN_OPTIONS=detect_leaks=0`: passou com
  ASan/UBSan, incluindo o novo teste do listener. Vazamentos não foram
  verificados pelo sanitizer neste ambiente; o teste de sockets simulado
  confere explicitamente que nenhuma porta/socket fica abandonada.
- `make release`: compilou, validou os banners/manifests e publicou ambos.
  3DSX: 1.287.812 bytes; NDS: 1.324.544 bytes; versão compartilhada: 1052.
- O servidor do PC entregou ambos os binários completos pelo protocolo de
  atualização. Versão, tamanho e SHA-256 recebidos coincidiram com os arquivos
  publicados. Os 29 hashes do pacote passaram.

O usuário confirmou que a transferência console→PC funciona em hardware.
A transferência direta entre consoles e a entrega PC→console ainda precisam
de validação em hardware. A verificação acima baixou os apps para cálculo do
hash no PC, sem alterar bancos, fila ou backups.

## Instalação

O usuário escolheu **Atualizar pelo PC**. Após baixar a versão 0.4.28,
encerre o app e abra o Chest Link novamente pelo Homebrew Launcher.
Se aparecer a mensagem de limpeza, confirme-a; no menu principal, confira
se a recepção passa a mostrar IP e PIN. Não é necessário usar FTP ou retirar
o cartão SD. A versão antiga é preservada durante a instalação pelo
atualizador, conforme o mecanismo de backup existente.
