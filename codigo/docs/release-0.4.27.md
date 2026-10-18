# Chest Link 0.4.27 — correção da checagem Wi-Fi do 3DS

## Mudança

O indicador e a liberação da rede do 3DS agora consultam
`ACU_GetWifiStatus`: resposta válida e AP diferente de zero significam
conexão disponível. Não é mais exigido `ACU_GetStatus == 3` para inicializar
SOC e obter o IP. A leitura opcional do nome da rede não bloqueia um link
com IPv4 utilizável. Falha na consulta ou AP zero ainda limpam o IP antigo;
transferências e listener continuam exigindo um IPv4 válido.

Este é o critério utilizado pelo
[ftpd](https://github.com/mtheall/ftpd/blob/master/source/3ds/platform.cpp)
e pela espera de conexão da
[libctru](https://github.com/devkitPro/libctru/blob/master/libctru/source/services/ac.c).
Não há implementação nova de WPA2, DHCP ou configuração de rede.

O DS foi recompilado com o mesmo número 0.4.27, sem alteração funcional do
seu adaptador de Wi-Fi.

## Evidência e testes

- FTP real do console respondeu em `10.0.0.201:5000`; o executável instalado
  antes da correção tinha tamanho e SHA-256 iguais à publicação 0.4.26.
- O teste com AP disponível e `GetStatus` diferente de 3 falhou com o código
  0.4.26 e passou depois da mudança. O teste também verifica que a consulta
  antiga não é utilizada, desconexão/retorno, IP inválido, falha de SOC,
  indisponibilidade de SSID e timeout não bloqueante.
- Builds DS/3DS concluídos e manifests/banners conferidos para 0.4.27.
- Regressões locais: núcleo, ExtData, GUI, TCP, HTTP e testes DS existentes
  passaram. Ports de rede/atualização passaram com ASan/UBSan, sem detecção
  de vazamentos neste ambiente.
- Seis testes do instalador FTP cobrem hash divergente, preservação do
  original, instalação repetida, rollback e falha de recuperação.
- Entrega FTP da 0.4.27 concluída e verificada relendo os arquivos finais:
  `ChestLink_3DS.3dsx` e `ChestLink_3DS.smdh` na pasta original. O executável
  0.4.26 ficou em `ChestLink_3DS.3dsx.previous4` com recibo de preservação.
  Nenhum banco foi alterado. Ambos os apps também estão publicados no PC.

O estado de rede dentro do novo app ainda precisa ser validado pelo usuário
no console; um FTP funcionando não comprova a execução do Chest Link novo.

## Entrega FTP

`tools/install_3ds_ftp.py` exige um par DS/3DS validado. Envia o 3DSX e o SMDH
para arquivos temporários na pasta atual, relê seus bytes e confere SHA-256
antes de substituir os nomes finais. Preserva os arquivos anteriores em
nomes livres e deixa um recibo que o app usa para remover somente seu backup
verificado após a nova versão iniciar. Backups antigos sem identificação e
todos os bancos permanecem intocados.
