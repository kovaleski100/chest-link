# Política de versões dos consoles

- Toda versão do DS deve ter um executável 3DS compilado com o mesmo número.
- A versão única está em `codigo/include/version.hpp`. Nunca fixe versões nos
  banners, ícones ou manifests separadamente.
- Porte funcionalidades compartilháveis. No 3DS, use os serviços nativos para
  rede, WPA/WPA2 e DHCP; não replique drivers/configuração do DS sem pedido
  explícito do usuário. Se a mudança for exclusiva do DS, recompile o 3DS com
  o número novo mesmo sem alterar seu comportamento.
- Use `make -C codigo release` para compilar, validar e publicar o par. Para
  só compilar, `make -C codigo consoles`. `tools/package.py` também rejeita
  pares fora de sincronia, manifests/hashes inválidos e banners antigos.
- Rode `make -C codigo console-ports-test test mailbox-test gui-test` antes de
  publicar. Informe separadamente compilação/testes locais e validação no
  hardware real; não declare uma conexão ou transferência real sem evidência.
- Preserve bancos, backups e alterações existentes. A atualização só limpa
  cópias antigas identificadas do app depois de iniciar a versão nova.
