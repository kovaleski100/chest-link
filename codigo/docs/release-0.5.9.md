# Chest Link v0.5.9

Tentativa de correção do download pelo PC no DS usando WPA2, orientada pelos
logs reais da v0.5.7. A tentativa registrada aceitou a oferta, mas recebeu
somente 5.040 bytes da imagem e terminou em timeout no PC.

## Alterações

- Envio ao DS com um segmento por vez e espera de confirmação TCP no Linux.
  O protocolo continua compatível com o app já instalado no DS. Outros
  sistemas usam envio pausado de blocos pequenos.
- ACK imediato de dados TCP no caminho NTR/WPA2, conservando as validações
  de sequência, checksum, janela e CCMP.
- Leitura imediata dos bytes já disponíveis no socket. A thread de rede
  continua recebendo tempo de execução quando o socket precisa aguardar;
  cada bloco disponível deixa de exigir uma espera extra de VBlank.
- Primeiro progresso após 512 bytes, seguido de blocos de 4 KiB para evitar
  excesso de pausas de tela e gravações pequenas. Limite de 30 segundos sem
  atividade após a aceitação; a confirmação humana continua separada.
- Logs distinguem bytes enfileirados de segmentos confirmados pelo DS.
- DS e 3DS usam o mesmo número de versão. O 3DS utiliza sua rede nativa.

## Validação

- `make -C codigo release`: par DS/3DS v0.5.9 compilado, validado e publicado.
- `console-ports-test`: passou, incluindo primeiro progresso, troca do prazo
  depois da confirmação, leitura sem VBlank com dados prontos e prazo sob
  repetidas respostas `EAGAIN`.
- `mailbox-test`: 47 testes passaram, incluindo controle de um segmento por
  vez, fila de bytes não enviados, perda de ACK, alternativa pausada,
  compatibilidade e preservação das cópias instaladas.
- NTR WPA2: 166 verificações; RAM simulada: 470; fila: 1.431; associação: 37;
  IPv4: 27; DHCP/TCP: 53. Todas passaram. As 53 verificações DHCP/TCP também
  passaram com ASan/UBSan, incluindo ACK imediato somente em NTR/WPA2.
- Núcleo: 29 grupos passaram; adaptador ExtData: 9 grupos passaram.
- melonDS: os 1.402.368 bytes foram baixados, conferidos por SHA-256 e
  instalados no armazenamento privado do teste.
- Azahar: os 1.395.664 bytes foram baixados, conferidos por SHA-256 e
  instalados; a cópia anterior foi preservada e seu hash conferido.

A execução final de `make -k -C codigo console-ports-test test mailbox-test
gui-test` terminou com duas falhas já presentes antes da correção: a fixture
Sinnoh espera o nome Bayleef para a espécie 157 (o parser retorna Typhlosion),
e um teste de interface procura uma lista antiga de itens de menu. Os testes
dessas áreas foram mantidos; portanto a bateria geral não está inteiramente
verde. O registro completo está em `build/validation-0.5.9/checks.log`.

Resultados estruturados dos emuladores: `build/validation-0.5.9/`. O teste DS
usou `melonAP`, uma rede virtual aberta. Não valida o rádio físico em WPA2.
A transferência corrigida ainda requer validação no DS Lite real.

### Teste físico posterior em 17/10/2026

O DS Lite executando v0.5.9 tentou baixar a v0.5.10 duas vezes em WPA2.
Recebeu somente 4.096 e 11.264 bytes da imagem; ambas as tentativas
terminaram por timeout. O envio de um segmento por vez estava ativo e não
resolveu a falha física. Nenhum erro de MIC foi registrado. Evidência e
limites da conclusão: `docs/wpa2-communication-review.md` e
`build/validation-0.5.10/hardware-summary.json`.
