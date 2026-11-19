# Changelog

What changed in each release of Pauta. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and versions follow
[Semantic Versioning](https://semver.org/). Write new entries under **Unreleased** as you
go; `scripts/release.py cut X.Y.Z` turns them into the next release's notes.

## [Unreleased]

## [1.14.1] - 2026-11-19

### Added

- **Aviso de versão nova em abas abertas.** Uma aba que fica aberta por dias continuava
  rodando a versão em que foi carregada, sem saber que saiu outra. Agora, depois de um
  lançamento, a aba mostra no alto da tela "A Pauta foi atualizada" com o botão
  "Recarregar". A Pauta não recarrega sozinha, para não perder um formulário pela metade.
  Vale para abas carregadas desta versão em diante: uma aba já aberta numa versão
  anterior precisa ser recarregada uma vez à mão.

### Changed

- **O logo leva para a tela inicial de quem escolheu uma.** Com uma "Tela inicial"
  escolhida em Perfil, o logo (na lateral e no alto do celular) abre essa tela em vez do
  Painel, que continua no menu. Sem escolha, nada muda. No celular isso também dá um
  caminho de volta ao Quadro quando ele não está na barra de baixo.

## [1.14.0] - 2026-11-18

### Added

- **Perfil: escolha a tela em que a Pauta abre.** Em Perfil há agora o campo "Tela inicial":
  Painel (como sempre foi), Quadro, Pedidos, Clientes e, para quem os vê, Campanhas e
  Financeiro. A escolha é da pessoa e vale em todos os aparelhos em que ela entra. Ela só
  decide onde a Pauta abre sem um endereço próprio (o ícone no celular, o endereço
  digitado): um link para um pedido continua abrindo o pedido. O Painel segue no menu e no
  logo, e se a tela escolhida sair de vista (a Meta desligada, o Financeiro escondido) a
  Pauta abre no Painel. O registro de uso passa a guardar a tela escolhida junto da
  abertura do app, para medir quem usa.

## [1.13.1] - 2026-11-17

### Changed

- **Campanhas com período Personalizado abre na hora.** Um período que o Pauta ainda não
  tinha lido na Meta (qualquer intervalo de datas escolhido à mão) fazia a página inteira
  esperar o alcance: de 6 a 9 segundos. Agora a lista aparece logo com os números
  guardados, a coluna Alcance mostra "…" enquanto a Meta responde, e cada número entra no
  lugar quando chega, sem a página piscar. Se a Meta não responder, fica o traço de sempre.
- **A primeira página depois de uma atualização do Pauta não espera mais a Meta.** A lista
  de contas de anúncio era lida um portfólio depois do outro (uns 7 segundos com quatro
  portfólios, de 15 a 17 com dez) e quem abrisse Painel, Campanhas ou Configurações
  primeiro esperava tudo isso. Agora os portfólios são lidos ao mesmo tempo, e a leitura
  começa quando o Pauta inicia, antes de alguém pedir. O alcance por período também é
  lido em todos os portfólios de uma vez.
- **O registro de uso guarda o formato do período Personalizado**: quantos dias e há
  quantos dias termina, nunca as datas. Serve para saber qual período rápido falta no
  seletor.
- **Em acceptance, a versão ao lado do nome ficou curta.** Um build de branch tem uma versão
  comprida (`1.13.1.dev41+g41acf5dab1f0`) que não cabia ao lado de "Pauta" e saía do lugar.
  Agora aparece só o começo do commit (`41acf5d`); a versão inteira continua no texto que
  aparece ao parar o mouse em cima e no fim de Configurações. Em produção nada muda:
  continua `v1.13.0`.

## [1.13.0] - 2026-11-15

### Added

- **Clientes: em cartões ou em lista, na ordem que você escolher.** Ao lado da busca há
  agora dois controles. O primeiro troca os cartões por uma lista, uma linha por cliente,
  com colunas para segmento, situação, pedidos em aberto, total de pedidos, último pedido e
  cliente desde. O segundo é o "Ordenar por", com esses mesmos campos e o nome; o botão ao
  lado inverte a ordem e diz como ela está ("A → Z", "Mais primeiro", "Mais recente
  primeiro"). Na lista, clicar no título de uma coluna ordena por ela, e clicar de novo
  inverte. Cada ordem começa do jeito mais útil: quem tem mais pedidos em aberto, o pedido
  mais recente, o cliente mais antigo. Clientes encerrados continuam no fim em qualquer
  ordem (menos na ordem por situação), e quem não tem o dado (sem segmento, sem pedido)
  vem depois de quem tem. A ordem por nome agora respeita os acentos: "Ótica" fica junto
  do "O", não depois do "Z". A escolha fica guardada no navegador de cada pessoa. No
  celular a lista vira linhas compactas, sem os títulos das colunas.

## [1.12.1] - 2026-11-15

### Changed

- **Arquivos do pedido: o envio ficou bem mais rápido, principalmente em lote.** Três coisas
  mudaram. Um arquivo de até 4 MB (quase todos: 37 dos 38 da semana medida) vai para o
  OneDrive em um pedido só, em vez de abrir uma sessão de envio antes: no OneDrive pessoal
  cada ida custa um segundo ou mais, qualquer que seja o tamanho. A página agora envia três
  arquivos ao mesmo tempo em vez de um por vez, e a fila inteira aparece de uma vez, cada
  arquivo com a sua barra. E a miniatura de uma imagem ou vídeo é buscada assim que o
  arquivo chega, sem esperar alguém abrir o pedido; se a página pede a mesma miniatura
  várias vezes enquanto o lote sobe, o OneDrive é consultado uma vez só. Medido no du7 com
  o OneDrive de verdade, sete arquivos de 2 MB: 22,6 s antes, 6,1 s agora; cada arquivo, de
  3,3 s para 1,9 s. O primeiro arquivo de um pedido ainda vai sozinho, porque é ele que cria
  a pasta do pedido. No fim de um lote o aviso é um só ("7 arquivos enviados"). Arquivos
  maiores que 4 MB continuam indo em partes, como antes.

## [1.12.0] - 2026-11-13

### Added

- **Painel: o card "Saldo acabando".** A primeira tela agora lista os clientes com o saldo
  de anúncios zerado ou que acaba dentro do prazo do time (o mesmo alerta de Campanhas →
  Visão geral: 3 dias por padrão, ajustável em Configurações → Campanhas, 0 desliga), para
  avisar o cliente antes de a campanha parar. Vem primeiro quem tem menos tempo: saldo que
  já acabou, depois "acaba hoje", depois os dias contados. Cada linha traz o cliente (o nome
  abre a página dele), quanto resta, o alerta ("saldo acabou", "saldo para 2 dias") e
  **Avisar do saldo**, que abre o WhatsApp do cliente com a mensagem escrita, a mesma da
  Visão geral. "Ver visão geral" leva para lá. Sem nenhum cliente em alerta o card não
  aparece, e ele só existe onde a Meta está ligada. O Painel não ficou mais lento: abre como
  antes e o card entra quando os saldos chegam.

## [1.11.1] - 2026-11-12

### Fixed

- **Visão geral: um saldo que já acabou não aparece mais como "saldo acaba hoje".** O
  alerta dizia "acaba hoje" para qualquer saldo que não cobrisse um dia, inclusive zero: uma
  conta parada havia dois dias, com R$ 0,00 na Meta, lia como se ainda houvesse tempo. Agora
  saldo zerado é **"saldo acabou"**, e quando as campanhas também pararam de entregar o
  alerta é um só, com a causa na frente: "saldo acabou: sem entrega desde ontem" (antes eram
  dois alertas para o mesmo acontecimento). O alerta vale mesmo se nada foi gasto nos
  últimos 7 dias, caso em que antes não aparecia. Na coluna Saldo, embaixo do valor:
  "acabou", "menos de um dia" (era "para 0 dias") ou "para N dias". A mensagem de **Avisar
  do saldo** acompanha: com saldo zerado ela diz que o saldo acabou e que sem saldo as
  campanhas ficam paradas, em vez de "acaba hoje (restam R$ 0,00)".

## [1.11.0] - 2026-11-12

### Added

- **Campanhas → Visão geral: a mensagem para o cliente já escrita, a um toque.** Cada linha
  ganhou até dois atalhos que abrem o WhatsApp na conversa do próprio cliente (o número do
  cadastro) com o texto pronto; você lê, muda o que quiser e envia. **Avisar do saldo**
  aparece junto do alerta "saldo para N dias" e diz quanto resta e por quantos dias no ritmo
  atual: "Olá, Carla! O saldo dos seus anúncios dura mais 2 dias no ritmo atual (restam
  R$ 48,00). Para as campanhas não pararem, vale colocar crédito nos próximos dias."
  **Enviar resumo** leva os números do período escolhido como a linha mostra: investimento,
  cliques no link e, quando as campanhas contam a mesma coisa, os resultados com o custo de
  cada um. O cumprimento usa o primeiro nome do contato do cliente. Sem número no cadastro,
  o WhatsApp pergunta para quem enviar. A Pauta não envia nada sozinha. O registro de uso
  anota só o tipo da mensagem aberta (saldo ou resumo), nunca o cliente nem o texto. API:
  as linhas de `GET /api/campaigns/overview` levam `contact` e `whatsapp`.

## [1.10.2] - 2026-11-12

### Fixed

- **"Atualizar agora" não diz mais "A sincronização não terminou" sobre números novos.** A
  tela sabe que uma sincronização acabou porque o horário da última mudou, e esse horário
  tem segundos inteiros: uma sincronização que começasse no mesmo segundo da anterior
  ficava com o mesmo horário e parecia não ter rodado. Com a Meta de verdade isso
  praticamente não acontece (uma sincronização leva segundos); nos testes de navegador,
  rápidos, acontecia cerca de uma vez em quinze e podia parar uma versão. Agora duas
  sincronizações seguidas nunca ficam com o mesmo horário.

## [1.10.1] - 2026-11-12

### Fixed

- **Um toque no menu não se perde mais quando a lista chega na mesma hora.** Ao sair de
  Pedidos (ou de Campanhas, Clientes) no instante em que os dados da tela ainda estavam
  chegando, a tela antiga às vezes reescrevia o endereço com o seu filtro
  (`#/pedidos?f=open`) por cima do novo, e a pessoa continuava onde estava, como se não
  tivesse tocado. Agora uma tela só ajusta o endereço enquanto ele ainda é o dela. Era
  também o que fazia um teste de navegador falhar de vez em quando (a primeira tentativa
  da versão 1.10.0 parou nele).

## [1.10.0] - 2026-11-12

### Added

- **Campanhas → Visão geral: todos os clientes numa tela, quem precisa de atenção
  primeiro.** Uma segunda aba em Campanhas (a lista de sempre vira "Por cliente") mostra
  uma linha por cliente: valor gasto, cliques e custo por clique, resultados quando as
  campanhas contam a mesma coisa, a variação contra o período anterior, uma linha de
  tendência dos últimos 14 dias, o saldo com "para N dias" e o Visto. Cada linha traz seus
  alertas em uma frase que dá para conferir no Gerenciador: "custo por clique subiu 42% em
  7 dias", "resultados caíram 35% com o mesmo investimento", "sem entrega desde ontem",
  "saldo para 2 dias", "sem dados novos da Meta", "sem análise há 3 dias". Os alertas
  comparam sempre os últimos 7 dias com os 7 anteriores, sem contar hoje, e só falam acima
  de R$ 20 gastos em cada semana; um cliente cujas campanhas começaram há pouco não é
  comparado com um período em que ainda não existia. Filtros: só com alerta, segmento e o
  que a tendência desenha. Pedido da equipe, para o dia em que forem 50 clientes; nada é
  lido da Meta ao abrir (são os números diários que a Pauta já guarda). API:
  `GET /api/campaigns/overview`. Desenho e perguntas em aberto:
  `docs/campaign-overview-spec.md`.
- **Configurações → Campanhas.** Um bloco novo, para administradores, com os números que os
  alertas da Visão geral usam: a partir de quantos por cento o custo subindo e o volume
  caindo viram alerta, quanto o investimento pode variar para ainda ser "o mesmo", o gasto
  e a contagem mínimos por semana para a Pauta dizer alguma coisa, e com quantos dias o
  saldo acabando e a falta de análise avisam (0 desliga cada um). No mesmo bloco, **quais
  tipos de pedido colocam uma campanha no ar**: até aqui eram sempre "Criar campanha" e
  "Reativar campanha", fixos no código, e renomear um deles em Listas desligava em silêncio
  a pergunta "Qual campanha o pedido criou?". Vale para todo o time. API:
  `GET`/`PATCH /api/campaigns/settings`; `GET /api/boot` e a exportação levam o bloco.

## [1.9.1] - 2026-11-12

### Fixed

- **Configurações → Meta não fica parada numa lista antiga.** A página sabia se a lista
  era antiga por uma leitura de estado feita logo depois; numa Meta rápida a releitura
  por trás já tinha acabado nesse instante, a página ouvia "atual" sobre a lista velha e
  não perguntava de novo (a tabela só mudava num Atualizar). Agora o aviso vem junto com
  a lista.

## [1.9.0] - 2026-11-12

### Added

- **Visto hoje: todos.** Em Campanhas, um botão no alto marca de uma vez todos os clientes
  com campanha ativa que ainda não foram vistos hoje (antes, marcava-se um por um, sete toques
  em trinta segundos). O botão de cada cliente e o ícone da nota continuam lá, para o dia em
  que há algo a dizer sobre um cliente. API: `POST /api/reviews/today` (nota opcional).
- **O pedido fica ligado à campanha que ele criou.** Nenhuma das 13 campanhas tinha pedido
  e só 1 de 16 pedidos tinha o link do Gerenciador, então a Pauta não conseguia ligar os
  dois sozinha. Agora, quando um pedido de **Criar campanha** (ou Reativar) vai para
  Concluído, no quadro ou na página, aparece a pergunta "Qual campanha o pedido criou?" com
  as campanhas do cliente que começaram nos últimos 7 dias e ainda não têm pedido,
  **Nenhuma** por padrão. Escolhendo uma, a página da campanha mostra "Pedido #n" e o
  histórico do pedido diz qual campanha. Só administradores; nada aparece quando não há
  campanha candidata. API: `PATCH /api/campaigns/{id}` com `{"request": id}` (ou null).
- **Configurações → Meta abre na hora.** Logo depois de conectar (ou desconectar) um
  portfólio, a lista de contas era descartada e a primeira visita esperava a leitura de
  todos os portfólios de novo: de sete a dezessete segundos com nove conectados. Agora a
  lista anterior aparece de imediato, com "Lendo a Meta de novo…", a Meta é lida por trás e
  a tabela se atualiza sozinha quando a leitura chega (as contas do portfólio
  desconectado saem na hora). **Atualizar** continua pedindo à Meta na hora. `GET /api/meta`
  ganha `stale` e `accounts_error`.
- **Campanhas abre na hora em qualquer período rápido.** A sincronização de hora em hora
  só deixava pronto o alcance de "Últimos 30 dias"; quem tinha "Este mês" ou "Últimos 7
  dias" guardado no navegador esperava a Meta a cada visita (seis segundos). Agora os seis
  períodos do seletor são lidos a cada hora; só "Personalizado" ainda lê na tela.
- **O espaço do OneDrive em Configurações → Arquivos** vale uma hora em vez de cinco
  minutos (um envio ou uma remoção zera): a leitura, às vezes com a renovação do token
  antes, era o que `GET /api/onedrive` esperava a cada visita.

### Changed

- **O WhatsApp do cliente ficou em destaque no cadastro.** Só 1 de 12 clientes tinha o
  número, e sem ele o **Abrir conversa** do relatório fica desligado. No formulário do
  cliente o campo vem logo abaixo do nome, com a dica "para abrir a conversa do relatório
  daqui"; na lista de clientes, quem não tem número mostra "sem WhatsApp". Continua
  opcional: há cliente que não tem mesmo.
- **O registro de uso anota o período de cada abertura de Campanhas.** Uma espera de 6,6 s
  em Campanhas no dia 11 não dizia qual período custou isso; agora cada abertura de
  Campanhas ou de uma campanha registra o período escolhido (`period`, decisão 11).
- **O registro de uso diz em que chamada ou formulário o erro apareceu.** Cada aviso de
  erro ficava registrado só como "validation". Agora leva o método, a rota e o status da
  chamada que falhou logo antes (até 3 s) ou, quando nenhuma falhou (uma checagem na
  própria tela), o formulário ou a tela de onde veio; `pauta usage` mostra isso na seção
  dos erros. Nada do conteúdo dos campos é registrado. Decisão 11 atualizada.

## [1.8.4] - 2026-11-06

### Changed

- **Campanhas abre na hora também depois de uma hora parada.** O alcance de cada campanha
  vem da Meta e valia uma hora; a primeira visita depois disso esperava de três a cinco
  segundos pela leitura, portfólio por portfólio. Agora os números anteriores aparecem de
  imediato (até um dia de idade) enquanto a Meta é lida de novo por trás, e a sincronização
  de hora em hora já lê o alcance do período padrão (últimos 30 dias). **Atualizar** continua
  pedindo à Meta na hora.
- **As miniaturas dos arquivos abrem na hora.** Cada miniatura era pedida ao OneDrive a cada
  vez (duas idas, um a três segundos). Agora é guardada ao lado do banco na primeira vez e
  servida dali depois, em qualquer aparelho; some junto com o arquivo.

## [1.8.3] - 2026-11-05

### Changed

- **O link do relatório vale 5 dias, não 30.** Tempo de sobra para o cliente abrir na semana
  em que recebeu, e um link repassado adiante morre logo. Os links já criados na 1.8.2
  continuam com a validade que tinham. Decisão 12 atualizada.

## [1.8.2] - 2026-11-05

### Added

- **Link do relatório para o cliente.** Na tela do relatório, **Copiar link** cria um
  endereço (`/r/<código>`) que abre o mesmo cartão em qualquer navegador, sem conta na Pauta,
  e copia. O link vale por 30 dias e mostra só o que está no cartão: o nome da campanha, o
  cliente, o período, as métricas escolhidas naquele momento (com as barras por dia) e a data
  dos dados da Meta; nada de telefone, contato, contas de anúncio, orçamento ou outras
  campanhas. **Abrir conversa** passa a mandar o link no fim da mensagem do WhatsApp ("Veja o
  relatório aqui: ..."), e o WhatsApp mostra uma prévia com o nome da campanha, do cliente e
  o período. A tela diz até quando o link vale. Na página da campanha, **Links do relatório**
  lista os links criados (período, quantas métricas, quem criou, até quando) com **Revogar**:
  a partir daí o endereço mostra só "Este relatório não está mais disponível", assim como um
  link vencido. Pedir o link do mesmo cartão de novo (mesmo período, mesmas métricas) devolve
  o mesmo endereço. API: `POST /api/campaigns/{id}/links` (`{since, until, metrics}` →
  `{url, expires, ...}`), `DELETE /api/campaigns/{id}/links/{token}`, `links` em
  `GET /api/campaigns/{id}`; `GET /api/r/{token}` e `GET /r/{token}` abrem sem sessão.
  Esquema v14 (só acrescenta a tabela `report_link`). Decisão 12.

## [1.8.1] - 2026-11-04

### Added

- **O Pauta agora registra quais telas e ações cada conta usa, para melhorar o app.** Ficam
  no banco do próprio time o número da conta (não o nome), a tela, a ação, o tipo de
  aparelho (celular ou computador, app instalado ou navegador, tamanho da tela), os erros
  que apareceram e quanto tempo cada chamada levou; nunca o conteúdo de pedidos ou clientes.
  Os registros são apagados após 90 dias, e um time pode pedir para desligar
  (`pauta usage --disable`). O responsável lê o resumo com `pauta usage` (decisão 11); veja a
  política de privacidade.
### Changed

- **Campanhas e a página do cliente abrem na hora.** A lista de contas da Meta (números do
  mês, saldos) valia dez minutos; quem voltava depois disso esperava de quatro a oito
  segundos pela leitura dos três portfólios, a cada visita. Agora a lista anterior aparece
  de imediato e a Meta é lida de novo por trás; a sincronização de hora em hora também a
  mantém atualizada. **Atualizar** em Configurações continua pedindo à Meta na hora.

## [1.8.0] - 2026-11-04

### Added

- **Relatório para o cliente.** Na página da campanha, **Gerar relatório** abre uma tela
  limpa, sem menus, feita para tirar um print e mandar no WhatsApp: o nome da campanha, o
  cliente, o período e as métricas marcadas na página da campanha viram cartões, cada um com
  o número, o que ele conta (nos Resultados) e uma frase curta dizendo o que está sendo
  medido, mais as barras por dia onde há dados. As cores são fixas (não seguem o tema do
  celular), para todo cliente receber o mesmo cartão. **Abrir conversa** abre o WhatsApp na
  conversa com o número cadastrado no cliente, com a mensagem pronta; sem número cadastrado
  o botão fica desligado e a tela diz onde cadastrar. **Copiar imagem** gera a imagem do cartão no próprio celular e a copia, para
  colar na conversa (o link do WhatsApp só leva texto; num navegador que não copia imagem,
  ela é baixada). O endereço (`#/relatorio/<id>?p=...&m=...`) guarda o período e as métricas,
  então o mesmo relatório pode ser reaberto. API: `GET /api/campaigns/{id}` traz
  `client_contact` e `client_whatsapp`.
### Fixed

- **Link do WhatsApp com número digitado com o zero.** Um WhatsApp cadastrado como se disca
  ("0 32 99999-9999") virava um link que o WhatsApp recusava ("Não foi possível abrir este
  link"). O zero do DDD e o "00" internacional saem antes de o 55 do Brasil entrar; vale
  para o botão Compartilhar com o cliente e para o WhatsApp na página do cliente.

### Changed

- **Campanhas em português direto.** Na página da campanha, as métricas passam a ter o nome
  do Gerenciador de Anúncios: **Cliques no link** (antes "Leads (cliques)"), **Custo por
  clique no link** (antes "Custo por lead"), **Taxa de cliques (CTR)** e **Custo por mil
  impressões (CPM)**; o objetivo da campanha aparece em português ("objetivo: Engajamento",
  antes "engagement"); as ações da Meta que viram chips, e os Resultados, ganham nome em
  português para muito mais tipos (conversas, cadastros no site, compras, carrinho,
  ligações, instalações do app...), inclusive os que apareciam como chave técnica nas
  campanhas da equipe (`onsite_web_lead` → "Cadastros no site", `post_interaction_net` →
  "Interações com a publicação (líquidas)", `offsite_search_add_meta_leads` → "Pesquisas
  (site + Meta)"...); um tipo que a Pauta ainda não conhece é traduzido palavra por palavra,
  nunca mais aparece como chave. As ações ficam atrás de **Mais métricas (N)** até uma ser
  marcada, para a fileira de chips não tomar meia tela. O chip "Cliques no link" da ação
  some: é a mesma métrica. Os cartões seguem um padrão só: título, número, o que ele conta
  (nos Resultados) e uma frase curta dizendo o que está sendo medido (a mesma que vai no
  relatório), em vez de uma nota ao lado do título em alguns e nada em outros; o número
  pequeno acima do gráfico ganha o nome que faltava ("máx. por dia").

## [1.7.1] - 2026-11-03

### Changed

- **Configurações abre na hora.** O cartão do OneDrive perguntava à Microsoft quanto espaço
  a pasta usa a cada visita à página (um a dois segundos de espera, oito vezes só no
  domingo). Agora a resposta vale por cinco minutos; um arquivo que sobe ou sai, ou uma
  desconexão, pede de novo.

## [1.7.0] - 2026-11-01

### Added

- **Campanhas igual ao Gerenciador de Anúncios.** O período padrão passa a ser **Últimos 30
  dias** (o do próprio Gerenciador: de ontem para trás, sem o dia de hoje), sempre com as
  datas exatas; o navegador continua lembrando a última escolha e o endereço manda. As
  colunas são as dele, na ordem dele: **Resultados** (o que o objetivo da campanha conta,
  com o nome que o Gerenciador usa embaixo do número: "Conversas por mensagem iniciadas",
  "Cadastros", "Cliques no link"...; "—" quando a Meta não registrou resultado para o
  objetivo), **Custo por resultado**, **Valor gasto** (antes "Investido"), **Impressões**,
  **Alcance** e **Orçamento** da campanha ("R$ 15,00 · diário" ou "R$ 450,00 · total").
  Cada campanha mostra "ativa desde *dia*" ao lado do nome, para um período curto não
  parecer falta de dados. Na página da campanha os cartões padrão são Resultados, Custo por
  resultado e Valor gasto; Leads (cliques), Custo por lead, CTR, CPM e frequência seguem
  no seletor. "Hoje" é o dia da conta de anúncios (fuso horário que a Meta informa; São
  Paulo quando não há conta), não o do servidor: o período padrão, o "hoje incluso", a data
  do Visto hoje e os dias que a sincronização relê seguem o fuso da conta. API:
  `GET /api/campaigns` e `GET /api/campaigns/{id}` trazem `results`, `result_indicator`,
  `cost_per_result_cents`, `daily_budget_cents` e `lifetime_budget_cents`; `results` deixa
  de ser os cliques no link (`link_clicks` e `cpl_cents` continuam); sem `since`/`until` o
  período é os últimos 30 dias e `today_included` vem `false`. Esquema v11 (aditivo).
- **Equipe → Meta** passa a ter **uma conexão por portfólio empresarial** (o Login para
  Empresas da Meta conecta um portfólio por vez, e o usuário do sistema da Pauta pode viver
  no portfólio de um cliente): cada portfólio conectado aparece num bloco próprio,
  "Portfólio *nome* conectado à Pauta em *data* (por *pessoa*)", com **Adicionar contas**
  (entra de novo nesse portfólio) e **Desconectar** (só ele; o acesso do lado da Meta se
  tira nas Configurações do negócio desse portfólio). Conectar um segundo portfólio não
  derruba mais o primeiro: **Conectar outro portfólio** soma. As contas de anúncios de todos
  os portfólios ficam na mesma tabela, cada uma dizendo de qual portfólio é; um acesso
  revogado na Meta marca só aquele portfólio ("acesso revogado na Meta; reconecte em
  Adicionar contas") e os outros seguem lendo e sincronizando. Um **Histórico** (quem
  conectou, desconectou, vinculou ou desvinculou o quê, e quando) fecha o cartão e sai no
  export. A conexão antiga é migrada sozinha na primeira subida (o arquivo do token ganha o
  número do portfólio). API: `POST /api/meta/connect` aceita `{"business_id"}`, `DELETE
  /api/meta/connections/{business_id}` substitui `DELETE /api/meta`, `GET /api/meta` traz
  `connections`, novo `GET /api/meta/log`; `/metrics` ganha `meta.connections` e
  `meta.revoked`; `pauta meta status` lista os portfólios. Esquema v10 (aditivo).
- Aba **Campanhas** (quando a Meta está configurada; todo o time vê): um bloco por cliente
  com as campanhas acompanhadas e os números do período (investido, leads = cliques no link,
  custo por lead, alcance, impressões), mais o total do cliente. No topo, o **período** com
  as opções do Gerenciador de Anúncios (hoje, ontem, últimos 7 ou 30 dias sem o dia de hoje,
  este mês, mês passado, personalizado) sempre mostrando as datas exatas e um aviso "hoje
  incluso"; a escolha fica no endereço e o navegador lembra a última. O check diário mora
  nas mesmas linhas: **Visto hoje** por cliente (com nota opcional), "Hoje: 3 de 5 clientes
  vistos", e quem ainda falta ver fica em cima. Tocar numa campanha abre a página dela:
  escolha de métricas (investido, leads, custo por lead, alcance, impressões, CTR, CPM,
  frequência e os resultados que a Meta reportar, como conversas iniciadas), cada uma com
  o valor do período e um gráfico por dia. Administradores têm **Atualizar agora**, **Não
  acompanhar** e "ver ignoradas". No celular, a aba entra no lugar de Financeiro/Quadro
  (os dois continuam a um toque do Painel). **Equipe → Meta** agora só mapeia as contas
  (conta, cliente e saldo; os totais do mês saíram, porque somavam campanhas encerradas) e,
  quando a Meta recusa o saldo, diz o que fazer: "sem permissão · reconecte em Adicionar
  contas". O cartão Meta da página do cliente lista as campanhas do mês com link para a aba.
  API: `GET /api/campaigns` ganha `include_skipped=1`, `client=<id>`, `last_sync`,
  `seen_today`/`seen`; novos `GET /api/campaigns/{id}?since&until` (a campanha com os dias)
  e `POST /api/clients/{id}/reviews` (o Visto hoje).
- Acompanhamento de campanhas (dados e sincronização; a tela vem a seguir): a Pauta passa a
  guardar, por campanha e por dia, os números das contas de anúncios vinculadas a um cliente
  (investido, impressões, alcance, cliques no link e as ações da Meta). As campanhas vêm da
  própria Meta: toda campanha **ativa** de uma conta vinculada ganha uma linha sob o cliente,
  encerra quando a Meta para de veicular e volta quando reativa; quem não quiser acompanhar
  uma campanha marca "não acompanhar" e a sincronização não mexe mais nela. Um pedido
  concluído de "Criar campanha" ou "Reativar campanha" cujo link do Gerenciador de Anúncios
  traz o número da campanha fica ligado a ela (aparece na linha do tempo). A sincronização
  roda sozinha no servidor (de hora em hora os dois últimos dias; de madrugada os últimos 28,
  porque conversões chegam atrasadas), e também pela linha de comando (`pauta meta sync`,
  `pauta meta status`). API: `GET /api/campaigns?since&until` (mês atual por padrão),
  `PATCH /api/campaigns/{id}` e `POST /api/meta/sync` (administradores, uma vez a cada 15
  minutos). O `/metrics` mostra a última sincronização; a exportação inclui as tabelas novas.
- Para testar: qualquer branch pode ir para https://acc.pauta.cc antes do merge (Actions →
  *Deploy branch to acceptance*). Só o Eduardo pode disparar; a versão do ar não muda.
- Equipe → **Meta** (para administradores, quando o servidor tem a Meta configurada):
  **Conectar Meta** leva ao login da Meta, onde você escolhe o portfólio empresarial da
  agência e as contas de anúncios. Na volta, a Pauta mostra cada conta com os números deste
  mês: investido, alcance, impressões, cliques no link, custo por clique e o saldo (ou "sem
  permissão", quando a Meta não deixa ler). A Pauta só lê; não altera nada na Meta. Primeiro
  passo da fase 2 da decisão 8.
- Equipe → Meta: a coluna **Cliente** diz de quem é cada conta de anúncios. A Pauta sugere
  pelo nome (você confirma) e já vincula sozinha quando o número da conta está no cadastro do
  cliente. Na página do cliente aparece um cartão **Meta** com os números deste mês das contas
  vinculadas (investido, alcance, cliques no link, custo por clique e saldo). Uma conta que
  sumir da lista da Meta continua aqui, marcada "não aparece mais na Meta".
- Meta: a leitura faz duas chamadas por 50 contas (lista + lote), não uma por conta; se a
  Meta não devolver os números de uma conta, só essa linha mostra "—" (o motivo ao passar o
  mouse) e as outras continuam. Quando a Meta falha, a página do cliente diz "os números da
  Meta estão indisponíveis no momento" (o motivo mesmo só para administradores) e a Pauta
  espera um minuto antes de tentar de novo, a não ser que um administrador toque em
  Atualizar. Desvincular uma conta agora vale: a próxima leitura não a vincula de volta.

### Fixed

- **Atualizar agora** (Campanhas) responde na hora e sincroniza em segundo plano: a página
  mostra "Sincronizando com a Meta…", acompanha a linha "Dados da Meta de…" e avisa quando
  terminou (ou o problema que a passagem encontrou; se o servidor reiniciou no meio e nada
  foi sincronizado, "A sincronização não terminou; tente de novo", não "atualizados"). Só
  uma sincronização roda por vez: um segundo toque, ou a passagem automática de hora em
  hora chegando no meio, recebe "a Meta já está sincronizando" em vez de ler a Meta duas
  vezes (a automática tenta de novo no minuto seguinte; a página só espera a passagem que
  já roda acabar). Sair de Campanhas no meio não avisa nada em outra tela. API: `POST
  /api/meta/sync` passa a responder **202** `{"started": true, "last_sync": <anterior>}` e
  **409** `{"error", "reason": "busy"}` enquanto uma passagem roda (os erros da Meta
  trazem `reason`, o código fixo); `GET /api/campaigns` e `/metrics` trazem `sync_error`
  e `syncing`.
- Com dois ou mais portfólios conectados, uma conta vinculada a um cliente que nenhuma
  leitura ainda tinha colocado no seu portfólio ficava sem sincronizar, sem erro e sem
  aviso. A sincronização agora lê a lista de contas de cada portfólio antes (o que coloca
  quase todas), e a que ainda assim ficar sem portfólio (sumiu da Meta, ou o portfólio dela
  foi desconectado) aparece nos erros da passagem e no log: "conta *id* sem portfólio:
  desvincule a conta em Configurações → Meta ou reconecte o portfólio". O aviso, e o toast
  de Campanhas, saem uma vez; nas passagens seguintes a conta fica só no log, e a lista de
  contas só é relida quando o conjunto de contas sem portfólio muda, não de hora em hora.
- Um portfólio com mais de cem contas de anúncios agora lista todas em Configurações → Meta:
  a leitura segue as páginas da Meta (antes parava na primeira).
- Campanhas lista todo cliente com conta vinculada, mesmo sem campanha ativa (sumia como se
  a conexão tivesse falhado), e mostra o Saldo da conta em cada bloco; `GET /api/campaigns`
  traz `accounts` por cliente e `campaigns: []` para esses.
- du7: o porteiro do runner agora é `runner-job-guard.sh`; sem a extensão o runner recusava
  todo job, inclusive os deploys.
- **Perfil** (`#/perfil`, no menu da conta e no avatar da barra de cima): a sua página, só
  sua. Nome, **WhatsApp** (novo; só você vê) e e-mail do Gravatar
  saem de Equipe e vêm para cá. As suas **passkeys** aparecem em lista, com nome (a Pauta
  dá um ao criar: "iPhone", "Mac"...; dá para renomear), quando foi criada e usada;
  **Adicionar passkey neste aparelho** e **Remover** (enquanto sobrar uma; o aparelho da
  passkey removida sai da Pauta na hora, os outros continuam) ficam ao lado,
  e o **Link de nova passkey** (celular novo ou perdido) agora você mesmo gera, com Copiar
  e Enviar no WhatsApp: vale 10 minutos (é para abrir no aparelho novo na hora; o que o
  administrador manda continua valendo 3 dias) e "Sair em todos os aparelhos" também o
  cancela. "Sair em todos os aparelhos" fecha a página. API: `GET /api/me`
  traz `whatsapp`; `PATCH /api/me` aceita `name`, `email` e `whatsapp`; `GET /api/me/passkeys`,
  `PATCH|DELETE /api/me/passkeys/{id}` (400 na última; o DELETE encerra as outras sessões
  e devolve um cookie novo para esta), `POST /api/me/move`. Esquema v12
  (aditivo).
- **Link de nova passkey** em Configurações → Time: o administrador gera, para qualquer pessoa do time, um
  link de uso único para criar uma passkey nova (celular novo, perdido, ou o ambiente de
  aceitação). Antes, esse link só aparecia durante a mudança de endereço.

### Changed

- Voltar para uma versão anterior ao esquema 10 (antes de "uma conexão por portfólio")
  mostra a Meta como "não conectada" até a próxima atualização: o arquivo do token passou a
  ser um por portfólio, e a versão antiga não o encontra pelo nome. Nada se perde; a
  atualização seguinte volta a ler os arquivos.
- Custo por resultado e Custo por lead arredondam a metade para cima, como o Gerenciador
  de Anúncios (antes a metade exata ia para o par mais próximo).
- Um arquivo de token antigo ilegível é posto de lado com um aviso no log em vez de ser
  tentado a cada início; com dois ou mais portfólios, o Alcance de uma conta ainda sem
  portfólio conhecido fica em traço sem derrubar o dos outros; um acesso revogado chegando
  no meio de Desconectar não ressuscita a conexão.
- A aba **Equipe** agora se chama **Configurações** (ícone de engrenagem): é onde ficam o
  time, os convites, a Meta, o Financeiro, as listas e os Arquivos (o OneDrive dos pedidos),
  em seções com esse nome e nessa ordem. O endereço `#/equipe` (e qualquer link antigo que
  comece com ele, inclusive a volta do login da Meta) abre `#/configuracoes` sozinho. As
  mensagens que mandavam para "Equipe → Meta" ou "Equipe" agora dizem "Configurações → ...".

## [1.6.1] - 2026-10-31

### Changed

- A Pauta agora fica em **https://app.pauta.cc**. As passkeys feitas em pauta.cc continuam
  valendo, sem fazer nada. pauta.cc e pauta.team levam para www.pauta.cc, o futuro site
  (por enquanto ele leva para o app), e links antigos como pauta.cc/#/mudar/... ainda chegam
  ao lugar certo. O teste fica em https://acc.pauta.cc.

### Fixed

- Equipe: os botões de quem administra não espremem mais o nome das pessoas no painel Time;
  vão para baixo do nome quando falta espaço.

## [1.6.0] - 2026-10-31

### Changed

- A Pauta mudou para **https://pauta.cc** (decision 4). No endereço antigo aparece "Mudar
  para pauta.cc": um toque leva sua conta para o endereço novo, onde você cria uma passkey
  com Face ID ou digital. A conta, os pedidos e o histórico continuam os mesmos. Depois,
  adicione pauta.cc à tela de início do celular. A página Equipe mostra quem já mudou, e
  `pauta users` também. pauta.team leva para pauta.cc.
- Quem administra pode mandar a cada pessoa o link dela: Equipe → "Link para mudar" →
  Enviar no WhatsApp. A pessoa toca no link, confirma com Face ID e já está em pauta.cc.
  O link vale uma vez, por 3 dias, e só para aquela pessoa; serve também para quem perdeu o
  celular. No du7: `pauta move-link <nome>`.

## [1.5.1] - 2026-10-30

### Fixed

- Financeiro: o botão Registrar do painel registrava o pagamento no cliente errado (ou dava
  "cliente não encontrado") quando o número do ciclo de cobrança não coincidia com o do
  cliente, o que acontece assim que alguém é pausado e volta. O painel agora leva o número
  do cliente; confira os pagamentos registrados pelo painel na 1.5.0.

## [1.5.0] - 2026-10-30

### Added

- Financeiro: uma aba nova (depois de Clientes; no celular ela entra no lugar do Quadro) com
  quem está em dia, em atraso, vencendo na semana e esperando o primeiro pagamento, e o
  recebido no mês. Cada cliente Ativo tem um valor por mês; o mês dele começa no primeiro
  pagamento registrado (ou na data "cliente desde", ou num dia fixo: escolha em Equipe →
  Financeiro), e o painel mostra em que mês de vida ele está ("4º mês"). Pausar ou encerrar
  tira o cliente do painel; ao voltar, a contagem recomeça. Na página do cliente, um card
  Pagamentos com o valor, a situação, a lista e o botão para registrar. Pagamentos nunca são
  apagados, só anulados (por quem registrou ou um administrador). Equipe → Financeiro guarda
  as regras do time: moeda, valor padrão, periodicidade, tolerância, aviso de vencimento e
  quem pode ver. Os cartões do topo filtram a lista (toque em "Em atraso" e só eles
  aparecem; toque de novo para ver todos) e "Recebido no mês" abre os pagamentos do mês,
  com um seletor para ver quanto entrou em cada mês. Decisão 7.

## [1.4.0] - 2026-10-29

### Added

- Arquivos nos pedidos: envie imagens e vídeos direto na página do pedido (botão ou arrastar),
  com miniatura, quem enviou e quando, e uma linha na conversa e histórico. Os arquivos ficam
  no OneDrive do time, não no servidor; "Link para o cliente" gera um link só de
  visualização para mandar no WhatsApp. Um administrador conecta o OneDrive uma vez em
  Equipe → OneDrive, com um código (decision 3).

## [1.3.0] - 2026-10-29

### Security

- Ready for collaborators and a public repository (decision 2): CODEOWNERS for CI, deploy,
  sign-in and dependencies, rulesets and settings as code (`scripts/repo-settings.sh`), the
  WhatsApp secrets in an `alerts` environment, immutable releases, and on du7 a runner that
  refuses every job but the deploy and a `pauta-deploy` that only installs the published
  release's files. `SECURITY.md` and `CONTRIBUTING.md` are new.

Fixes from a security review of 1.2.3. Everyone has to sign in again once after this release
(the session key moved), which takes a tap with the passkey.

- The key that signs sessions now lives in a file next to the database
  (`pauta.db.session-key`, readable only by the service) instead of inside it, so the nightly
  backups on the NAS can no longer be turned into an admin login. The old key is deleted on
  first start. Deleting the file and restarting signs everyone out.
- Sessions can be ended: "Sair" ends the person's sessions on every device, and disabling an
  account ends its sessions for good (re-enabling it doesn't bring old ones back). Before, a
  copied cookie kept working for 180 days after "Sair".
- A single-use invite could create several accounts if the join was sent many times at once;
  joining is now one at a time and an invite can't be used past its limit.
- Passkeys must verify the person (Face ID, fingerprint or PIN); a touch alone is refused.
- The team always keeps at least one active admin, and admin changes take only true/false
  (sending `0` used to get past the "you can't demote yourself" check).
- Nobody can take a teammate's name (ignoring case, accents and invisible characters) or
  email, so the timeline can't be made to show someone else as the author. Hidden control and
  text-direction characters are dropped from all text.
- "Exportar dados" is for admins only, as documented.
- The ads page and Instagram fields refuse `javascript:`, `data:` and similar links (the app
  never made them clickable, but the export and copy button passed them on).
- Malformed requests get a 400 instead of a 500, so nobody can set off the 5xx alarm from
  outside; bodies must be exactly `application/json` with a valid length.
- A connection that stalls for 15 seconds is dropped, and at most 64 are served at once, so
  slow clients can't pile up threads on the Pi.
- New headers: `X-Frame-Options`, `Cross-Origin-Opener-Policy` and `Permissions-Policy`.
- The pauta unit gets `TasksMax` and `MemoryMax` (applied by `provision-du7.sh`).
- The Equipe page says plainly what the Gravatar hash does and doesn't hide.

### Fixed

- A browser test expected an afternoon greeting and failed every morning ("Bom dia").
- A browser test waited by evaluating a string in the page, which the Content Security Policy
  sometimes refused, so CI failed at random.

## [1.2.3] - 2026-10-28

### Fixed

- On a phone, the Quadro's columns widened the whole page, which pushed the tab bar off the
  screen, so there was no way to leave the Quadro without the browser's back button.

### Added

- Browser tests for every way a signed-in person arrives (an invite link then "Abrir a
  Pauta", the back button, an edited address, a fresh load on any screen), on a laptop and a
  phone, each walking every screen through the menu and checking it drew, not the 😕 error.

## [1.2.2] - 2026-10-28

### Added

- The version that's live shows in small type next to the Pauta name, in the sidebar and in
  the phone's top bar (it's also at the bottom of the Equipe page).

## [1.2.1] - 2026-10-28

### Fixed

- Opening an invite link while signed in ("Você já entrou" → "Abrir a Pauta") left the app
  without its startup data, so every screen after the dashboard said "null is not an object
  (evaluating 'BOOT.options')" until a reload. The app now loads it first.

## [1.2.0] - 2026-10-28

### Added

- Structured logs: one JSON line per request in the journal (`journalctl -u pauta`) with the
  method, the route pattern (`/api/requests/{id}`, never the raw path), the status, the
  duration and the account id. No request bodies, IPs, names, cookies or invite tokens. Also
  `start` (with the version), `auth_failed`, `rate_limited` and `error` (with the traceback)
  events; errors are journal errors (`journalctl -u pauta -p err`).
- `GET /metrics` on 127.0.0.1:8088 only (refused through Caddy): requests and 5xx since the
  start, the last 15 minutes' requests, 5xx, p50/p95 latency and failing routes, the database
  size and the age of the newest nightly backup.
- du7's watchdog checks Pauta every 5 minutes: the service and `/healthz` (restarts it), the
  5xx rate, the nightly backup and its NAS copy (under 26 h), the TLS certificate (over 14
  days left), the GitHub runner, and failed deploys. Alerts go to IRC #du7 and WhatsApp.
- An hourly uptime check from GitHub (`uptime.yml`) that works when du7 or the home internet
  is down: it opens an issue labelled `uptime` and sends a WhatsApp alert, and closes the issue
  when the site is back.
- A WhatsApp alert when a release or a manual deploy fails. Alerts use the approved
  `du7_service_status` template, so they arrive even outside WhatsApp's 24-hour window.

### Fixed

- A crash in a request now answers 500 with a message and logs the traceback; the connection
  used to drop, which Caddy showed as a 502.

### Changed

- `pauta-deploy` also writes its deploys, switches and rollbacks to the journal
  (`journalctl -t pauta-deploy`; failures at error priority).

## [1.1.0] - 2026-10-28

### Added

- Clients have a **Link da página de anúncios** (free text). It shows under *Atalhos* on the
  client, and on every request in the *Briefing* and in *Dados do cliente*, each with a
  *Copiar* button. A link opens in a new tab; anything else is shown as written.
- The *Clientes* page filters by state (Todos, Ativo, Pausado, Encerrado), with counts. The
  filter is kept in the address, so it survives a reload.
- Admins can delete any client. One with requests is deleted together with them and their
  history, after typing the client's name to confirm; to keep the history, mark the client
  *Encerrado* instead.

## [1.0.0] - 2026-10-28

The first versioned release. It covers everything since Pauta replaced the
"Controle de Clientes e Campanhas" spreadsheet.

### Added

- Requests (pedidos) with the briefing and the execution on one record: client, type,
  goal, audience, region, budget, account balance, creatives, due date, priority, status,
  what's missing, campaign link and notes.
- A timeline on every request: who created it, status changes, edits and comments.
- Dashboard, board with drag and drop, filterable list, clients with their requests, and
  editable lists for request types, goals and segments.
- Passkey accounts: join with a single-use invite (link, QR code or WhatsApp), sign in with
  Face ID, fingerprint or the device PIN, add more devices. No passwords anywhere.
- Admin tools: invite admins or members, disable people, export everything as JSON.
- Link previews for WhatsApp, iMessage, Slack and LinkedIn, and installable app icons.
- Gravatar pictures for people who add an email; teammates only see the hash, never the
  address.
- `GET /healthz` for the deploy and uptime checks, and `pauta --version`. The version is
  shown at the bottom of the Equipe page.
- `HEAD` requests for pages and `/healthz` (they used to answer 501).
- Nightly database backups, kept 30 days on du7 and copied to the NAS.

### Changed

- Signing in returns the same profile as `/api/me`, Gravatar included.
- Releases are built and tested by GitHub Actions and deployed to du7 by a self-hosted
  runner: one release per tag, a database backup before every deploy, and an automatic
  rollback when the new version fails its health check.

### Security

- Every page is served with a strict Content Security Policy (scripts from Pauta only;
  images also from gravatar.com), `nosniff`, `same-origin` referrers and no framing.
- Writes from other origins are refused; the session cookie is HttpOnly, SameSite=Strict
  and Secure behind HTTPS. Invite, sign-up and login endpoints are rate limited per IP.
- The service runs with systemd sandboxing: a read-only system, write access only to its
  own data directory, no privilege escalation.

[Unreleased]: https://github.com/eduelias/pauta/compare/v1.14.1...HEAD
[1.14.1]: https://github.com/eduelias/pauta/compare/v1.14.0...v1.14.1
[1.14.0]: https://github.com/eduelias/pauta/compare/v1.13.1...v1.14.0
[1.13.1]: https://github.com/eduelias/pauta/compare/v1.13.0...v1.13.1
[1.13.0]: https://github.com/eduelias/pauta/compare/v1.12.1...v1.13.0
[1.12.1]: https://github.com/eduelias/pauta/compare/v1.12.0...v1.12.1
[1.12.0]: https://github.com/eduelias/pauta/compare/v1.11.1...v1.12.0
[1.11.1]: https://github.com/eduelias/pauta/compare/v1.11.0...v1.11.1
[1.11.0]: https://github.com/eduelias/pauta/compare/v1.10.2...v1.11.0
[1.10.2]: https://github.com/eduelias/pauta/compare/v1.10.1...v1.10.2
[1.10.1]: https://github.com/eduelias/pauta/compare/v1.10.0...v1.10.1
[1.10.0]: https://github.com/eduelias/pauta/compare/v1.9.1...v1.10.0
[1.9.1]: https://github.com/eduelias/pauta/compare/v1.9.0...v1.9.1
[1.9.0]: https://github.com/eduelias/pauta/compare/v1.8.4...v1.9.0
[1.8.4]: https://github.com/eduelias/pauta/compare/v1.8.3...v1.8.4
[1.8.3]: https://github.com/eduelias/pauta/compare/v1.8.2...v1.8.3
[1.8.2]: https://github.com/eduelias/pauta/compare/v1.8.1...v1.8.2
[1.8.1]: https://github.com/eduelias/pauta/compare/v1.8.0...v1.8.1
[1.8.0]: https://github.com/eduelias/pauta/compare/v1.7.1...v1.8.0
[1.7.1]: https://github.com/eduelias/pauta/compare/v1.7.0...v1.7.1
[1.7.0]: https://github.com/eduelias/pauta/compare/v1.6.1...v1.7.0
[1.6.1]: https://github.com/eduelias/pauta/compare/v1.6.0...v1.6.1
[1.6.0]: https://github.com/eduelias/pauta/compare/v1.5.1...v1.6.0
[1.5.1]: https://github.com/eduelias/pauta/compare/v1.5.0...v1.5.1
[1.5.0]: https://github.com/eduelias/pauta/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/eduelias/pauta/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/eduelias/pauta/compare/v1.2.3...v1.3.0
[1.2.3]: https://github.com/eduelias/pauta/compare/v1.2.2...v1.2.3
[1.2.2]: https://github.com/eduelias/pauta/compare/v1.2.1...v1.2.2
[1.2.1]: https://github.com/eduelias/pauta/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/eduelias/pauta/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/eduelias/pauta/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/eduelias/pauta/releases/tag/v1.0.0
