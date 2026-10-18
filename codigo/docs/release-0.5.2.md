# Chest Link 0.5.2 — estado do servidor no console

No topo, o app mantém a rede Wi-Fi, troca o IP local do console por `IP-server`
e mostra o endereço anunciado pelo servidor Chest Link do PC. O estado agora
reflete a descoberta local do servidor: “procurando”, “conectado” ou “não
encontrado”. A checagem de acesso à internet foi removida.

## Verificação

- `make -C codigo console-ports-test test mailbox-test gui-test`: passou. A
  etapa gráfica foi repetida após ajustar duas asserções antigas da interface
  web para corresponder à implementação existente.
- `make -C codigo release`: compilou e publicou o par sincronizado DS/3DS v0.5.2.
- `make -C codigo e2e-ds`: passou no melonDS; o menu, a faixa sem servidor e a
  box sintética `e2e` foram conferidos.
- `make -C codigo e2e-3ds`: passou no Azahar; menu e faixa sem servidor foram
  conferidos.
- `sha256sum -c SHA256SUMS.txt`: os oito arquivos passaram.

Os dois emuladores estavam sem rede associada, então confirmaram o estado
“não encontrado”; não testaram a descoberta de um servidor ativo. melonDS usa
uma rede virtual e não se associou ao Wi-Fi real `MatheusFKovaleski`. Nenhum
console físico foi testado.

## Binários publicados

- DS: 1.329.664 bytes, versão 0.5.2.
- 3DS: 1.291.788 bytes, versão 0.5.2.
