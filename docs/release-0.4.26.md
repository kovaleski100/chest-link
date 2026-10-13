# Chest Link 0.4.26 — DS e 3DS sincronizados

Nota posterior: o usuário observou falso “OFF” no 3DS 0.4.26 enquanto o FTP
funcionava. A consulta de rede foi corrigida na
[0.4.27](release-0.4.27.md). Os resultados abaixo são o registro dos testes
locais da 0.4.26, não uma validação física dessa consulta.

## Portado para o 3DS

- Ícone Wi-Fi ON/OFF, SSID e IPv4 da conexão atual, amostrados a cada segundo.
  Estado nativo desconectado ou consulta com falha apaga o SSID/IP anterior.
  Uma associação sem IPv4 utilizável não habilita transferências.
- Verificação de alcance TCP da internet a cada 30 segundos, sem bloquear
  os controles e com limite de quatro segundos. A indicação não comprova
  DNS/TLS; transferências locais continuam possíveis sem internet.
- Listener acompanha perda e retorno da conexão, troca de SSID e de IP;
  fecha o endpoint antigo, tenta reabrir em intervalos limitados e mantém o
  PIN. Ouvir a rede não inicia envio pelo PC: isso continua manual, com
  confirmação no console antes de importar.
- Atualização do `.3dsx` no caminho real informado pelo launcher, inclusive
  em pasta personalizada. Há confirmação mostrando o destino e fallback
  explícito para o caminho padrão quando o launcher não informa a origem.
- Backup do executável anterior até abrir a versão nova. Sua remoção exige
  recibo da atualização, versão e SHA-256 de ambas as cópias conferidos.
  Arquivos de versões anteriores com nome `ChestLink_3DS_v*.3dsx` também
  são limpos na pasta do app. A comparação do caminho protege a cópia
  atual mesmo com diferenças de maiúsculas/minúsculas no cartão.
  Backups não identificados, versões futuras e todos os bancos permanecem.
- Número da versão nos créditos, banner/ícone e manifesto; os dois builds
  usam `include/version.hpp`. O 3DS publicado anteriormente era 0.4.3.
- Recompilação com o código compartilhado atual de bancos e transferências:
  seleção de armazenamento PKSM transparente, formato tratado conforme o
  destino, transferências diretas e cópias via PC com backup preservado.
- Texto do menu esclarece que recebimento exige confirmação e não corta
  mais a indicação junto aos controles.

## Exclusivo do DS

Não foram portados ARM7/ARM9, WPA2/CCMP em software, recuperação da RAM do
rádio, alterações de quadros/FCS/MIC ou implementação DHCP. No 3DS, são
usados os serviços AC/SOC do sistema; configurações, senha e troca de rede
continuam nas definições do console. Não há um segundo menu de configuração
Wi-Fi nem alterações automáticas nos perfis do firmware.

Referências primárias consultadas:

- [Serviço AC da libctru](https://github.com/devkitPro/libctru/blob/master/libctru/include/3ds/services/ac.h): estado da conexão e SSID nativos.
- [Homebrew Launcher](https://github.com/devkitPro/3ds-hbmenu/blob/master/source/menu-entry.c): caminho de lançamento em argv e metadados SMDH incorporados.

## Política para próximas versões

`make consoles`, `make ds` e `make 3ds` compilam o par. `make release` também
publica os dois executáveis/manifests e atualiza os hashes. O verificador
confere versão, tamanho, SHA-256, banner DS e SMDH 3DS incorporado; rejeita
app antigo apenas renumerado no manifesto. O empacotador repete a validação.
Se uma implementação só fizer sentido no DS, o 3DS ainda recebe build com
o mesmo número. Esta regra está registrada em `AGENTS.md`.

## Validação desta versão

- Builds nativos BlocksDS e devkitARM/libctru concluídos para 0.4.26.
- Port de rede testado com AC/SOC e sockets simulados: desconexão, erro de
  consulta, IP antigo, retorno da rede, falha de SOC, timeout não bloqueante
  e tratamento de EINPROGRESS específico do SOC.
- Caminhos de instalação e preservação/limpeza testados com arquivos reais
  temporários; backup alterado ou binário errado nunca autoriza exclusão.
- Nove testes Python de publicação: par válido, versões divergentes, hash
  inválido, banner antigo, SMDH divergente, peer ausente, trava concorrente
  e restauração após falha de publicação. Se até a restauração falhar, a
  trava e os backups são preservados para recuperação manual.
- Regressão: 26 grupos do núcleo, nove ExtData, cinco GUI, 38 da caixa postal
  TCP e 28 da interface HTTP/decodificação passaram. Testes de Wi-Fi/DHCP do
  DS existentes também passaram. Renderizador 400x240 inspecionado no host.
- Núcleo, ExtData e ports novos passaram com ASan/UBSan; detecção de
  vazamentos desabilitada neste ambiente.

O 3DS 0.4.26 e a transferência DS↔3DS ainda precisam ser testados nos consoles
reais. O sucesso físico do DS 0.4.25 está registrado separadamente em
`diagnosticos/wifi-2026-10-12.md`; ele não é prova do teste do novo 3DS.
