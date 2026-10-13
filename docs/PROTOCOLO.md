# Protocolos Chest Link 0.4.3

Na conexão direta, os dois consoles usam IPv4/TCP na rede local, porta padrão 40991. O receptor abre o servidor; o emissor conecta ao IP mostrado na tela. O PIN vale para uma sessão. O protocolo direto v1 permanece compatível com Chest Link 0.1.

Na caixa postal, o PC escuta na porta 40992 e os consoles iniciam as conexões. O PC usa um PIN persistente e conserva os pacotes depois de entregá-los. O listener do console permanece disponível para conexões diretas, mas não consulta a caixa postal: o envio da caixa postal ao console é iniciado manualmente na interface do PC. Não há nuvem, negociação de troca do jogo ou dependência dos servidores da Nintendo.

Todos os inteiros são `uint32` little endian. O protocolo depende de leituras e escritas exatas; o adaptador de sockets trata operações parciais, desconexão, cancelamento e limite de espera. O limite de inatividade é 180 segundos; a conexão inicial tem 20 segundos, e a espera por um cliente tem dez minutos. O receptor aceita uma sessão por execução de “Receber”.

## Sequência direta v1

1. Emissor envia `CHESTLNK` (8 bytes), versão `1` (4 bytes) e PIN numérico (4 bytes).
2. Receptor valida versão/PIN e responde.
3. Emissor envia a oferta de 52 bytes.
4. Receptor verifica limites e pede confirmação no próprio console. Responde aceitando ou recusando.
5. Emissor envia os bytes de `.bnk`, seguidos dos bytes de `.json` dos nomes.
6. Receptor valida a oferta, os arquivos e o digest; cria um banco novo e atualiza o cadastro com diário de recuperação.
7. Receptor envia confirmação final com o nome do banco. Se a confirmação se perder, a origem permanece intacta e o receptor pode já ter a cópia completa.

## Oferta

| Offset | Bytes | Campo |
|---:|---:|---|
| 0 | 4 | Quantidade de boxes |
| 4 | 4 | Quantidade de slots ocupados |
| 8 | 4 | Máscara de gerações, bit na posição do ID de armazenamento |
| 12 | 4 | Bytes do banco: `16 + boxes × 30 × 336` |
| 16 | 4 | Bytes do JSON de nomes |
| 20 | 32 | SHA-256 de `bnk || json`, nessa ordem |

A oferta não contém caminhos ou nomes de arquivos escolhidos pelo emissor. O receptor escolhe localmente `link0001` a `link9999`, verifica colisões e conserva o cadastro existente.

Limites: 1–500 boxes, no máximo 30 registros por box, JSON de até 256 KiB e gerações suportadas pelo destino. O JSON de nomes deve ser um array com exatamente uma string por box. IDs, contagens e hash devem corresponder ao conteúdo recebido. Limites são verificados antes de receber o corpo.

## Resposta

`status` (4 bytes), `length` (4 bytes), mensagem UTF-8 (`length` bytes, no máximo 384). Status `0` representa sucesso e `1` representa recusa/erro. Na resposta final de sucesso, a mensagem é o nome do banco criado.

## Persistência

Os arquivos de staging são gravados em `chest-link/`. O receptor verifica o pacote, copia o cadastro anterior para `registryNNNN.json`, grava e sincroniza um diário contendo hash do pacote, hash do cadastro anterior e nome do novo banco. O par `.bnk`/`.json` é escrito e conferido antes da atualização do cadastro. O diário é removido após a confirmação da gravação.

Ao reiniciar, o app aceita uma importação já registrada somente se o novo banco e os nomes passam na conferência. Caso contrário, restaura o cadastro anterior a partir da cópia com hash válido. O diário é mantido até essa recuperação terminar. Os arquivos temporários ou não cadastrados desta transação podem ser removidos; bancos anteriores não são apagados.

ExtData usa arquivos previamente alocados no tamanho exato e os serviços FS do 3DS. Onde rename não é suportado, o adaptador copia para um destino ausente e apaga a origem temporária somente após flush/close. A substituição do cadastro é protegida pelo diário; não existe promessa de atomicidade física sob falha do cartão ou da energia.

## Limites de confiança

O PIN é transmitido sem criptografia. SHA-256 serve para detectar corrupção dos bytes; ele não autentica um aparelho contra um invasor da rede. O receptor exige confirmação local de cada oferta e o protocolo nunca aceita caminhos remotos. A origem nunca é apagada, mesmo quando a confirmação final chega.

## Caixa postal v1 — porta 40992

Cada operação abre uma conexão nova. O cabeçalho inicial tem 20 bytes:

| Offset | Bytes | Campo |
|---:|---:|---|
| 0 | 8 | ASCII `CLMAIL01` |
| 8 | 4 | Versão `1` |
| 12 | 4 | PIN numérico do PC |
| 16 | 4 | Comando: `1` upload, `2` lista, `3` busca |

O PC valida o cabeçalho e responde com o mesmo frame de resposta de 8 bytes + mensagem usado acima. A oferta de 52 bytes e o corpo `bnk || json` também são os mesmos. Comandos: `1` upload, `2` lista, `3` busca/entrega manual ao console e `4` atualização do app 3DS. Em upload, `0` significa cópia guardada no PC sem destinatário; `1` é DS e `2` é 3DS. Em lista, o valor `0` é um filtro que significa “todos os destinos” e requer `includeDelivered=1`; não é um destino de entrega. Busca exige `1` ou `2` e nunca recebe diretamente uma cópia com destinatário `0`.

### Upload — console → PC

1. Após autenticar, o console envia destinatário (`u32`), tamanho do rótulo (`u32`, 1–63), rótulo UTF-8 e oferta de 52 bytes. O rótulo serve apenas para exibição e não é usado como caminho.
2. O PC verifica tamanhos e capacidade. Para destinatários `1` e `2`, também verifica a compatibilidade de gerações. Para `0`, guarda a cópia sem atribuir destino e aceita a máscara de gerações do catálogo atual; a compatibilidade fica para quando o usuário escolher DS ou 3DS no PC. O identificador é `hex(SHA256(LE32(destinatario) || digest_da_oferta))[0:32]`. A identidade se refere ao conteúdo mais o destino (inclusive o estado sem destino); o rótulo não altera a identidade.
3. Se a cópia já estiver publicada e válida, o PC responde sucesso com `STORED <id>`. O console encerra sem reenviar o corpo. Um pacote existente com descrição diferente ou hash danificado não é substituído.
4. Caso contrário, o PC reserva capacidade e responde `READY`. O console transmite banco e nomes em blocos.
5. O PC verifica tamanho exato, cabeçalho v3, nomes UTF-8, contagens de registros/gerações e SHA-256. Sincroniza banco, nomes e metadados em um diretório temporário e publica por rename para `items/<id>/`.
6. O PC responde sucesso com o ID somente depois da publicação. Uma queda antes disso pode deixar uma cópia já publicada; repetir o mesmo envio reconhece seu ID.

### Lista — console → PC

O console envia filtro de destinatário (`u32`), incluir entregues (`u32`, 0/1) e offset (`u32`). Filtro 0 exige incluir entregues=1 e retorna todos os itens, inclusive os sem destino. O PC responde sucesso, seguido de tamanho (`u32`, até 64 KiB) e JSON:

```json
{"items":[],"next":0,"total":0}
```

Cada item contém `id`, `target` (`0` sem destino, `1` DS, `2` 3DS), `label`, `delivered` e os seis campos da oferta: `boxes`, `occupied`, `generations`, `bankBytes`, `namesBytes`, `hash` (hex de 64 caracteres). Todos os campos numéricos são inteiros sem sinal; não há booleanos/null. As páginas têm até 32 itens, ordenados por data de criação e ID. `next=0` indica última página. Metadados, IDs, tamanho de página e paginação são verificados pelo cliente antes de exibir.

### Busca/entrega — PC → console

1. O console envia destinatário (`u32`), ID ASCII de 32 bytes e flags (`u32`: 0=entrega; 1=recuperação de backup sem consumir a pendência). Este comando é usado somente para item já atribuído a DS ou 3DS; item sem destino não pode ser buscado pelo console.
2. O PC verifica se o pacote pertence à fila indicada e confere novamente seus arquivos. Responde sucesso e envia a oferta de 52 bytes.
3. O console aplica os limites do armazenamento local e verifica o ID derivado do digest. Se aceitar, responde `READY`; se recusar, responde erro e a pendência permanece.
4. O PC envia banco e nomes. O console verifica os arquivos, procura um `linkNNNN` já registrado com conteúdo e nomes exatamente iguais e o reutiliza, ou importa um banco novo pelo diário de recuperação.
5. Durante a procura de um banco idêntico, o console pode enviar respostas `VERIFY`, que mantêm a conexão ativa e não confirmam entrega. Depois de verificar e gravar o banco, responde sucesso com `linkNNNN`. Se a conexão se perder aqui, a cópia local continua válida. A próxima busca pode reutilizá-la, sem criar um banco duplicado.
6. Para flags=0, o PC grava atomicamente `delivered=1`; para flags=1, conserva o estado existente. Responde `DELIVERED` ou `BACKUP`, respectivamente. Os arquivos do pacote permanecem no PC em ambos os casos.

O modo de recuperação de backup permite ao console de origem receber uma cópia destinada ao outro sem consumir a pendência do destinatário. A interface oferece por padrão as pendências do próprio aparelho; a lista de todos os backups inclui os dois destinos e as cópias sem destino. As gerações e o limite de boxes do armazenamento local continuam sendo exigidos.

### Encaminhamento manual pelo PC

O console envia uma cópia sem destinatário (`target=0`) e não recebe oferta de transferência de volta por causa desse upload. Na interface do PC, o usuário escolhe explicitamente **Enviar seleção ao DS** ou **Enviar seleção ao 3DS**, seleciona os Pokémon e informa IP/PIN do console. O servidor cria uma cópia de entrega com `target=1` ou `2`, valida nesse momento as gerações compatíveis e inicia a conexão direta v1 na porta 40991. O console precisa estar com o listener ativo e ainda confirma localmente antes de gravar. A cópia original sem destino continua no PC; o servidor registra separadamente o estado da cópia encaminhada.

O botão **Limpar pendências** da interface tira, após confirmação, os itens destinados ao DS/3DS que ainda não foram entregues da fila do console. Os arquivos e metadados permanecem no PC como backup e continuam disponíveis na Pokédex. O console deixa de listar esses itens até que o usuário os selecione e envie novamente pelo PC. Cópias sem destino (`target=0`) e itens já entregues não são alterados. A operação é manual e não faz parte de uma transferência automática do protocolo.

### Atualização de apps — comandos 4 e 5

Após o cabeçalho autenticado, o servidor informa se há uma versão mais nova do app correspondente: comando `4` para o `.3dsx` do 3DS e comando `5` para o `.nds` do DS. Cada imagem tem seu próprio `release.json` (versão, tamanho e SHA-256). O cliente confirma antes de baixar e verifica o hash antes de concluir. O 3DS substitui o caminho fixo do app, mantendo `.previous`. No DS, o app usa o caminho informado pelo launcher compatível e grava a nova versão na mesma pasta; no primeiro início da atualização, procura em `fat:/` e `sd:/` e remove somente arquivos Chest Link antigos/duplicados com o padrão de nome do app, preservando a cópia em execução e versões mais novas. Se o launcher não informar o caminho, o fallback é a pasta padrão do armazenamento. A conexão de atualização não consulta nem altera itens da caixa postal.

### Persistência no PC

`config.json` conserva o PIN; `incoming/` contém somente uploads ainda não publicados. Cada pacote publicado tem `items/<id>/bank.bnk`, `names.json` e `meta.json`. Nenhuma busca remove esses arquivos. O servidor não escreve os bancos originais do Chest ou PKSM e não modifica saves de jogos.

Somente um processo pode usar a pasta de dados por vez. O servidor reserva espaço para uploads simultâneos, limita a 16 conexões ativas e recusa novos pacotes quando excedem a capacidade configurada. O padrão é 512 MiB de corpos e 1.000 pacotes, incluindo os já entregues. Na inicialização, somente arquivos incompletos de `incoming/` são limpos. Ao encerrar, conexões abertas são interrompidas e os uploads parciais são descartados.

Os arquivos são fechados com `flush` e `fsync` antes da publicação; metadados de entrega usam arquivo temporário + `os.replace`. Diretórios também recebem `fsync` em POSIX. A biblioteca padrão do Python não oferece `fsync` portátil de diretórios no Windows. Essas medidas reduzem os efeitos de interrupção, mas não garantem recuperação de corrupção física do disco/SD. Os testes foram executados no Linux; Windows e os serviços reais dos consoles ainda precisam de validação.
