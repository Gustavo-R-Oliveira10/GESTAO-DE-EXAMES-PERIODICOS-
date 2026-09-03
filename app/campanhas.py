"""Módulo de Gestão de Campanhas.

Uma campanha agrupa o atendimento de um local de trabalho num período. A meta
(denominador do progresso em %) não é definida cegamente pela lista que o RH
manda nem por um snapshot automático na criação — é definida pelo cruzamento
dessa lista contra a base mestre: só quem está com o ASO **vencido** no
momento do cruzamento vira "Convocado" (conta pra meta). Quem a lista trouxe
mas já está "Dispensado" é barrado e mostrado à parte ("Já Dispensados"),
sem contar pra meta. Esse cruzamento acontece **uma única vez** por campanha
(trava de upload) — ver `campanha_ja_processou_lista_rh`.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from sqlite3 import Connection

from logs import registrar_log


@dataclass
class Campanha:
    id: int
    local_trabalho: str
    data_inicio: str
    data_fim: str
    kits_enviados: bool
    status: str
    criado_em: str
    detalhe_operacao: str | None = None
    lista_rh_processada_em: str | None = None
    lista_rh_arquivo: str | None = None
    total_funcionarios_filial: int = 0  # todo mundo do local_trabalho, independente de precisar de exame
    total_membros: int = 0       # meta desta campanha — ASO vencido no cruzamento com a lista do RH
    concluidos: int = 0          # fizeram + nao_precisou (status_aso='Dispensado', por qualquer motivo)
    fizeram: int = 0             # da própria filial que compareceram de verdade nesta campanha
    fora_do_local: int = 0       # de OUTRA filial que também compareceram aqui (ex: SP fazendo em Brasília)
    nao_precisou: int = 0        # já estavam com ASO em dia por outro motivo, nunca vieram a esta campanha
    pendentes: int = 0           # ainda precisam fazer o exame

    @property
    def fizeram_total(self) -> int:
        """Total de comparecimentos reais nesta campanha, incluindo gente de
        fora da filial — é o número físico de exames feitos aqui."""
        return self.fizeram + self.fora_do_local

    @property
    def precisam_exame(self) -> int:
        """Quantos da meta ainda precisam (ou precisaram) vir fazer o exame
        nesta campanha de verdade — meta menos quem já ficou em dia por fora
        (nao_precisou). É fizeram + pendentes, e é o denominador certo do
        comparecimento (total_membros conta gente que nunca precisou vir)."""
        return self.total_membros - self.nao_precisou

    @property
    def percentual_concluido(self) -> float:
        if not self.total_membros:
            return 0.0
        return round(self.concluidos / self.total_membros * 100, 1)

    @property
    def percentual_compareceram(self) -> float:
        """% de quem realmente precisava vir fazer o exame nesta campanha e já
        veio (exclui do denominador quem nunca precisou comparecer, pois
        ficou em dia por fora) — mede o comparecimento de verdade.
        Só conta gente da própria filial (fora_do_local não faz parte da meta)."""
        if not self.precisam_exame:
            return 0.0
        return round(self.fizeram / self.precisam_exame * 100, 1)

    @property
    def lista_rh_travada(self) -> bool:
        return bool(self.lista_rh_processada_em)


def criar_campanha(
    conn: Connection,
    local_trabalho: str,
    data_inicio: date,
    data_fim: date,
    kits_enviados: bool,
    detalhe_operacao: str | None = None,
) -> int:
    """Cria só a campanha (local + período + kits). A meta (campanha_membros)
    fica vazia até a lista do RH ser cruzada contra a base mestre — ver
    `registrar_resultado_lista_rh`. Isso evita que a meta seja definida antes
    de sabermos de verdade quem está vencido."""
    agora = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO campanhas (local_trabalho, data_inicio, data_fim, kits_enviados, status, detalhe_operacao, criado_em)
        VALUES (?, ?, ?, ?, 'ativa', ?, ?)
        """,
        (local_trabalho, data_inicio.isoformat(), data_fim.isoformat(), int(kits_enviados), detalhe_operacao, agora),
    )
    campanha_id = cur.lastrowid
    conn.commit()

    registrar_log(
        "Campanha criada",
        f"id={campanha_id} local_trabalho={local_trabalho} periodo={data_inicio.isoformat()}"
        f"..{data_fim.isoformat()} kits_enviados={kits_enviados}",
    )
    return campanha_id


def _linha_para_campanha(row) -> Campanha:
    return Campanha(
        id=row["id"],
        local_trabalho=row["local_trabalho"],
        data_inicio=row["data_inicio"],
        data_fim=row["data_fim"],
        kits_enviados=bool(row["kits_enviados"]),
        status=row["status"],
        criado_em=row["criado_em"],
        detalhe_operacao=row["detalhe_operacao"],
        lista_rh_processada_em=row["lista_rh_processada_em"],
        lista_rh_arquivo=row["lista_rh_arquivo"],
        total_funcionarios_filial=row["total_funcionarios_filial"] or 0,
        total_membros=row["total_membros"] or 0,
        concluidos=row["concluidos"] or 0,
        fizeram=row["fizeram"] or 0,
        fora_do_local=row["fora_do_local"] or 0,
        nao_precisou=row["nao_precisou"] or 0,
        pendentes=row["pendentes"] or 0,
    )


# Subconsultas em vez de JOIN único: um LEFT JOIN encadeado (membros -> ca)
# multiplicaria linhas e complicaria contar "fora_do_local" (que por
# definição não está em campanha_membros) na mesma query. Cada métrica fica
# isolada e correta, ao custo de mais subqueries — no volume desta tabela
# (algumas dezenas de campanhas) é irrelevante pra performance.
_QUERY_CAMPANHAS_COM_PROGRESSO = """
    SELECT c.*,
        (SELECT COUNT(*) FROM funcionarios f WHERE f.local_trabalho = c.local_trabalho)
            AS total_funcionarios_filial,
        (SELECT COUNT(*) FROM campanha_membros cm WHERE cm.campanha_id = c.id)
            AS total_membros,
        (SELECT COUNT(*) FROM campanha_membros cm JOIN funcionarios f ON f.id = cm.funcionario_id
            WHERE cm.campanha_id = c.id AND f.status_aso = 'Dispensado')
            AS concluidos,
        (SELECT COUNT(*) FROM campanha_membros cm JOIN campanha_atendimentos ca
            ON ca.campanha_id = cm.campanha_id AND ca.funcionario_id = cm.funcionario_id
            WHERE cm.campanha_id = c.id)
            AS fizeram,
        (SELECT COUNT(*) FROM campanha_atendimentos ca
            WHERE ca.campanha_id = c.id
            AND NOT EXISTS (
                SELECT 1 FROM campanha_membros cm
                WHERE cm.campanha_id = ca.campanha_id AND cm.funcionario_id = ca.funcionario_id
            ))
            AS fora_do_local,
        (SELECT COUNT(*) FROM campanha_membros cm JOIN funcionarios f ON f.id = cm.funcionario_id
            LEFT JOIN campanha_atendimentos ca ON ca.campanha_id = cm.campanha_id AND ca.funcionario_id = cm.funcionario_id
            WHERE cm.campanha_id = c.id AND f.status_aso = 'Dispensado' AND ca.funcionario_id IS NULL)
            AS nao_precisou,
        (SELECT COUNT(*) FROM campanha_membros cm JOIN funcionarios f ON f.id = cm.funcionario_id
            WHERE cm.campanha_id = c.id AND f.status_aso != 'Dispensado')
            AS pendentes
    FROM campanhas c
"""


def listar_campanhas(conn: Connection) -> list[Campanha]:
    rows = conn.execute(
        _QUERY_CAMPANHAS_COM_PROGRESSO + " ORDER BY c.criado_em DESC"
    ).fetchall()
    return [_linha_para_campanha(r) for r in rows]


def obter_campanha(conn: Connection, campanha_id: int) -> Campanha | None:
    row = conn.execute(
        _QUERY_CAMPANHAS_COM_PROGRESSO + " WHERE c.id = ?", (campanha_id,)
    ).fetchone()
    return _linha_para_campanha(row) if row else None


def listar_membros_pendentes(conn: Connection, campanha_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT f.* FROM campanha_membros cm
        JOIN funcionarios f ON f.id = cm.funcionario_id
        WHERE cm.campanha_id = ? AND f.status_aso != 'Dispensado'
        ORDER BY f.nome
        """,
        (campanha_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def listar_membros_concluidos(conn: Connection, campanha_id: int) -> list[dict]:
    rows = conn.execute(
        """
        SELECT f.* FROM campanha_membros cm
        JOIN funcionarios f ON f.id = cm.funcionario_id
        WHERE cm.campanha_id = ? AND f.status_aso = 'Dispensado'
        ORDER BY f.nome
        """,
        (campanha_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def listar_membros_fizeram(conn: Connection, campanha_id: int) -> list[dict]:
    """Quem da própria filial (convocado desta campanha) realmente
    compareceu, com a data de comparecimento. Não inclui gente de fora da
    filial que também fez aqui — ver `listar_membros_fora_do_local`."""
    rows = conn.execute(
        """
        SELECT f.*, ca.data_atendimento
        FROM campanha_atendimentos ca
        JOIN funcionarios f ON f.id = ca.funcionario_id
        JOIN campanha_membros cm ON cm.campanha_id = ca.campanha_id AND cm.funcionario_id = ca.funcionario_id
        WHERE ca.campanha_id = ?
        ORDER BY ca.data_atendimento, f.nome
        """,
        (campanha_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def listar_membros_fora_do_local(conn: Connection, campanha_id: int) -> list[dict]:
    """Gente de OUTRA filial que compareceu nesta campanha (ex: alguém
    lotado em São Paulo que fez o exame na campanha de Brasília). Casa
    sempre pelo ID/matrícula — nunca deixa de dar baixa na base mestre só
    porque a pessoa não é 'da casa' deste local; só fica sinalizado à parte
    pra não inflar a meta/headcount da filial que sediou o atendimento."""
    rows = conn.execute(
        """
        SELECT f.*, ca.data_atendimento
        FROM campanha_atendimentos ca
        JOIN funcionarios f ON f.id = ca.funcionario_id
        WHERE ca.campanha_id = ?
        AND NOT EXISTS (
            SELECT 1 FROM campanha_membros cm
            WHERE cm.campanha_id = ca.campanha_id AND cm.funcionario_id = ca.funcionario_id
        )
        ORDER BY ca.data_atendimento, f.nome
        """,
        (campanha_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def listar_membros_nao_precisou(conn: Connection, campanha_id: int) -> list[dict]:
    """Convocados que já estavam com o ASO em dia, mas nunca compareceram a
    esta campanha — ficaram assim por algum outro motivo (recarga da base,
    exame feito fora, etc)."""
    rows = conn.execute(
        """
        SELECT f.* FROM campanha_membros cm
        JOIN funcionarios f ON f.id = cm.funcionario_id
        LEFT JOIN campanha_atendimentos ca ON ca.campanha_id = cm.campanha_id AND ca.funcionario_id = cm.funcionario_id
        WHERE cm.campanha_id = ? AND f.status_aso = 'Dispensado' AND ca.funcionario_id IS NULL
        ORDER BY f.nome
        """,
        (campanha_id,),
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Cruzamento da lista do RH — trava de upload único
# ---------------------------------------------------------------------------
def campanha_ja_processou_lista_rh(conn: Connection, campanha_id: int) -> bool:
    row = conn.execute(
        "SELECT lista_rh_processada_em FROM campanhas WHERE id = ?", (campanha_id,)
    ).fetchone()
    return bool(row and row["lista_rh_processada_em"])


def registrar_resultado_lista_rh(
    conn: Connection,
    campanha_id: int,
    arquivo: str,
    convocados: list[dict],
    ja_dispensados: list[dict],
) -> None:
    """Grava o resultado do cruzamento (uma única vez) e trava novo upload.
    `convocados`/`ja_dispensados`: lista de {"funcionario_id": ..., "nome": ...}.
    Convocados entram em `campanha_membros` (contam pra meta); já dispensados
    só ficam registrados em `campanha_rh_resultado` pra exibição, sem contar."""
    agora = datetime.now().isoformat(timespec="seconds")

    conn.execute(
        "UPDATE campanhas SET lista_rh_processada_em = ?, lista_rh_arquivo = ? WHERE id = ?",
        (agora, arquivo, campanha_id),
    )
    conn.executemany(
        "INSERT OR IGNORE INTO campanha_membros (campanha_id, funcionario_id) VALUES (?, ?)",
        [(campanha_id, c["funcionario_id"]) for c in convocados],
    )
    conn.executemany(
        """
        INSERT INTO campanha_rh_resultado (campanha_id, funcionario_id, nome, categoria, criado_em)
        VALUES (?, ?, ?, 'convocado', ?)
        """,
        [(campanha_id, c["funcionario_id"], c["nome"], agora) for c in convocados],
    )
    conn.executemany(
        """
        INSERT INTO campanha_rh_resultado (campanha_id, funcionario_id, nome, categoria, criado_em)
        VALUES (?, ?, ?, 'ja_dispensado', ?)
        """,
        [(campanha_id, c["funcionario_id"], c["nome"], agora) for c in ja_dispensados],
    )
    conn.commit()

    registrar_log(
        "Lista do RH cruzada com a base mestre (trava de upload único)",
        f"campanha_id={campanha_id} arquivo={arquivo} "
        f"convocados={len(convocados)} ja_dispensados={len(ja_dispensados)}",
    )


def obter_resultado_lista_rh(conn: Connection, campanha_id: int) -> tuple[list[dict], list[dict]]:
    convocados = conn.execute(
        "SELECT * FROM campanha_rh_resultado WHERE campanha_id = ? AND categoria = 'convocado' ORDER BY nome",
        (campanha_id,),
    ).fetchall()
    ja_dispensados = conn.execute(
        "SELECT * FROM campanha_rh_resultado WHERE campanha_id = ? AND categoria = 'ja_dispensado' ORDER BY nome",
        (campanha_id,),
    ).fetchall()
    return [dict(r) for r in convocados], [dict(r) for r in ja_dispensados]


# ---------------------------------------------------------------------------
# Seed do cronograma oficial
# ---------------------------------------------------------------------------
# local_trabalho precisa bater exatamente com o valor gravado na base mestre
# (conferido contra a planilha real: "Brasilia" sem acento, "Botafogo" e
# "Península" sem o prefixo "Rio de Janeiro").
CRONOGRAMA_OFICIAL = [
    {
        "local_trabalho": "Brasilia",
        "data_inicio": date(2026, 9, 2),
        "data_fim": date(2026, 9, 4),
        "detalhe_operacao": "09h00 às 18h00",
    },
    {
        "local_trabalho": "Botafogo",
        "data_inicio": date(2026, 9, 25),
        "data_fim": date(2026, 10, 5),
        "detalhe_operacao": "09h00 às 18h00 (8h de atendimento por dia — 25/09 e 05/10)",
    },
    {
        "local_trabalho": "Península",
        "data_inicio": date(2026, 9, 28),
        "data_fim": date(2026, 10, 2),
        "detalhe_operacao": "09h00 às 18h00 (28/09 e 30/09); 02/10 só até 13h (4h de atendimento)",
    },
    {
        "local_trabalho": "Recife",
        "data_inicio": date(2026, 9, 29),
        "data_fim": date(2026, 9, 29),
        "detalhe_operacao": "09h00 às 16h00 (6h de atendimento)",
    },
    {
        "local_trabalho": "Curitiba",
        "data_inicio": date(2026, 11, 23),
        "data_fim": date(2026, 11, 23),
        "detalhe_operacao": "09h00 às 16h00 (6h de atendimento)",
    },
]


# Dias reais de atendimento por local — cada entrada é um dia clínico
# separado, com seu próprio horário (uma campanha pode ter dias não-
# contíguos, ex: Brasília pulou o dia 03/09). Horário de Brasília ajustado
# conforme confirmado com o usuário: 02/09 fechou às 18h, 04/09 só até 14h
# (não 18h como no detalhe_operacao inicial, escrito antes de confirmar).
CRONOGRAMA_DIAS_OFICIAL = {
    "Brasilia": [
        {"data": date(2026, 9, 2), "hora_inicio": "09:00", "hora_fim": "18:00"},
        {"data": date(2026, 9, 4), "hora_inicio": "09:00", "hora_fim": "14:00"},
    ],
    "Botafogo": [
        {"data": date(2026, 9, 25), "hora_inicio": "09:00", "hora_fim": "18:00"},
        {"data": date(2026, 10, 5), "hora_inicio": "09:00", "hora_fim": "18:00"},
    ],
    "Península": [
        {"data": date(2026, 9, 28), "hora_inicio": "09:00", "hora_fim": "18:00"},
        {"data": date(2026, 9, 30), "hora_inicio": "09:00", "hora_fim": "18:00"},
        {"data": date(2026, 10, 2), "hora_inicio": "09:00", "hora_fim": "13:00"},
    ],
    "Recife": [
        {"data": date(2026, 9, 29), "hora_inicio": "09:00", "hora_fim": "16:00"},
    ],
    "Curitiba": [
        {"data": date(2026, 11, 23), "hora_inicio": "09:00", "hora_fim": "16:00"},
    ],
}


def seed_dias_campanhas_oficiais(conn: Connection) -> int:
    """Pré-cadastra os dias de atendimento do cronograma oficial. Roda
    independente de `seed_campanhas_oficiais` — casa pelo local_trabalho, então
    funciona tanto pra campanha criada pelo seed quanto pra uma criada na mão
    (ex: o usuário já tinha criado a de Brasília manualmente antes do seed
    existir). Idempotente: pula qualquer campanha que já tenha dias
    cadastrados, nunca duplica."""
    criados = 0
    for local_trabalho, dias in CRONOGRAMA_DIAS_OFICIAL.items():
        campanha = conn.execute(
            "SELECT id FROM campanhas WHERE local_trabalho = ?", (local_trabalho,)
        ).fetchone()
        if not campanha:
            continue
        campanha_id = campanha["id"]
        ja_tem_dias = conn.execute(
            "SELECT 1 FROM campanha_dias WHERE campanha_id = ?", (campanha_id,)
        ).fetchone()
        if ja_tem_dias:
            continue
        for dia in dias:
            conn.execute(
                "INSERT INTO campanha_dias (campanha_id, data, hora_inicio, hora_fim) VALUES (?, ?, ?, ?)",
                (campanha_id, dia["data"].isoformat(), dia["hora_inicio"], dia["hora_fim"]),
            )
            criados += 1
    conn.commit()

    if criados:
        registrar_log("Dias de atendimento do cronograma oficial pré-cadastrados", f"dias_criados={criados}")
    return criados


def listar_dias_campanha(conn: Connection, campanha_id: int) -> list[dict]:
    """Cada dia de atendimento da campanha, com quantos compareceram naquele
    dia específico (via campanha_atendimentos.data_atendimento)."""
    rows = conn.execute(
        """
        SELECT cd.id, cd.data, cd.hora_inicio, cd.hora_fim,
               COUNT(ca.funcionario_id) AS total_atendidos
        FROM campanha_dias cd
        LEFT JOIN campanha_atendimentos ca
            ON ca.campanha_id = cd.campanha_id AND ca.data_atendimento = cd.data
        WHERE cd.campanha_id = ?
        GROUP BY cd.id
        ORDER BY cd.data
        """,
        (campanha_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def seed_campanhas_oficiais(conn: Connection) -> int:
    """Pré-cadastra o cronograma oficial confirmado. Idempotente e não
    destrutivo: pula qualquer local_trabalho que já tenha campanha criada
    (manual ou de um seed anterior) — nunca duplica nem mexe no que já existe."""
    criadas = 0
    for item in CRONOGRAMA_OFICIAL:
        ja_existe = conn.execute(
            "SELECT 1 FROM campanhas WHERE local_trabalho = ?", (item["local_trabalho"],)
        ).fetchone()
        if ja_existe:
            continue
        criar_campanha(
            conn,
            item["local_trabalho"],
            item["data_inicio"],
            item["data_fim"],
            kits_enviados=False,
            detalhe_operacao=item["detalhe_operacao"],
        )
        criadas += 1

    if criadas:
        registrar_log("Cronograma oficial pré-cadastrado", f"campanhas_criadas={criadas}")
    return criadas
