# Chest Link 0.5.6 — logs da atualização pelo PC

O DS e o 3DS registram cada etapa da atualização: descoberta e conexão,
autenticação sem gravar o PIN, oferta recebida, decisão, bytes enviados ou
recebidos, progresso, falhas e resultado. Eventos são gravados em JSONL no
armazenamento do console, ao lado do app, e enviados por UDP ao PC durante a
sessão autenticada. O PC acrescenta os eventos do TCP e do console a
`update-communication.jsonl` na pasta de dados do servidor.

No DS NTR conectado a WPA2, os registros incluem amostras de CCMP, falhas MIC e
contadores de quadros descartados. Durante uma espera sem tráfego, o app grava
um checkpoint de ociosidade a cada 10 segundos. O logger não registra o PIN, a
senha Wi-Fi nem o conteúdo do arquivo transferido. Se o servidor não suportar o
canal UDP, o log local do console continua disponível.

## Validação

- `make -C codigo release`: par DS/3DS v0.5.6 compilado, validado e publicado.
- `sha256sum -c SHA256SUMS.txt`: todos os arquivos do pacote conferidos.
- `make -C codigo console-ports-test`: passou, incluindo testes de estado e
  recuperação de rede nativa.
- `make -C codigo test`: 29 grupos principais, 9 grupos ExtData e as verificações
  WPA2 simuladas passaram. A suíte Python terminou com uma falha preexistente no
  parser Sinnoh: o fixture espera `Bayleef`, mas o parser retorna `Typhlosion`.
- `make -C codigo mailbox-test`: 43 testes passaram, incluindo a autenticação e
  persistência da telemetria do atualizador.
- `make -C codigo gui-test`: 5 grupos C++ passaram. A suíte Python teve uma
  falha em uma asserção antiga que espera o menu DS sem as opções atuais
  “Configurar Wi-Fi” e “Ler saves Pokemon”.
- O app v0.5.6 completou no melonDS uma atualização de 1.400.320 bytes para uma
  versão de teste posterior. `update_result=installed` aparece no JSONL local e
  no log do PC. A emulação usou uma rede aberta (`security=open`).

Não houve teste em console físico nem na WPA2 `Matheusfkovaleski`; portanto, os
contadores WPA2 reais ainda precisam ser coletados para identificar a causa da
falha nessa rede.
