# Release v0.5.13 — retry da transmissão WPA2 no DS

## Motivo

As capturas WPA2 mostram que o DS recebe dados e calcula o ACK TCP esperado,
mas o PC mantém um segmento sem confirmação. Os contadores anteriores
confirmavam que o ACK entrava na fila e era cifrado; não mostravam o resultado
da transmissão no rádio.

## Alteração

- No caminho NTR/WPA2, o console consulta o estado do quadro ao concluir a
  transmissão.
- Se o cabeçalho indicar falha (`status 5`, código de falha usado pelo próprio
  driver no tratamento de transmissões multiplayer), o driver reenvia o mesmo
  quadro protegido até duas vezes. O bit Retry é marcado, mantendo o mesmo PN,
  número de sequência e conteúdo CCMP.
- A fila avança após o sucesso ou depois do limite de tentativas. WEP, rede
  aberta e DSi nativo mantêm o comportamento existente.
- Os logs agora incluem status bruto do rádio, falhas de ACK no rádio, tentativas
  extras e quadros que atingiram o limite.

## Validação

O teste local simula o cabeçalho e os registradores do MAC e verifica duas
tentativas adicionais, o limite, o bit Retry, a liberação da fila e a ausência
de repetição em WEP/rede aberta. Esse teste não simula a entrega real pelo rádio.

## Resultados locais

- `make -C codigo console-ports-test`: passou; incluiu nove verificações do
  publicador de par e seis de instalação FTP.
- O teste novo `nds-tx-retry-test`: passou, 24 verificações.
- `make -C codigo test`: os testes de WPA2, recepção simulada, fila, DHCP e
  associação passaram. A suíte terminou com uma falha fora desta alteração em
  `test_native_saves.py::SinnohParserTests::test_reads_sinnoh_trainer_party_box_dex_badges_story_and_points`:
  espécie 157 esperava o nome `Bayleef`, mas o parser retornou `Typhlosion`.
- `make -C codigo mailbox-test`: passou, 47 testes.
- `make -C codigo gui-test`: os cinco grupos C++ passaram; uma verificação de
  interface falhou porque ainda espera o menu antigo sem “Ler
  saves Pokemon”. Os outros 38 testes de interface passaram.
- `make -C codigo consoles` e `make -C codigo release`: compilaram e validaram
  o par DS/3DS v0.5.13; os dois manifestos conferem com os executáveis.

A validação WPA2 em um DS Lite físico permanece pendente. O próximo teste deve
observar `macfail`, `retry`, `txmac` e o ACK do PC nos logs. Se o cabeçalho
retornar status 5 após as duas tentativas extras, o log mostrará isso sem
afirmar que o ACK chegou ao ponto de acesso.
