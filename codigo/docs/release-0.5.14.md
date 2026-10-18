# Release v0.5.14 — teste do retry WPA2 no DS

## Motivo

Esta versão incrementa apenas a numeração para que o atualizador ofereça uma
nova versão. O código é o mesmo da v0.5.13, incluindo o retry de transmissão
WPA2 no DS e os contadores de resultado do rádio.

## Logs do console

Foram analisados 20 logs disponíveis no cartão. Todos identificam o app como
v0.5.7, v0.5.9 ou v0.5.11; não há um teste do app v0.5.13 em WPA2. Os três
downloads completos são de rede aberta. Nos 17 logs WPA2, nenhum download
completo foi instalado: 13 terminaram com falha/cancelamento, dois detectaram
que já estavam atualizados e dois foram cancelados na oferta. Os downloads
interrompidos receberam entre 72 e 13.384 bytes.

Os logs antigos mostram ACKs TCP enfileirados e cifrados, mas não registram o
resultado final da transmissão pelo MAC nem tentativas de retry. Eles, portanto,
não confirmam se o ponto de acesso recebeu os ACKs nem testam a correção da
v0.5.13.

## Validação local

- `make -C codigo console-ports-test`: passou, incluindo os testes do par DS/3DS
  e instalação FTP.
- `make -C codigo test`: verificações de WPA2, RX simulado, retry TX (24 checks),
  associação, fila, DHCP/TCP e demais grupos C++ passaram. A suíte Python
  terminou com uma falha não relacionada no teste Sinnoh: espécie 157 esperava
  `Bayleef`, mas recebeu `Typhlosion`.
- `make -C codigo mailbox-test`: passou, 47 testes.
- `make -C codigo gui-test`: os cinco grupos C++ passaram e 38 testes de
  interface passaram. Uma asserção ainda espera o menu antigo sem “Ler saves
  Pokemon”.
- Atualização em melonDS: passou; download completo, hash conferido e instalação
  no armazenamento isolado do emulador.
- Atualização em Azahar: passou; download completo, hash conferido e instalação
  no armazenamento isolado do emulador.
- `make -C codigo release`: compilou DS e 3DS, validou os dois manifests e
  publicou o par v0.5.14.

Os emuladores usam uma rede virtual aberta e não reproduzem a transmissão WPA2
do DS Lite. O teste do retry em hardware físico permanece pendente.
