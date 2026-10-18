# Chest Link 0.5.1 — tentativa manual de conexão ao PC

O app tenta conectar ao último IP salvo antes de buscar. Essa tentativa tem
limite de 1,5 s; se não houver resposta, faz a descoberta UDP e tenta o endereço
que responder. Se a busca não localizar um PC ou a conexão com o endereço
encontrado falhar, abre a tela de entrada manual do IP. Só mostra que o servidor
não foi encontrado depois que a tentativa manual também falha. O PIN salvo
continua disponível para autenticar o servidor.

No DS, a descoberta UDP usa socket não bloqueante, retransmite a cada ~350 ms
e tem limite de 180 quadros (cerca de 3 s a 60 Hz). A espera termina mesmo se o
contador de milissegundos ficar parado, e B cancela a operação.

## Verificação

- Regressão de rede DS: **passou**; relógio parado termina a busca em 180
  quadros (nove anúncios), cancelamento por B termina no quarto quadro, e uma
  conexão sem resposta ao IP salvo termina em 90 quadros para o limite de 1,5 s.
- `make -C codigo console-ports-test test mailbox-test gui-test`: **passou**.
  Inclui 28 grupos do core, 9 do adaptador ExtData, 40 testes de mailbox,
  32 de interface e os testes de portas/rede, WPA2, DHCP e timeout.
- `make -C codigo consoles`: **passou**; DS e 3DS v0.5.1 compilados como par.
- melonDS: **passou** no arranque e na abertura da box sintética `e2e`.
- Fluxo manual no melonDS: usei o `melonAP` virtual do emulador. A busca
  recebeu um endereço sem resposta TCP, abriu “PC sem resposta: informe IP” e
  o IP padrão de teste terminou na mensagem de servidor não encontrado.
- Fluxo manual no Azahar: sem IP salvo, a busca abriu “PC nao encontrado:
  informe IP”; o IP padrão de teste terminou na mensagem de servidor não
  encontrado.
- Esses testes cobriram somente os dois caminhos de fallback. Não validei no
  emulador o IP salvo que responde, o IP salvo que falha seguido de busca com
  conexão bem-sucedida, nem o IP manual correto.
- O host estava conectado ao Wi-Fi `MatheusFKovaleski`, mas a rota padrão do
  Linux usava Ethernet. O melonDS usa `melonAP` virtual e não se associou ao
  SSID real; portanto, os testes não validam essa rede WPA2.
- Servidor local: consulta de atualização autenticada, recusada antes do
  download, retornou v0.5.1 (1.329.664 bytes) para DS.
- Hardware real: ainda não testado.
- `make -C codigo release`: **passou**; par DS/3DS v0.5.1 publicado
  localmente. Os oito arquivos listados em `SHA256SUMS.txt` conferem.
