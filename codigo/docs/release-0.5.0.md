# Chest Link 0.5.0 — marco de funcionalidades

A versão compartilhada passou de 0.4.30 para 0.5.0 para marcar o conjunto de
funcionalidades acumuladas desde a linha 0.4.x. DS e 3DS continuam usando o
único número de `include/version.hpp`.

## Builds e validação local

- `make -C codigo console-ports-test test mailbox-test gui-test`: passou.
- Os testes incluíram núcleo, ExtData, WPA2/DHCP do DS, descoberta UDP do
  servidor, mailbox e interface gráfica.
- `make -C codigo release`: compilou os executáveis DS e 3DS com os SDKs
  instalados, conferiu versões, banners, manifests e hashes, e publicou o par
  na pasta do projeto.
- DS: `DS/ChestLink_DS.nds`, 1.328.640 bytes.
- 3DS: `3ds/ChestLink_3DS/ChestLink_3DS.3dsx`, 1.289.736 bytes.

## Emuladores e hardware

O executável DS chegou ao menu principal no melonDS; o 3DS chegou ao menu
principal no Azahar. As capturas foram feitas nos perfis isolados do laboratório.
O runner expirou aguardando confirmação manual do menu e da box sintética em
`Consultar bancos`. Como esta sessão não expôs controle de entrada para as
janelas, só foi possível confirmar o menu nas capturas; navegação da box e
transferências não contam como validadas nesta execução.

Os consoles físicos não foram testados com a versão 0.5.0. As capturas e os
testes locais não comprovam associação Wi-Fi nem transferência em hardware real.
