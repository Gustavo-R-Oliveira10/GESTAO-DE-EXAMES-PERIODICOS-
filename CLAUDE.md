# Controle de Exames Periódicos — Projeto

Ferramenta interna e leve (uso individual) para gerenciar a campanha de exames
periódicos (ASO) de ~1.295 funcionários, distribuídos por local de trabalho
(São Paulo, Brasília, Botafogo, Península, Curitiba, Belo Horizonte, Recife,
Sorocaba, entre outros — ver base real).

O plano de arquitetura original está em
`C:\Users\gwx1195653\.claude\plans\atue-como-um-arquiteto-curious-lighthouse.md`.
Consulte-o para o contexto da decisão inicial de stack (histórico; algumas
decisões documentadas ali foram substituídas pela reformulação da campanha
2026 — este arquivo é a fonte da verdade atual).

## Stack

- **Linguagem:** Python 3.14
- **Banco de dados:** SQLite (arquivo único em `app/data/periodicos.db`, criado automaticamente)
- **Interface:** Flask + HTML/CSS próprio (`python server.py`, roda local em `http://localhost:8501`).
  Streamlit foi removido a pedido do usuário (não gostou do visual padrão).
  Front feito à mão (templates Jinja + CSS puro, sem framework JS), estilo
  clínica de saúde: cores suaves (teal/azul), cards arredondados.
- **Matching de nomes:** rapidfuzz
- **Planilhas:** pandas + openpyxl

## Como rodar

```
cd app
python server.py
```

Abre em `http://localhost:8501`. Não é `flask run` — o entrypoint é
`server.py` diretamente (tem `app.run(...)` no final do arquivo).

**Ou dê 2 cliques em `iniciar_app.vbs`** (raiz do projeto) — sobe o servidor
em segundo plano (sem janela de terminal) e abre numa janela própria do Edge
(`--app=`, sem barra de endereço), como se fosse um programa instalado. Pra
criar um atalho na área de trabalho: botão direito no `.vbs` → Enviar para →
Área de trabalho (criar atalho).

## Base mestre real (correção 2026-09-03)

`app/importacao_base.CAMINHO_BASE_MESTRE_FIXA` aponta para
`PERIODICOS - BASE MESTRA.xlsx` na **raiz do projeto** (não `app/data/`) —
é o arquivo que o usuário mantém e edita manualmente no Excel (ex: corrigir
o local de trabalho de alguém). O app nunca escreve nele, só lê. Toda leitura
(carga inicial ou "Recarregar base do arquivo" no Dashboard) salva uma cópia
com data/hora em `app/data/backups_base_mestra/` antes de processar — nunca
apagada automaticamente, serve de ponto de recuperação.

**Cuidado com parsing de data**: `planilhas.parse_data()` já corrigiu duas
vezes o mesmo bug (`pd.to_datetime(dayfirst=True)` trocando dia/mês quando o
dia é ≤12) — primeiro para ISO puro (`"2026-09-02"`), depois para ISO com
hora (`"2026-02-09 00:00:00"`, formato real que vem do Excel). Se aparecer
uma data suspeita de novo, comece verificando esse ponto antes de qualquer
outra hipótese. Há testes de regressão específicos em
`app/tests/test_planilhas.py`.

## Testes

`app/tests/` (pytest, 56 testes). Rodar com `cd app && python -m pytest
tests/ -v`. `conftest.py` tem uma fixture `autouse` que isola banco, log e
pasta de backups num diretório temporário em **todo** teste automaticamente
— nunca precisa (nem deve) apontar manualmente pro banco real num teste.

## Git

Repositório: https://github.com/Gustavo-R-Oliveira10/GESTAO-DE-EXAMES-PERIODICOS-.
Fluxo de trabalho (branch → commit → push → merge pra main) documentado em
`GIT_WORKFLOW.md` — siga sempre esse passo a passo.

**`.gitignore` crítico:** `app/data/` inteira (banco, base mestre real, logs,
PDFs de ASO) e qualquer `.xlsx`/`.xls` em qualquer lugar do projeto nunca são
versionados — são dados reais de funcionário (nome, CPF, resultado de exame
médico). **Sempre rode `git status` antes de `git add -A`** e confira que
nada disso aparece na lista antes de commitar. Já aconteceu uma vez, nesta
sessão, de um `PERIODICOS - BASE MESTRA.xlsx` real estar solto na raiz do
projeto e quase ir pro primeiro commit — foi pego a tempo revisando o
`git status` antes de commitar, e o `.gitignore` foi reforçado com um padrão
`*.xlsx`/`*.xls` genérico por causa disso.

Nota de ambiente: o mirror pip corporativo (`mirrors.tools.huawei.com`) não
resolveu neste ambiente de desenvolvimento; as dependências foram instaladas
via `pip install --index-url https://pypi.org/simple -r requirements.txt`.

## Base mestre fixa (campanha 2026)

**A partir da reformulação de 2026-09-02, a base mestre não é mais enviada por
upload.** O arquivo fica fixo em `app/data/base_mestra_2026.xlsx` e:

- É importado **automaticamente só na primeira vez** que o servidor sobe com o
  banco vazio (`importacao_base.carregar_base_mestre_se_vazia`). Reiniciar o
  servidor depois disso **não** reimporta — isso é proposital, pra não
  sobrescrever o progresso de campanhas já processadas.
- Para atualizar o cadastro (novas admissões, mudança de função/local etc.)
  depois disso, use o botão **"Recarregar base do arquivo"** no Dashboard
  (`importacao_base.recarregar_base_mestre`). Essa recarga atualiza campos
  cadastrais normalmente, mas **nunca regride** `data_ultimo_aso`/`status_aso`
  — fica sempre a data mais recente entre o banco e o arquivo, pra não apagar
  uma baixa já processada numa campanha em andamento.
- **⚠️ Pendência:** o arquivo hoje em `app/data/base_mestra_2026.xlsx` é um
  **placeholder sintético** criado para testes (4 funcionários fictícios).
  Substitua pelo Excel real da campanha 2026 antes de zerar o banco / rodar em
  outra máquina. A base de produção real (~1.294 funcionários) já está
  carregada no `periodicos.db` atual (importada manualmente antes dessa
  mudança) e não precisa desse arquivo pra continuar funcionando.

## Categorização por local — regra inegociável

Toda categorização/agrupamento/filtro do sistema usa **exclusivamente** a
coluna `local_trabalho` (Local de Trabalho na planilha). A coluna `filial`
(razão social/legal) é só guardada como dado de referência — nunca entra em
matching, dashboard, ou campanha. Isso vale em `matching.py`,
`baixa_diaria.py`, `pdf_pipeline.py`, `campanhas.py`.

**Cuidado com capitalização:** a planilha real veio com o mesmo local escrito
de formas diferentes (ex: "CURITIBA" vs "Curitiba"), o que fragmentava
dashboard e campanhas. Corrigido nos dados existentes; `importacao_base.py`
agora reconcilia automaticamonce novas linhas contra a grafia já usada na base
(`_mapa_local_trabalho_existente` / `_linha_para_campos`), então isso não
deve mais se repetir em recargas futuras — mas vale checar o Dashboard depois
de cada recarga se aparecer um local nunca visto antes.

## Estrutura do código (`app/`)

- `db.py` — schema SQLite e conexão. `init_db()` cria as tabelas e aplica
  migrações leves (`ALTER TABLE`) para bancos já existentes quando o schema evolui.
- `rules.py` — regra de corte do ASO: `status_aso(data_ultimo_aso, ano_campanha)`.
  Olha só a data do último ASO (abril = precisa refazer, maio em diante =
  dispensado) — o campo `tipo_aso` (ex: PERIÓDICO BIENAL) é armazenado mas
  **não** entra na regra (confirmado com o usuário).
- `planilhas.py` — leitura de Excel: `parse_data()` (aceita data formatada,
  serial do Excel, **ou ISO já gravado pelo próprio sistema** — cuidado: uma
  versão anterior usava `dayfirst=True` do pandas pra tudo, o que corrompia
  datas ISO tipo "2026-09-02" → 9-fev; agora ISO é detectado e parseado direto
  via `date.fromisoformat`) e `mapear_colunas()` (mapeia os nomes reais das
  colunas da empresa pros nomes internos). Ver `ALIASES_COLUNAS`.
- `matching.py` — pipeline de cruzamento em camadas: ID exato → CPF exato →
  nome normalizado exato → nome fuzzy (rapidfuzz, threshold 90) → exceção.
  Match por ID/CPF é sempre global; o filtro por `local_trabalho` (quando
  informado) restringe apenas as camadas de nome.
- `resolvers.py` — camada de reconciliação de exceções, **pluggable**:
  `ResolvedorManual` (ativo hoje) e `ResolvedorLLM` (esqueleto pronto pra
  OpenAI/Gemini). Nenhum resolvedor escreve na base sozinho — toda sugestão
  passa por confirmação humana na tela.
- `baixa_diaria.py` — motor de baixa + relatório EOD (fizeram/faltaram/
  inconsistências). Usado por dentro de uma campanha (`campanhas.py`), não
  mais como aba isolada. Registra cada processamento em `logs.py`.
- `campanhas.py` — módulo de Gestão de Campanhas (substitui as antigas abas
  "Importar lista RH" e "Baixa diária"). Uma campanha fixa (`campanha_membros`)
  quem precisa de exame num `local_trabalho` no momento da criação — isso é o
  denominador do progresso (%), e não muda mesmo se a base mudar depois.
  `criar_campanha`, `listar_campanhas`, `obter_campanha`,
  `listar_membros_pendentes/concluidos`.
- `importacao_base.py` — importação da base mestre fixa (ver seção acima).
- `logs.py` — log de auditoria em `app/data/log_eventos.csv` (data/hora/ação).
  `registrar_log()` é chamado por `baixa_diaria.py`, `campanhas.py` e
  `importacao_base.py` toda vez que a base mestre é alterada em lote.
- `pdf_pipeline.py` — separação de PDFs em lote (inalterado nesta reforma,
  só o parâmetro `filial` virou `local_trabalho`). Extrai texto por página
  (nativo via PyMuPDF; OCR via pytesseract como fallback, se o binário do
  Tesseract estiver instalado). Agrupa páginas do mesmo ASO **apenas com sinal
  explícito de continuação** (nunca por omissão). Quem não é identificado vai
  para `excecoes_pdf` + `data/asos_pendentes/`, resolvido manualmente.
- `server.py` — servidor Flask. Só rotas HTTP e renderização. Páginas:
  Dashboard, Consulta geral, Campanhas (lista + detalhe por campanha), Fila de
  exceções, Separar PDFs, PDFs pendentes, Histórico/Logs.
- `templates/` — HTML (Jinja2) + `base.html` (sidebar de navegação).
- `static/style.css` — visual: paleta em `:root`, cards, badges, tabelas,
  barras de progresso. Sem dependência externa.

## Convenções de dados

- **Chave primária:** Matricula (coluna `id` no banco) — não CPF.
- Datas guardadas como `TEXT` ISO (`YYYY-MM-DD`) no SQLite.
- `status_fila`: `Aguardando | Cobrança enviada | Concluído | Faltou`.
- `data_agendada`: campo legado — ainda usado por `baixa_diaria.py` pra
  calcular "faltou", mas não há mais UI dedicada pra setá-lo pessoa a pessoa
  (a aba "Buscar por ID" foi substituída pela "Consulta geral", que não expõe
  esse campo). Na prática o cálculo de faltantes fica vazio a menos que algo
  volte a popular esse campo — não é um bug, é uma lacuna conhecida.

## Módulos do sistema (visão geral)

1. ✅ Base mestre fixa + motor de regras
2. ✅ Camada de reconciliação de exceções (pluggable p/ LLM)
3. ✅ Gestão de Campanhas (baixa diária embutida, progresso em %)
4. ✅ Dashboard gerencial (cards + % de conclusão por local de trabalho)
5. ✅ Consulta geral (tabela dinâmica + exportação)
6. ✅ Separação inteligente de PDFs
7. ✅ Histórico/Logs (auditoria em CSV)
8. ⏳ Painel de fila dedicado da Matriz SP — nunca chegou a ser construído
   como módulo isolado; o conceito de fila (`status_fila`) existe no schema
   mas hoje só é setado via baixa diária dentro de uma campanha.

## Histórico de validação

Ver `CHANGELOG.md` para o que foi validado em cada etapa e os bugs reais
encontrados e corrigidos ao longo do desenvolvimento (agrupamento de PDF
colando pessoas diferentes, `parse_data` corrompendo datas ISO em duas
variantes, backup colidindo no mesmo segundo, entre outros).
