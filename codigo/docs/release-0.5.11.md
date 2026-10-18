# v0.5.11 — recepção WPA2 e diagnóstico do transporte

## Correção reproduzida

No driver NTR, a autenticação CCMP avançava o contador de replay antes de
confirmar espaço na fila compartilhada ARM7/ARM9. Se essa fila estivesse
cheia, o quadro era descartado depois de consumir seu número de pacote.
Na recuperação da RAM, o cache também o marcava como já processado. Mesmo
liberando a fila, o mesmo quadro íntegro não podia mais ser entregue.

O driver verifica o espaço antes de autenticar e marcar o quadro. A fila
normal preserva o cursor do quadro pendente; a recuperação preserva a
possibilidade de tentar a mesma imagem de RAM novamente. A validação MIC
e a proteção contra replay continuam obrigatórias.

Um teste reproduziu cinco falhas antes da mudança: avanço prematuro do
replay, avanço do cursor e ausência de entrega após liberar a fila. Os
dois caminhos passam depois da correção. A simulação também verifica que
uma segunda consulta não entrega novamente o quadro já aceito.

**Esse defeito está comprovado em teste local. Os logs antigos não mediam
fila cheia e não provam que ele causou os dois travamentos no DS físico.**

## Diagnóstico para localizar a falha física

O campo `radio` dos logs do SD e do PC passa a registrar:

| Campo | Leitura |
| --- | --- |
| `rxq=A/B/C/D` | Quadros enfileirados pelo ARM7 / retirados pelo ARM9 / perdas da fila / tentativas adiadas por falta de espaço. |
| `lwip=A/B` | Entregas aceitas pela entrada da pilha / descartes por alocação ou recusa da entrada. Aceitação aqui ainda não prova aceitação pelo TCP. |
| `tcp-rx=N:SEQ+LEN/PORT` | Último segmento com dados observado depois de autenticar CCMP: contador, sequência, tamanho dos dados e porta local. Ainda não passou pela validação TCP. |
| `tcp-in=N:SEQ/EXPECTED` | Último segmento com dados que passou pelo checksum TCP e encontrou uma conexão estabelecida; sequência recebida / sequência esperada antes de processá-lo. |
| `ack=N:VALUE/M:RADIO_VALUE` | ACKs da conexão observada enfileirados pelo ARM9 / cifrados e entregues ao rádio pelo ARM7, com os respectivos números de confirmação. Isso não comprova recepção pelo PC. |
| `txrej=N` | Recusas de enfileiramento de saída. |

Os contadores são cumulativos. A comparação deve usar amostras da mesma
conexão e sua porta local. Nenhuma senha, chave, PIN ou conteúdo do arquivo
é incluído nesses novos campos.

## Feedback

O texto dos bytes passa a ser redesenhado quando a quantidade muda, mesmo
que a porcentagem ainda seja 0%. Um teste chama o código real da interface
com 512, 4.608 e 8.704 bytes e exige as três contagens. Essa correção visual
é independente da correção da fila de recepção.

Redesenhar mais vezes expôs o custo do escalonamento de imagens: o renderer
dividia coordenadas por pixel em CPUs sem divisão inteira por hardware.
O escalonamento agora acumula o passo e o resto da divisão, preservando
os mesmos pixels, recorte e transparência. Isso permite manter a contagem
de bytes atualizada sem refazer centenas de milhares de divisões em cada
aviso de progresso.

## Validação

DS e 3DS usam a versão única de `include/version.hpp`. O 3DS mantém seus
serviços nativos de rede; recebe a correção compartilhada de feedback.

Resultados e evidências desta rodada ficam em `build/validation-0.5.11`.
O par foi publicado por `make -C codigo release`; o servidor do PC em
execução ofereceu a versão 1291 com os hashes dos dois arquivos publicados.

| Verificação final | Resultado |
| --- | --- |
| WPA2 / RAM RX simulada / fila / DHCP e TCP reais | 166 / 506 / 1.485 / 58 verificações passaram. |
| ASan/UBSan dos três testes de transporte | Passaram. |
| Escala / telas completas antes e depois | 60 casos e 20 telas com pixels idênticos; ASan/UBSan passou. |
| melonDS | 1.409.536 bytes baixados, hash validado e executável instalado. |
| Azahar | 1.396.160 bytes baixados, hash validado, executável instalado e backup anterior distinto preservado. |

O comando exigido `make -j2 -k -C codigo console-ports-test test mailbox-test
gui-test` foi executado. Os testes de portas, protocolo, mailbox e renderer
passaram. A suíte geral ainda retorna erro pelas duas falhas anteriores:
expectativa de espécie/nome em um teste Sinnoh e expectativa literal do menu
antigo em `test_interface`. Esses trechos não foram alterados nesta rodada.

Antes dos resultados finais houve um timeout no melonDS após 922.112 bytes
gravados e uma execução do Azahar sem IPv4 antes da transferência. As duas
tentativas foram preservadas no relatório; a causa exata de cada uma não
foi isolada. A comparação de pixels e a transferência final passaram depois
da otimização do renderer, sem alterar a rede do aplicativo 3DS.

Os emuladores exercitam download, hash e instalação em armazenamento
privado. A rede virtual aberta do melonDS não valida a recepção WPA2 do
rádio NTR físico. Ainda é necessário executar esta versão no console para
verificar se o travamento original foi resolvido ou localizar a etapa
restante pelos novos registros.

A versão antiga continua usando seu driver antigo durante o download.
Para exercitar a correção, a v0.5.11 precisa ser instalada no DS pelo SD ou
pela rede WEP que já funciona, antes de testar uma transferência em WPA2.
