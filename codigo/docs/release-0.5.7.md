# Chest Link 0.5.7 — recepção WPA2 QoS no DS

O caminho NTR do DS agora aceita quadros QoS Data protegidos por WPA2. O
verificador CCMP usa o cabeçalho e o TID do quadro, valida o MIC com o AAD QoS
e mantém a proteção contra replay separada por prioridade. Quadros aceitos
seguem para o lwIP sem perder o cabeçalho QoS; quadros rejeitados pelo rádio
podem passar pela recuperação autenticada da RAM.

## Validação local

- `make -C codigo release`: par DS/3DS v0.5.7 compilado, validado e publicado.
- Testes NTR WPA2: fixture AES-CCM QoS independente, TIDs e replay, recuperação
  simulada de RAM e adaptação para lwIP passaram.
- `make -C codigo console-ports-test`: passou.
- `make -C codigo mailbox-test`: 43 testes passaram.
- `make -C codigo gui-test`: os 5 grupos C++ passaram; uma asserção Python
  antiga falhou porque ainda espera o menu DS sem as opções atuais.
- `make -C codigo test`: os grupos C/C++ passaram; uma asserção Python antiga
  do parser Sinnoh espera “Bayleef” para o species ID 157, mas o parser retorna
  “Typhlosion”.
- melonDS: o executável v0.5.7 foi transferido, verificado e instalado no
  armazenamento isolado. O emulador usa o ponto de acesso virtual aberto
  `melonAP`; isso não valida WPA2 no rádio físico.

Não houve teste em hardware real nem na rede WPA2 `Matheusfkovaleski`. A
compatibilidade final com o rádio do console ainda precisa ser confirmada no DS.
