# v0.5.12 — versão de teste

Esta versão só incrementa a numeração de v0.5.11 para v0.5.12 (código 1292)
para permitir o teste de atualização solicitado. O mesmo executável 3DS foi
compilado e publicado junto com o DS.

## Artefatos publicados

| Console | Tamanho | SHA-256 |
| --- | ---: | --- |
| DS | 1.409.536 bytes | `0532e48919d06c905f5f810aa3caaaf3c32cab4c236332c70c224665d0f77a20` |
| 3DS | 1.396.160 bytes | `7d772f3c46149a1f3d8436926192a89e1eb00df37e179ed86a8081e877d0aa67` |

`make -C codigo release` validou e publicou o par. `sha256sum -c
SHA256SUMS.txt` passou para os oito arquivos do pacote.

## Testes da atualização

- melonDS: baixou 1.409.536 bytes, instalou o executável e confirmou o hash.
- Azahar: baixou 1.396.160 bytes, instalou o executável e confirmou o hash.
- O servidor do PC em execução ofereceu v0.5.12 para DS e 3DS. A verificação
  autenticada local recusou cada oferta antes do download.
- Evidências dos emuladores: `build/e2e/run-20261017T191431Z-544726-32253e`
  e `build/e2e/run-20261017T191540Z-545370-b34fe9`.

O teste sequencial de portas passou; `mailbox-test` passou (47 testes) e os
cinco grupos nativos de GUI passaram. A suíte `test` ainda falha no fixture
Sinnoh que espera o nome Bayleef para a espécie 157, e `gui-test` falha na
asserção de integração que espera a lista antiga do menu DS. Não houve
alteração funcional no código nesta versão.

Os emuladores usaram armazenamento privado e rede virtual; isso valida a
oferta, a transferência, o hash e a instalação, mas não testa o rádio WPA2 do
DS físico. A falha WPA2 original continua pendente de validação no console.

## Tentativa física observada depois da publicação

Em 19:21:50 UTC, o DS físico autenticou no servidor, aceitou a oferta v0.5.12
e iniciou o download. A instalação não terminou, então o DS continua rodando
uma versão anterior à v0.5.12; esta tentativa não exercitou o código novo.

O servidor conseguiu confirmar 13 blocos de 1.024 bytes. No 14º havia um
segmento TCP pendente (`unacked=1`, `notsent=0`) quando expiraram os 30
segundos. A telemetria do DS registrou 13.384 bytes lidos do fluxo, incluindo
64 bytes de protocolo, a resposta de início de 8 bytes e os 13 blocos. O
último segmento de dados passou pela autenticação CCMP e pelo checksum TCP.

Na última amostra: `rxq=491/491/0/0` (sem perda ou backpressure),
`lwip=484/0` (sem descarte registrado) e `mic_failed=0`. O DS enfileirou 27
ACKs e registrou o mesmo valor de confirmação após entregá-los ao rádio; o PC
recebeu confirmações dos blocos anteriores, mas não do segmento pendente.
Isso comprova a etapa até a entrega ao rádio, não a recepção do último quadro
pelo ponto de acesso. Os registros atuais não identificam por que o próximo
segmento TCP não chegou ao processamento do DS.

Evidência: `PC/dados/update-communication.jsonl`, sessão
`56ed1ad3b5494837`, e telemetria remota `tcp_idle_checkpoint` às 19:22:05 e
19:22:15 UTC. Para testar o código da v0.5.12 no rádio WPA2, primeiro é
necessário instalar essa versão no DS via SD ou pela rede WEP já funcional.
