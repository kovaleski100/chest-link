# Revisão da comunicação WPA2 no DS

## Percurso revisado

1. `platform/nds/main.cpp` seleciona o ponto de acesso, restaura a senha salva e aguarda associação e IPv4.
2. `third_party/dswifi/source/arm7/ntr/ieee_802_11/beacon.c` aceita somente RSN com PSK, CCMP para par e grupo, sem PMF obrigatório; `association.c` anuncia esse perfil.
3. `third_party/dswifi/source/arm7/ntr/wpa.c` calcula a PMK, executa o handshake EAPOL, instala PTK/GTK, autentica CCMP e controla replay por TID.
4. `third_party/dswifi/source/arm9/lwip/rx_tx.c` forma quadros de saída; `arm7/ntr/tx_queue.c` os cifra antes da transmissão. Na entrada, `arm7/ntr/rx_queue.c` decifra e autentica antes de encaminhar ao lwIP.
5. O lwIP executa DHCP e TCP. `source/network.cpp` e `source/update.cpp` recebem o manifesto e a imagem; `server/chest_link_server.py` envia os dados e registra a sessão.

## Evidência disponível

- Os testes locais passaram: 166 verificações NTR WPA2, 470 de recepção com RAM simulada, 1.431 da fila de pacotes e 25 de DHCP.
- Em `PC/dados/update-communication.jsonl`, duas tentativas anteriores registraram autenticação TCP e decisão positiva do DS. O servidor entregou 32.768 bytes ao socket, mas depois bloqueou por minutos e terminou com `Broken pipe` ou timeout. Entrega ao socket do PC não prova recebimento pelo DS.
- A imagem ofertada nessas tentativas era v0.5.6 (`version`: 1286); o log não valida a correção QoS da v0.5.7 no console físico.
- O melonDS exercitou a atualização em `melonAP`, uma rede virtual aberta. Não testa o rádio NTR recebendo CCMP em WPA2.

## Captura no DS Lite real em 17/10/2026

Foram analisados os arquivos do SD `ChestLink_update_795798-1.jsonl` e
`ChestLink_update_1134216-2.jsonl`, junto ao registro do PC
`PC/dados/update-communication.jsonl`. Ambos os arquivos identificam o app
v0.5.7 e `driver=NTR security=WPA2`.

- A sessão `795798-1` conectou ao IP salvo `10.0.0.187:40992` em 47 ms.
  O PC ofereceu a própria v0.5.7. O DS respondeu `state=current` em 825 ms;
  a decisão negativa no PC corresponde à ausência de uma versão nova.
- A sessão `1134216-2`, correspondente à sessão `5920524b8dcc4125` do PC,
  conectou em 38 ms, recebeu a oferta v0.5.8 e registrou
  `update_offer_accepted` aos 3.809 ms. O PC recebeu a decisão positiva,
  enviou a resposta de início e entregou dois blocos de 16 KiB ao socket.
  Essa entrega ao socket não equivale à entrega ao DS.
- O contador TCP do DS chegou somente a 5.112 bytes. Pelo formato do
  protocolo, 72 bytes são respostas e manifesto; restam 5.040 bytes da
  imagem de 1.400.320 bytes, ou quatro segmentos de 1.260 bytes.
- A última recepção ocorreu aproximadamente aos 502.377 ms (8 min 22 s)
  desde o início do logger. Antes dela, o fluxo ficou cerca de 369 s sem
  receber dados. O PC registrou `transfer_failed: timed out` aos 603.804 ms
  de sua sessão.
- O DS terminou aos 1.012.070 ms (16 min 52 s) com `Cancelado.`, após
  aproximadamente 510 s sem receber dados. Portanto, o erro final no SD
  foi cancelamento, e o erro final no PC foi timeout.
- Na última amostra, `ccmp_rx=971`, `ccmp_valid=970`, `mic_failed=0` e
  `rx_ram=971`. Na primeira amostra eram 417, 417, 0 e 417. Todos os
  candidatos CCMP contabilizados passaram pela recuperação da RAM;
  nenhum incremento veio do percurso normal de quadros comprometidos na
  fila do rádio. Um candidato foi rejeitado antes da validação de MIC;
  os contadores não distinguem replay, cabeçalho e outros motivos.
- Os registros UDP de diagnóstico continuaram chegando ao PC durante o
  bloqueio TCP. Isso confirma atividade do app e comunicação de saída,
  mas não mede a entrega de cada segmento de entrada.

A leitura do arquivo é feita em blocos de 4.096 bytes em `source/update.cpp`.
O progresso visual só é atualizado ao completar um bloco. Nesta captura,
o primeiro bloco só pôde ser completado com o quarto segmento, aos 8 min
22 s. Isso explica a permanência inicial na mensagem de espera mesmo
com alguns bytes já recebidos. Não há erro de gravação no SD registrado.

## Risco principal

O código preserva o cabeçalho e o MIC CCMP com `W_RX_LEN_CROP = 0x0202`,
habilita `W_RXSTAT_INC_IE = BIT(9)` e tenta recuperar da RAM quadros que
o rádio rejeitou sem avançar `W_RXBUF_WRCSR`. `Wifi_RxQueueFlush()` também
é chamado periodicamente por `Wifi_NTR_Update()`; a recuperação não
depende exclusivamente de interrupções de recepção.

As capturas reais comprovam que alguns criptogramas intactos são recuperados
e autenticados, mas o download sustentado não funciona. A recuperação lê
uma única região ainda não comprometida e exige que ela permaneça estável
durante a cópia. Sob uma sequência de quadros, sobrescrita antes da cópia
é uma hipótese compatível com o código e com os contadores; os logs não
comprovam cada descarte nem isolam perdas entre ARM7, ARM9, lwIP e ACK TCP.
`rx_radio_rejected=0` não prova ausência de perdas no rádio.

O foco da investigação passa a ser a entrega contínua de quadros WPA2 no
driver NTR e seu encaminhamento ao TCP. Não há, nestes logs, uma alteração
de registro de rádio comprovadamente correta. A versão v0.5.8 foi apenas
oferecida; nenhum dos arquivos comprova sua instalação ou execução no
hardware real.

## Correção de fluxo na v0.5.9

- O servidor deixa de enfileirar blocos de 16 KiB para o DS. No Linux,
  usa `TCP_NODELAY` e `TCP_INFO` para aguardar o esvaziamento dos bytes ainda
  não enviados e dos segmentos não confirmados antes de enviar outro bloco.
  Cada bloco tem no máximo 1.024 bytes e nunca excede o MSS da conexão.
  A resposta de início também é confirmada antes dos dados do arquivo.
- A mudança mantém o protocolo anterior, permitindo que o DS com v0.5.7
  tente baixar a correção. Em sistemas sem os contadores Linux, o servidor
  usa blocos de 256 bytes separados por 50 ms e registra explicitamente
  `mode=paced`; essa alternativa não comprova recebimento por ACK.
- No DS, um hook de entrada do lwIP antecipa o ACK de segmentos de dados
  para NTR/WPA2. A validação TCP continua normal. DSi nativo, WEP e redes
  abertas mantêm a política de ACK anterior.
- DS e 3DS mostram o primeiro progresso após 512 bytes e continuam em blocos
  de 4 KiB, evitando uma pausa de tela por cada setor do arquivo. Depois da aceitação,
  a espera por atividade da transferência passa a 30 segundos. A confirmação
  humana continua com seu prazo anterior. O DS verifica o tempo transcorrido
  também quando `select()` sinaliza leitura e `recv()` devolve `EAGAIN`.
- A leitura tenta drenar o socket antes de aguardar um quadro de tela. A
  versão anterior aguardava VBlank em toda leitura, inclusive quando os
  bytes já estavam disponíveis. O teste de regressão inclui dados recebidos
  em leituras parciais e exige que sejam drenados sem esperas de tela.
- O log do PC identifica `transfer_flow_control`, `tcp_ack_wait` e
  `tcp_ack_timeout`. Em `chunk_sent`, `tcp_acknowledged` distingue a
  confirmação TCP de uma simples entrega ao socket.

Esta correção reduz as rajadas que podem sobrescrever a região de RAM usada
pela recuperação experimental. Ela não altera os registros de rádio nem
prova que a recepção NTR se tornou confiável no hardware físico. A verificação
local inclui um receptor simulado que rejeita sobreposição de quadros e a
pilha lwIP real recebendo um único segmento, sem avanço de temporizador.

## Resultado físico da correção: falha em 17/10/2026

O DS Lite em `10.0.0.147`, executando v0.5.9 com NTR/WPA2, tentou baixar
a v0.5.10 do PC `10.0.0.187:40992`. A v0.5.10 contém o mesmo código de
comunicação, com numeração nova. Ambas as tentativas autenticaram, receberam
a oferta correta e enviaram a aceitação.

| Sessão do PC | Sessão do DS | Bytes da imagem recebidos | Resultado |
| --- | --- | ---: | --- |
| `9b6816cb6e4d4cb3` | `114773-1` | 4.096 | Timeout no PC e no DS |
| `9c09a72f5d804ff3` | `188269-2` | 11.264 | Timeout no PC e no DS |

Os contadores TCP finais foram 4.168 e 11.336 bytes, incluindo os 72 bytes
do protocolo. A imagem completa tinha 1.402.368 bytes. O PC havia entregue
ao seu socket 5.120 e 12.288 bytes da imagem, respectivamente: em cada
falha havia um último bloco de 1.024 bytes sem confirmação.

O controle `mode=tcp-ack` estava ativo. Os checkpoints e o estado TCP no
Linux mostraram `unacked=1` e `notsent=0`, além de muitas retransmissões.
No último registro do DS, os contadores eram 43/43 e 73/73 para
`ccmp_rx/ccmp_valid`, com `mic_failed=0` e `rx_ram=ccmp_rx`. A atividade UDP
de diagnóstico continuou durante a espera.

Portanto, o envio de um segmento por vez **não resolveu** o download no
hardware real. Rajadas do próprio fluxo TCP não explicam sozinhas o
problema. A captura ainda não separa perda de quadros antes da recuperação
da RAM, perda na fila ARM7/ARM9, descarte no lwIP e perda do ACK de retorno.
Ausência de erros de MIC registrados não mede quadros que não chegaram ao
decifrador. A v0.5.10 não foi instalada nessas tentativas.

Captura preservada em `build/validation-0.5.10/hardware-wpa2-20261017.jsonl`
e resumo em `build/validation-0.5.10/hardware-summary.json`.

### Contador da tela observado pelo usuário

O usuário informou que as duas tentativas mostraram somente 512 bytes.
Isso é compatível com `progress()` em `source/app.cpp`: ele redesenha o
texto de bytes somente quando muda a porcentagem inteira. O primeiro
progresso de 512 bytes aparece como 0%; tanto 4.096 como 11.264 bytes
continuam abaixo de 1% dos 1.402.368 bytes. O texto pode, portanto, ficar
parado em 512 mesmo após novos dados ou blocos gravados.

O contador dos logs mede bytes recebidos pelo socket, não uma confirmação
de gravação durável ou de validação SHA-256. Em `source/update.cpp`, o
primeiro bloco tem 512 bytes e os seguintes têm 4.096; um bloco ainda
incompleto no `wire.read()` não chega ao `fwrite()` nem ao callback visual.
Os valores TCP, os blocos entregues ao arquivo e o texto exibido são
medidas distintas. A interface tem uma falha de atualização da contagem.

## Investigação e correção local na v0.5.11

O último bloco de 1.024 bytes enfileirado pelo PC não aparece no contador
de leitura do DS em nenhuma das duas tentativas. Portanto, a entrega ao
atualizador já deixou de avançar; o registro não demonstra apenas um ACK
perdido depois de uma leitura concluída. Isso ainda não localiza o descarte
entre rádio, fila, pilha e socket.

Foi reproduzida uma perda no código do console: `Wifi_NTR_WpaProcessRx()`
avançava o PN de replay antes de `Wifi_RxArm9QueueAdd()`, que podia falhar
por falta de espaço. A recuperação também gravava o hash da imagem como
processado. Liberar a fila depois disso não permitia entregar o mesmo
quadro, embora permanecesse íntegro na RAM. A fila normal consumia o
cursor do quadro descartado.

A v0.5.11 verifica espaço antes da autenticação e preserva o quadro
pendente. O teste falhou em cinco verificações antes da correção e passa
depois dela, incluindo retomada e ausência de entrega duplicada. Não havia
telemetria de fila nas capturas anteriores: esse defeito local não deve
ser apresentado como causa física já confirmada.

Foram adicionados contadores por etapa, sequências TCP e números dos ACKs
enfileirados/cifrados para localizar o próximo travamento sem depender do
contador visual. O formato está em `release-0.5.11.md`. O texto dos bytes
também foi corrigido e tem teste no código real da interface.
