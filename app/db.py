"""Camada de banco de dados (SQLite) — schema e conexão."""
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "periodicos.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS funcionarios (
    id TEXT PRIMARY KEY,              -- Matricula (planilha mestra)
    nome TEXT NOT NULL,
    nome_normalizado TEXT NOT NULL,
    cpf TEXT,                         -- opcional, nem sempre presente na planilha
    empresa TEXT,
    filial TEXT,
    ghe_area TEXT,
    local_trabalho TEXT,
    funcao TEXT,
    data_admissao TEXT,
    tipo_aso TEXT,                    -- ex: PERIÓDICO BIENAL, ADMISSIONAL
    data_ultimo_aso TEXT,
    status_aso TEXT,
    status_fila TEXT DEFAULT 'Aguardando',  -- Aguardando | Cobrança enviada | Concluído | Faltou
    data_agendada TEXT,                     -- dia em que o funcionário está previsto para o exame
    observacoes_livres TEXT
);

CREATE INDEX IF NOT EXISTS idx_funcionarios_nome_normalizado
    ON funcionarios(nome_normalizado);
CREATE INDEX IF NOT EXISTS idx_funcionarios_cpf ON funcionarios(cpf);
CREATE INDEX IF NOT EXISTS idx_funcionarios_filial ON funcionarios(filial);
CREATE INDEX IF NOT EXISTS idx_funcionarios_local_trabalho ON funcionarios(local_trabalho);

CREATE TABLE IF NOT EXISTS filiais (
    nome TEXT PRIMARY KEY,
    responsavel_rh TEXT,
    headcount_esperado INTEGER
);

CREATE TABLE IF NOT EXISTS importacoes_rh (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    filial TEXT,                        -- na verdade guarda o local_trabalho usado no filtro
    arquivo TEXT,
    data_importacao TEXT NOT NULL,
    total_linhas INTEGER,
    total_match_automatico INTEGER,
    total_excecoes INTEGER,
    campanha_id INTEGER REFERENCES campanhas(id)
);

CREATE TABLE IF NOT EXISTS campanhas (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    local_trabalho TEXT NOT NULL,
    data_inicio TEXT NOT NULL,
    data_fim TEXT NOT NULL,
    kits_enviados INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'ativa',   -- ativa | encerrada
    detalhe_operacao TEXT,                  -- ex: "09h00 às 18h00 (8h de atendimento)"
    lista_rh_processada_em TEXT,            -- setado uma única vez, trava novo upload
    lista_rh_arquivo TEXT,
    criado_em TEXT NOT NULL
);

-- Membros "convocados": quem, no momento em que a lista do RH foi cruzada
-- contra a base mestre, estava com o ASO vencido. É o denominador fixo do
-- progresso (%) — a lista do RH sozinha não dita a meta, só quem realmente
-- está vencido entra aqui. Populado uma única vez (trava de upload).
CREATE TABLE IF NOT EXISTS campanha_membros (
    campanha_id INTEGER NOT NULL REFERENCES campanhas(id),
    funcionario_id TEXT NOT NULL REFERENCES funcionarios(id),
    PRIMARY KEY (campanha_id, funcionario_id)
);

-- Resultado persistido do cruzamento da lista do RH contra a base mestre,
-- pra tela de detalhe conseguir mostrar as tabelas "Convocados" e "Já
-- Dispensados" depois do fato, sem precisar reprocessar o arquivo.
CREATE TABLE IF NOT EXISTS campanha_rh_resultado (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campanha_id INTEGER NOT NULL REFERENCES campanhas(id),
    funcionario_id TEXT NOT NULL REFERENCES funcionarios(id),
    nome TEXT NOT NULL,
    categoria TEXT NOT NULL,   -- convocado | ja_dispensado
    criado_em TEXT NOT NULL
);

-- Dias reais de atendimento médico da campanha (ex: Brasília teve 02/09 e
-- 04/09, com horários diferentes cada um) — vem do cronograma oficial.
-- Permite saber "quantos foram no dia X" separado de "quantos foram no
-- total", já que uma campanha pode ter vários dias não-contíguos.
CREATE TABLE IF NOT EXISTS campanha_dias (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    campanha_id INTEGER NOT NULL REFERENCES campanhas(id),
    data TEXT NOT NULL,
    hora_inicio TEXT,
    hora_fim TEXT
);

-- Registro de quem efetivamente compareceu (recebeu baixa) dentro de uma
-- campanha, e em qual dia. Existe pra separar "Concluído porque fez o exame
-- nesta campanha" de "Concluído porque já estava com o ASO em dia por outro
-- motivo" — as duas coisas deixam status_aso='Dispensado' igual, mas só a
-- primeira representa comparecimento real nesta campanha.
CREATE TABLE IF NOT EXISTS campanha_atendimentos (
    campanha_id INTEGER NOT NULL REFERENCES campanhas(id),
    funcionario_id TEXT NOT NULL REFERENCES funcionarios(id),
    data_atendimento TEXT NOT NULL,
    criado_em TEXT NOT NULL,
    PRIMARY KEY (campanha_id, funcionario_id)
);

CREATE TABLE IF NOT EXISTS excecoes_matching (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    importacao_id INTEGER REFERENCES importacoes_rh(id),
    texto_bruto TEXT NOT NULL,
    candidatos_json TEXT,
    status TEXT NOT NULL DEFAULT 'pendente',
    funcionario_id_resolvido TEXT REFERENCES funcionarios(id),
    origem_resolucao TEXT,
    confirmado_por TEXT,
    criado_em TEXT NOT NULL,
    resolvido_em TEXT
);

CREATE TABLE IF NOT EXISTS excecoes_pdf (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    arquivo_origem TEXT NOT NULL,
    paginas TEXT NOT NULL,              -- json com os índices de página no PDF original
    texto_extraido TEXT,
    metodo_extracao TEXT,               -- nativo | ocr | falhou
    candidatos_json TEXT,
    caminho_pdf_pendente TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pendente',
    funcionario_id_resolvido TEXT REFERENCES funcionarios(id),
    confirmado_por TEXT,
    criado_em TEXT NOT NULL,
    resolvido_em TEXT
);

CREATE TABLE IF NOT EXISTS auditoria_llm (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    excecao_id INTEGER REFERENCES excecoes_matching(id),
    provedor TEXT,
    entrada_enviada TEXT,
    resposta_recebida TEXT,
    confianca REAL,
    aceito INTEGER,
    criado_em TEXT NOT NULL
);
"""


def get_connection() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def _colunas_existentes(conn: sqlite3.Connection, tabela: str) -> set[str]:
    return {row["name"] for row in conn.execute(f"PRAGMA table_info({tabela})")}


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        # migração leve: adiciona colunas novas em bancos criados por versões anteriores do schema
        colunas_funcionarios = _colunas_existentes(conn, "funcionarios")
        if "data_agendada" not in colunas_funcionarios:
            conn.execute("ALTER TABLE funcionarios ADD COLUMN data_agendada TEXT")
            conn.commit()

        colunas_importacoes = _colunas_existentes(conn, "importacoes_rh")
        if "campanha_id" not in colunas_importacoes:
            conn.execute("ALTER TABLE importacoes_rh ADD COLUMN campanha_id INTEGER REFERENCES campanhas(id)")
            conn.commit()

        colunas_campanhas = _colunas_existentes(conn, "campanhas")
        if "detalhe_operacao" not in colunas_campanhas:
            conn.execute("ALTER TABLE campanhas ADD COLUMN detalhe_operacao TEXT")
            conn.commit()
        if "lista_rh_processada_em" not in colunas_campanhas:
            conn.execute("ALTER TABLE campanhas ADD COLUMN lista_rh_processada_em TEXT")
            conn.commit()
        if "lista_rh_arquivo" not in colunas_campanhas:
            conn.execute("ALTER TABLE campanhas ADD COLUMN lista_rh_arquivo TEXT")
            conn.commit()
    finally:
        conn.close()
