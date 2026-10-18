# Chest Link 0.5.4 — feedback imediato ao aceitar atualização

Ao aceitar uma atualização, o app agora sai da confirmação e mostra a barra em
0% com a mensagem de que está aguardando o PC iniciar o envio. A porcentagem
e os bytes recebidos aparecem assim que os primeiros dados chegam.

## Verificação local

- `make -C codigo console-ports-test test mailbox-test gui-test`: passou.
- `make -C codigo consoles` e `make -C codigo release`: DS e 3DS compilados,
  validados e publicados juntos como v0.5.4.
- melonDS, app DS normal: A encerrou a confirmação e mostrou a tela de espera
  durante uma pausa forçada de cinco segundos na resposta do servidor. Também
  recebeu e instalou o binário DS publicado completo (1.329.664 bytes); o
  arquivo no armazenamento isolado do emulador bateu byte por byte com o
  publicado.
- Azahar: o fluxo de atualização 3DS recebeu e instalou o binário v0.5.4; o
  SHA-256 instalado correspondeu ao executável compilado.
- `sha256sum -c SHA256SUMS.txt`: todos os arquivos publicados passaram.

## Hardware

Não testado em console físico. O melonDS usou sua rede virtual `melonAP`, não a
rede WPA2 `Matheusfkovaleski`.
