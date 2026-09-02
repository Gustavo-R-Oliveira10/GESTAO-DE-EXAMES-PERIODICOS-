# Changelog

Histórico das alterações do projeto, em ordem cronológica.

## 2026-09-02 — Matemática da campanha, trava de upload único, seed do cronograma

- **Correção de matemática**: a meta (denominador do progresso %) deixou de
  ser um snapshot automático de "todo mundo do local que precisa de exame no
  momento da criação da campanha". Agora é definida **exclusivamente** pelo
  cruzamento da lista do RH contra a base mestre: só quem está com o ASO
  **vencido** no momento desse cruzamento vira "Convocado" (conta pra meta).
  Quem a lista trouxe mas já está "Dispensado" é barrado — aparece na tabela
  "Já Dispensados", não conta pra meta. `campanhas.criar_campanha()` não faz
  mais snapshot automático; a campanha nasce com 0 membros até a lista do RH
  ser processada.
- **Trava de upload único**: a área de upload da "Lista do RH" só aceita um
  envio por campanha — trava dupla (backend em `campanha_ja_processou_lista_rh`
  + o formulário some da tela). Depois do envio, o formulário é substituído
  permanentemente por um aviso estático (data/hora do processamento + nome do
  arquivo) e pelas duas tabelas de validação (Convocados / Já Dispensados),
  persistidas em nova tabela `campanha_rh_resultado` — sobrevivem a reload de
  página, não são só um flash de tela.
- **Seed do cronograma oficial**: `campanhas.seed_campanhas_oficiais()`, rodado
  na inicialização do servidor, pré-cadastra Brasília, Botafogo, Península,
  Recife e Curitiba com os períodos e detalhes de operação confirmados (SP,
  Sorocaba, BH e Santa Rita do Sapucaí ficaram de fora — datas ainda em
  definição). **Idempotente e não-destrutivo**: pula qualquer local que já
  tenha campanha (a Brasília que o usuário já tinha criado manualmente foi
  preservada intocada — validado em teste simulando exatamente esse cenário
  antes de rodar no servidor real).
- Novas colunas em `campanhas`: `detalhe_operacao`, `lista_rh_processada_em`,
  `lista_rh_arquivo`. Removida a função `adicionar_membros()` (substituída por
  `registrar_resultado_lista_rh()` + `obter_resultado_lista_rh()`).
- Validado via `app.test_client()` (DB isolado): seed cria as 5 campanhas com
  os `local_trabalho` corretos (conferidos contra os valores reais da base:
  "Brasilia" sem acento, "Botafogo" e "Península" sem prefixo "Rio de
  Janeiro"); seed é idempotente ao rodar de novo; seed preserva uma campanha
  pré-existente com dados diferentes dos oficiais (simulando a Brasília real
  do usuário); classificação convocado/já-dispensado correta; segundo upload
  bloqueado sem alterar `campanha_membros`; "processar dia" continua
  funcionando com o novo modelo de membros. Servidor real reiniciado e
  conferido: a Brasília do usuário (id 1) permaneceu com suas datas
  originais, e as outras 4 campanhas oficiais foram criadas ao lado.

## 2026-09-02 — Datas no padrão brasileiro (DD/MM/AAAA)

- Todo texto de data exibido na interface passou de ISO (`YYYY-MM-DD`) para
  o padrão brasileiro. Novos filtros Jinja em `server.py`: `data_br`
  (datas) e `datahora_br` (timestamps dos logs, com hora).
- Aplicado em: Consulta geral (coluna Último ASO + filtro dessa coluna,
  ajustado pra também filtrar em DD/MM), lista e detalhe de Campanhas
  (período, data do relatório, data de realização, último ASO dos
  pendentes), Histórico/Logs (data/hora de cada evento), e na planilha
  gerada por "Exportar base atualizada".
- **Sem mudança** nos campos `<input type="date">` (seletores de data dos
  formulários) — o HTML exige valor em ISO internamente; o navegador já
  exibe esses seletores no formato local do sistema operacional
  automaticamente, então não há o que ajustar aí.
- Armazenamento no banco continua ISO (`YYYY-MM-DD`) — é só a apresentação
  que mudou; ordenação/comparação de datas no código continua correta.
- Validado via `app.test_client()`: nenhuma data em formato ISO restou
  visível em Consulta geral, Campanhas (lista e detalhe) ou Logs; export em
  Excel confirmado abrindo o arquivo gerado e checando os valores da coluna
  `data_ultimo_aso`.

## 2026-09-02 — Filtros por coluna, 2ª planilha de campanha, visual mais forte

- **Bug real relatado pelo usuário**: subiu a lista de RH de Brasília e as 66
  linhas caíram todas na fila de exceções. Causa raiz: a planilha não tinha
  cabeçalho reconhecível (colunas viraram "Unnamed: 0/1/2" no pandas), e a
  primeira linha de dados foi silenciosamente consumida como se fosse
  cabeçalho (perda de uma pessoa). Corrigido com
  `planilhas.validar_colunas_identificacao()`: agora o sistema **recusa com
  mensagem clara** em vez de despejar tudo em exceção. Aplicado em
  `campanha_processar_dia` e `campanha_importar_rh`. As 65 exceções órfãs
  desse bug foram limpas da fila real via `/excecoes/limpar-tudo`.
- **Fila de exceções — ações em lote**: checkboxes + "selecionar todas",
  "Aprovar selecionadas" (usa o melhor candidato sugerido) e "Excluir
  selecionadas", mais um botão "Limpar toda a fila". **Bug encontrado nos
  próprios testes**: a primeira versão do "aprovar em lote" aceitava
  candidatos com score baixíssimo (39, claramente errado) porque o rapidfuzz
  sempre devolve os top-3 mesmo sem nenhum parecido de verdade. Corrigido com
  limite mínimo de confiança (score ≥ 85) — abaixo disso fica pendente para
  revisão manual individual em vez de arriscar vincular a pessoa errada.
- **Robustez de mapeamento de coluna**: `mapear_colunas()` agora normaliza
  acentos tanto do cabeçalho da planilha quanto dos aliases antes de comparar
  (`_normalizar_cabecalho`), então "Matrícula" (com acento) bate com o alias
  "matricula" independente de quem escreveu a planilha.
- **Campanhas — segunda planilha**: esclarecido com o usuário que uma
  campanha recebe **duas** planilhas distintas: (1) a lista do RH do local de
  trabalho (`/campanhas/<id>/importar-rh` — cruza contra a base mestre e
  agrega novos membros à campanha, ex: gente que já estava dispensada e por
  isso não entrou no snapshot automático da criação) e (2) a lista de
  presença do dia (já existente, dá baixa + calcula quem não fez). Novo
  `campanhas.adicionar_membros()`.
- **Consulta geral — filtros por coluna**: cada coluna da tabela (ID, Nome,
  Local de trabalho, Função, Último ASO, Status ASO, Status fila) agora tem
  seu próprio filtro na linha de cabeçalho (texto ou dropdown conforme o
  campo), tudo em JS puro no cliente, sem round-trip ao servidor. Botão
  "Limpar filtros".
- **Visual — verde mais forte e mais detalhe**: usuário achou o visual
  anterior "com cara de IA" (genérico demais). Trocada a paleta pra um verde
  mais saturado (`#0d9668`), adicionados: gradiente sutil nos botões e barra
  de progresso, ícones nos cards de estatística do Dashboard, seções
  agrupadas na sidebar ("Visão geral" / "Operação" / "Suporte") com ícone de
  marca em gradiente, cabeçalhos de página com barra de destaque à esquerda,
  cabeçalho de tabela tingido de verde, badges com indicador de ponto,
  hover/lift em cards e stat-tiles, alertas com borda lateral colorida.
- Validado via `app.test_client()` (DB isolado): fluxo das duas planilhas de
  campanha (RH + presença do dia, incluindo agregação de novo membro),
  validação de cabeçalho bloqueando planilha malformada, ações em lote da
  fila de exceções (aprovar só com score alto, excluir, limpar tudo),
  renderização dos filtros de coluna e dos novos elementos visuais. Servidor
  real reiniciado e todas as rotas conferidas via HTTP depois de cada leva de
  mudanças.
- **Nota de teste**: durante essa sessão também vazou sem querer uma entrada
  de log de teste (`arquivo=mestra.xlsx`) para o `app/data/log_eventos.csv`
  real, por eu ter esquecido de isolar `logs.CAMINHO_LOG` numa das primeiras
  rodadas de teste antes de adotar essa disciplina. Identificado e limpo.

## 2026-09-02 — Reformulação para regras definitivas da campanha 2026

Reescrita de arquitetura pedida pelo usuário para substituir a prova de
conceito pelas regras definitivas da campanha 2026.

- **Base mestre fixa**: deixou de ser upload na interface. Novo
  `app/importacao_base.py` lê `app/data/base_mestra_2026.xlsx` — só importa
  automaticamente se o banco estiver vazio (`carregar_base_mestre_se_vazia`,
  chamado na inicialização do `server.py`); uma recarga manual
  (`recarregar_base_mestre`, botão no Dashboard) atualiza cadastro sem nunca
  regredir `data_ultimo_aso`/status de quem já foi processado — decisão
  tomada porque seguir a instrução literal ("ler o arquivo na inicialização"
  toda vez) apagaria o progresso de campanhas em andamento a cada restart do
  servidor. Comuniquei essa mudança ao usuário antes de implementar.
- **Categorização exclusiva por `local_trabalho`**: `planilhas.py` parou de
  tratar "Filial" como alias de "Local de Trabalho" (agora são colunas
  independentes). `matching.py`, `baixa_diaria.py` e `pdf_pipeline.py` tiveram
  o parâmetro `filial` renomeado para `local_trabalho` em toda a cadeia —
  "filial" continua armazenada, mas nunca mais usada em filtro/matching/campanha.
- **Dashboard (nova home)**: cards de total/dispensados/precisam-exame +
  barras de progresso (%) por local de trabalho.
- **Consulta geral** (substitui "Buscar por ID"): tabela com todos os
  funcionários, filtro por local de trabalho e busca por ID/nome em JS puro
  no cliente (sem round-trip ao servidor), botão "Exportar base atualizada"
  (gera .xlsx on-the-fly a partir do banco atual).
- **Módulo de Campanhas** (substitui as abas isoladas "Importar lista RH" e
  "Baixa diária"): novo `app/campanhas.py` + tabelas `campanhas` e
  `campanha_membros`. Criar uma campanha (local de trabalho + período + kits
  enviados) tira um **snapshot** de quem precisa de exame naquele local
  naquele momento — isso fixa o denominador do progresso (%) mesmo que a base
  mude depois. Cada campanha tem sua própria página com upload de lista de
  presença diária, que reaproveita o motor de `baixa_diaria.py` (agora com
  `campanha_id` linkado) e reflete o progresso imediatamente.
- **Histórico/Logs**: novo `app/logs.py`, log de auditoria simples em
  `app/data/log_eventos.csv` (data/hora/ação/detalhe). Chamado por
  `baixa_diaria.py` (toda baixa processada), `campanhas.py` (criação de
  campanha) e `importacao_base.py` (carga/recarga da base). Nova aba
  "Histórico/Logs" no Flask pra visualizar.
- **PDFs mantidos**: "Separar PDFs" e "PDFs pendentes" continuam intocados
  funcionalmente (só o campo de formulário/parâmetro renomeado para
  `local_trabalho`).
- **Bug real encontrado e corrigido durante os testes**: `planilhas.parse_data`
  usava `pd.to_datetime(texto, dayfirst=True)` pra tudo. Isso corrompia datas
  já em formato ISO (ex: `"2026-09-02"` virava 9 de fevereiro em vez de 2 de
  setembro) sempre que o "dia" era ≤12 — o pandas reinterpretava ISO como
  dia-primeiro. Isso quebrava silenciosamente a lógica de "nunca regredir a
  data" da recarga da base mestre (a comparação `max(existente, arquivo)`
  comparava uma data errada). Corrigido detectando o padrão `YYYY-MM-DD`
  primeiro e usando `date.fromisoformat` direto, sem passar pelo parser
  ambíguo do pandas. Esse bug já existia desde o módulo 1 (afetava qualquer
  reparse de data ISO já gravada) mas só foi pego agora porque a recarga de
  base foi o primeiro código a reparsear uma data ISO existente.
- **Problema de dados real encontrado no banco de produção**: o mesmo local de
  trabalho aparecia com capitalizações diferentes ("CURITIBA" e "Curitiba",
  "BELO HORIZONTE" e "Belo Horizonte"), fragmentando o Dashboard e — mais
  grave — fazendo uma campanha criada para um local perder quem estivesse
  gravado com a outra grafia. Confirmado com o usuário antes de alterar dados
  de produção; corrigido nos ~1.294 registros reais existentes (16 e 41
  registros consolidados respectivamente) e blindado em `importacao_base.py`
  (`_mapa_local_trabalho_existente`/`_linha_para_campos`): novas linhas
  importadas são reconciliadas contra a grafia já usada na base em vez de
  criar uma variante nova.
- **Nota de teste**: durante os testes, descobri que o `app/data/periodicos.db`
  já continha a base real do usuário (~1.294 funcionários, importada quando
  ele testou a versão anterior no navegador) — os testes desta sessão sempre
  isolaram `db.DB_PATH` para um diretório temporário antes de rodar, pra não
  arriscar esses dados. Um teste anterior a essa disciplina (na sessão
  passada, separação de PDF) já tinha vazado um arquivo de teste pra
  `app/data/asos_separados/` — limpo nesta sessão.
- Criado `app/data/base_mestra_2026.xlsx` **sintético** (4 funcionários
  fictícios) só para viabilizar os testes automatizados do bootstrap — não é
  a base real. O usuário precisa substituir esse arquivo pelo Excel real da
  campanha antes de depender dele (a base real já está no banco, importada
  manualmente antes dessa mudança, então isso não bloqueia o uso imediato).
- Validado via `app.test_client()` do Flask (DB isolado): bootstrap da base
  fixa, dashboard, consulta geral + exportação, criação de campanha com
  snapshot correto (excluindo quem já estava dispensado), processamento de
  dia com abate automático e progresso refletido, recarga manual sem
  regressão, fila de exceções via campanha, separação de PDF com
  `local_trabalho`, e geração de logs. Servidor real testado via HTTP sobre a
  base de produção depois — **achado um processo Flask antigo (pré-reforma)
  ainda ocupando a porta 8501**, retornando 404 nas rotas novas; identificado
  e corrigido antes de confirmar o resultado final ao usuário.

## 2026-09-02 — Troca de frontend: Streamlit → Flask + HTML/CSS próprio

- O usuário não gostou do visual padrão do Streamlit ("n gostei nada do
  visual... n gostei"). Reformulação completa do frontend: removido
  `app/app.py` (Streamlit) e `streamlit` do `requirements.txt`; adicionado
  `flask`.
- Novo `app/server.py`: servidor Flask fino, só rotas HTTP — toda a lógica de
  negócio continua nos mesmos módulos (`db.py`, `rules.py`, `matching.py`,
  `resolvers.py`, `planilhas.py`, `baixa_diaria.py`, `pdf_pipeline.py`), sem
  nenhuma mudança de comportamento, só de camada de apresentação.
- Novo `app/templates/` (Jinja2) e `app/static/style.css`: visual próprio
  estilo clínica de saúde — paleta suave (teal/azul, fundo quase-branco),
  cards arredondados com sombra leve, badges coloridos de status, sidebar de
  navegação com ícones. Sem framework JS, sem dependência de CDN externo — só
  HTML + CSS puro servido pelo Flask.
- Todas as 7 páginas do Streamlit foram recriadas: Base mestre, Buscar por ID
  (com formulário de agendamento), Importar lista de RH, Fila de exceções,
  Baixa diária (com download de CSV de inconsistências), Separar PDFs, PDFs
  pendentes.
- Validado com o cliente de teste do Flask (`app.test_client()`) cobrindo:
  redirect da home, upload e resumo da base mestre, busca por ID, salvar
  agendamento, importação de lista de RH com geração de exceção, resolução de
  exceção, processamento de baixa diária, download de CSV (incluindo o caso
  sem inconsistências, que corretamente redireciona com aviso), separação de
  lote de PDF e listagem de pendentes. Servidor real também testado via HTTP
  (todas as rotas respondendo 200/302 como esperado).
- Nota de teste: um teste tentou isolar a pasta de saída de PDFs trocando o
  atributo do módulo (`pdf_pipeline.PASTA_SAIDA_PADRAO = ...`) depois do
  import — não funciona, porque o valor default do parâmetro já foi fixado na
  definição da função no momento do import. O teste acabou escrevendo na
  pasta real `app/data/` (limpa em seguida). Não é um bug de produto, só uma
  armadilha de teste a evitar da próxima vez (passar a pasta explicitamente,
  não via monkeypatch do módulo).

## 2026-09-02 — Módulo 5: Separação inteligente de PDFs (OCR/extração)

- Instaladas `pymupdf`, `pytesseract`, `pillow`. Tesseract (binário de OCR) não
  está instalado no ambiente de desenvolvimento — a extração nativa (PyMuPDF)
  é o caminho principal; OCR é fallback opcional que degrada com aviso claro
  em vez de travar o lote quando o binário não está disponível na máquina.
- Novo `app/pdf_pipeline.py`: extrai texto por página, identifica CPF (regex),
  matrícula (regex com rótulo "Matrícula/Registro/Chapa") e nome candidato,
  agrupa páginas do mesmo ASO e cruza com a base mestre via `matching.py`.
  Salva um PDF por pessoa renomeado (`{matricula}_{NOME}_{data}.pdf`) em
  `data/asos_separados/{filial}/{ano-mes}/`; quem não é identificado vai para
  `excecoes_pdf` + `data/asos_pendentes/`, resolvido manualmente na tela
  (nunca gravado automaticamente).
- **Correção de bug encontrado em teste:** a heurística inicial de agrupamento
  juntava qualquer página sem CPF/matrícula própria à página anterior,
  assumindo que era "continuação". Isso colaria o ASO de uma pessoa
  desconhecida no arquivo de outra pessoa (risco de misatribuição). Corrigido
  para só agrupar com sinal explícito de continuação (palavra-chave como
  "verso"/"anexo"/"continuação", ou página quase em branco) — nunca por
  omissão. Validado com teste que distingue uma página de continuação real de
  uma página de pessoa desconhecida sem identificação.
- Ajuste após o usuário enviar o modelo real do ASO da empresa (TAP
  Saúde/Huawei): o nome aparece no formato "Atesto para os devidos fins, que
  o(a) Sr(a). NOME COMPLETO" (não como "Nome: X"). Adicionado regex dedicado
  para esse padrão.
- **Correção de bug encontrado em teste:** o regex do nome usava
  `re.IGNORECASE` global, o que também afrouxava o grupo de captura do nome
  (deveria aceitar só MAIÚSCULAS) e deixava vazar texto do campo seguinte do
  formulário (ex: "Idade") para dentro do nome capturado. Corrigido para
  aplicar case-insensitive só na palavra "Sr(a)" e manter a captura do nome
  restrita a uma única linha, case-sensitive.
- Validado: extração de matrícula, CPF e nome contra texto que reproduz o
  layout real do ASO (matrícula rotulada, CPF com máscara, nome após "Sr(a).",
  inclusive variando nome na mesma linha ou linha seguinte). Bateria completa
  de separação de lote reexecutada após as correções — 3 PDFs separados
  corretamente, 1 pendência isolada sem contaminar outro funcionário. App
  Streamlit testado subindo local com as duas novas abas (Separar PDFs, PDFs
  pendentes) sem erros.
- Novas abas em `app/app.py`: "Separar PDFs" (upload do lote + processamento)
  e "PDFs pendentes" (revisão manual com texto extraído e candidatos
  sugeridos, aciona `resolver_excecao_pdf()` para mover/renomear o arquivo).
- Nova tabela `excecoes_pdf` em `app/db.py`.

## 2026-09-02 — Módulo 3: Baixa diária + relatório EOD

- Novo `app/baixa_diaria.py`: processa a planilha de quem realizou o exame no
  dia, reaproveitando o pipeline de matching do módulo 1. Quem bate leva baixa
  automática (`data_ultimo_aso`, `status_aso`, `status_fila = 'Concluído'`);
  quem não bate vai para a fila de exceções existente.
- "Quem faltou" é calculado comparando `funcionarios.data_agendada` (novo
  campo) com quem apareceu na planilha do dia — quem estava agendado e não
  apareceu vira `status_fila = 'Faltou'`.
- Decisão confirmada com o usuário: a comparação de faltantes depende de um
  agendamento explícito por pessoa (`data_agendada`), já que o painel de fila
  completo (que geraria isso automaticamente) foi adiado.
- Detecção de inconsistências: nomes não encontrados na base mestre,
  duplicatas dentro da mesma planilha do dia, e reenvio da mesma data de ASO
  já registrada.
- Novo `app/planilhas.py`: extraído de `app.py` para compartilhar
  `parse_data()` e `mapear_colunas()`/`ALIASES_COLUNAS` entre módulos sem
  import circular. Adicionados aliases de coluna para "data de realização" e
  "observações" (planilha de baixa diária).
- `app/matching.py`: `cruzar_lista_rh()` ganhou parâmetro opcional `filial` —
  quando informado, restringe o cruzamento por nome (exato/fuzzy) aos
  funcionários da filial, evitando falso-positivo entre filiais diferentes.
  Match por ID/CPF continua global (chave inequívoca).
- `app/db.py`: novo campo `funcionarios.data_agendada`, com migração leve
  (`ALTER TABLE`) para bancos criados antes dessa mudança.
- Nova aba "Baixa diária" em `app/app.py`: upload da planilha do dia, seleção
  de filial/data, botão de processamento, e relatório com 3 blocos (Fizeram /
  Faltaram / Inconsistências) + download de inconsistências em CSV.
- Aba "Buscar por ID" ganhou formulário para definir `data_agendada` e
  `status_fila` manualmente (substituto mínimo do painel de fila, que fica
  para depois).
- Validado: teste sintético cobrindo match por ID, ausência (faltou), exceção
  (nome desconhecido) e duplicata na mesma planilha — todos os campos da base
  mestre atualizados corretamente. App Streamlit sobe sem erros com a nova aba.

## 2026-09-02 — Módulo 1: Base mestre + motor de regras + reconciliação

- Arquitetura definida: Python + SQLite + Streamlit + rapidfuzz (ver plano em
  `C:\Users\gwx1195653\.claude\plans\atue-como-um-arquiteto-curious-lighthouse.md`).
- Criado `app/db.py`: schema SQLite (`funcionarios`, `filiais`,
  `importacoes_rh`, `excecoes_matching`, `auditoria_llm`).
- Criado `app/rules.py`: regra de corte do ASO (abril = precisa fazer exame,
  maio em diante = dispensado), parametrizável por ano/mês de corte.
- Criado `app/matching.py`: pipeline de cruzamento em camadas (ID → CPF →
  nome exato → nome fuzzy → exceção), sem decidir sozinho os casos ambíguos.
- Criado `app/resolvers.py`: camada de reconciliação de exceções pluggable —
  `ResolvedorManual` (ativo) e `ResolvedorLLM` (esqueleto para OpenAI/Gemini,
  a pedido explícito do usuário, para tratar nomes digitados errado e
  observações em texto livre no futuro). Nenhuma resolução é gravada na base
  mestre sem confirmação humana.
- Criado `app/app.py`: interface Streamlit com abas de upload da base mestre,
  busca por ID, importação de lista de RH (roda o cruzamento) e fila de
  exceções (confirmação manual).
- Ajuste de schema após o usuário mostrar a planilha mestra real: colunas
  passaram a ser Matricula (chave primária), Nome, Empresa, Filial, GHE/Área,
  Local de Trabalho, Função, Data de Admissão, Tipo de Aso, Data Aso. Criado
  mapeamento flexível de nomes de coluna (`ALIASES_COLUNAS`) e parser de data
  que aceita tanto texto formatado quanto serial do Excel.
- Decisão confirmada com o usuário: a regra de corte usa **somente** a data do
  último ASO — o campo `Tipo de Aso` (ex: PERIÓDICO BIENAL vs ADMISSIONAL) é
  armazenado mas não influencia o cálculo de status.
- Validado: testes sintéticos da regra de corte (datas antes/depois do corte,
  ASO ausente) e do pipeline de matching (ID, CPF, nome exato, fuzzy com typo,
  exceção). App Streamlit testado subindo local (HTTP 200, sem erros de log).

## Próximos passos

- Módulo 4 (Painel de fila da Matriz SP) — adiado a pedido do usuário.
- Módulo 5 (Separação inteligente de PDFs / OCR) — não iniciado.
- Implementação real do `ResolvedorLLM` (hoje é só o esqueleto/interface).
