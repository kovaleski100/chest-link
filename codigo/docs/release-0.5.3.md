# Chest Link 0.5.3 — download de atualização no DS

O DS e o servidor do PC agora permitem até dez minutos sem tráfego durante a
atualização. Esse limite cobre o tempo para aceitar a oferta e pausas entre os
blocos do download. O botão B continua cancelando; o app só instala o arquivo
depois de conferir o tamanho e o SHA-256.

## Verificação

- `make -C codigo console-ports-test test mailbox-test gui-test`: passou.
- `make -C codigo e2e-harness-test`: passou.
- melonDS: recebeu, conferiu e instalou a atualização DS v0.5.3; hash do
  executável instalado igual ao binário publicado. Também confirmei a oferta
  manualmente com A e completei a transferência.
- Azahar: recebeu, conferiu e instalou a atualização 3DS v0.5.3; hash igual
  ao binário publicado e cópia anterior preservada.
- `make -C codigo release`: publicou o par DS/3DS v0.5.3 sincronizado.
- Hardware real: não testado. melonDS usa `melonAP` virtual; o teste não se
  conectou ao Wi-Fi WPA2 `Matheusfkovaleski`.

## Binários publicados

- DS: 1.329.664 bytes, versão 0.5.3.
- 3DS: 1.291.944 bytes, versão 0.5.3.
