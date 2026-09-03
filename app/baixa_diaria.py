"""Motor da baixa diária + relatório de fim de dia (EOD).

Usado pelo módulo de Campanhas: cada dia de atendimento de uma campanha sobe
uma planilha de presença aqui dentro.

Fluxo:
1. A planilha do dia (quem fez o exame) passa pelo mesmo pipeline de matching
   do módulo 1 (ID -> CPF -> nome exato -> fuzzy -> exceção). Categorização
   usa exclusivamente 'local_trabalho' — nunca 'filial'.
2. Cada linha batida é interpretada pelo valor da coluna de data (ver
   `_situacao_da_linha`): uma data válida = fez o exame naquele dia (baixa
   aplicada); "Pendente" (ou variantes) = ainda não fez, não recebe baixa;
   nenhuma coluna de data presente = planilha de presença "pura" (só quem
   foi), assume que fez no dia do relatório. **Não basta a pessoa aparecer
   na planilha** — o texto da linha decide, nunca a simples presença.
3. Quem não bateu vai para a fila de exceções (mesma tabela do módulo 1) —
   nada é gravado na base mestre sem confirmação manual.
4. "Quem estava agendado e faltou" é calculado comparando os funcionários do
   local de trabalho com data_agendada = data do relatório que NÃO apareceram
   na planilha do dia -> marcados como status_fila = 'Faltou'.
5. Duplicatas dentro da própria planilha do dia (mesmo funcionário duas vezes)
   também entram como inconsistência.
6. Todo processamento é registrado no log de auditoria (ver logs.py).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from sqlite3 import Connection

import pandas as pd

from logs import registrar_log
from matching import cruzar_lista_rh
from planilhas import parse_data
from rules import status_aso

_TEXTOS_PENDENTE = {"pendente", "pendencia", "pendência", "nao fez", "não fez", "-"}


def _situacao_da_linha(linha: dict) -> tuple[str, date | None, str]:
    """Interpreta a coluna de data da linha do dia. Aceita tanto
    'data_realizacao' (planilha dedicada de presença) quanto 'data_ultimo_aso'
    (planilha da empresa, onde a coluna 'Data Aso' vem preenchida com a data
    real ou o texto 'Pendente' por pessoa).

    Retorna (situacao, data, texto_bruto) — situacao é:
    - "sem_info": nenhuma das duas colunas veio preenchida — planilha de
      presença pura (só quem foi), assume que fez no dia do relatório.
    - "fez": valor parseou como data válida.
    - "pendente": texto reconhecido como "ainda não fez" (ex: 'Pendente').
    - "invalido": tinha texto, mas não é data nem um marcador de pendente
      conhecido — vira inconsistência para revisão manual, não decide sozinho.
    """
    valor = linha.get("data_realizacao")
    if valor is None or (isinstance(valor, float) and pd.isna(valor)) or not str(valor).strip():
        valor = linha.get("data_ultimo_aso")

    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return "sem_info", None, ""

    texto = str(valor).strip()
    if not texto or texto.lower() == "nan":
        return "sem_info", None, ""

    if texto.lower() in _TEXTOS_PENDENTE:
        return "pendente", None, texto

    dt = parse_data(texto)
    if dt:
        return "fez", dt, texto

    return "invalido", None, texto


@dataclass
class ItemFeito:
    funcionario_id: str
    nome: str
    data_realizacao: str


@dataclass
class ItemAindaPendente:
    funcionario_id: str
    nome: str


@dataclass
class ItemFaltou:
    funcionario_id: str
    nome: str
    data_agendada: str


@dataclass
class ItemInconsistencia:
    motivo: str
    detalhe: str


@dataclass
class RelatorioEOD:
    local_trabalho: str | None
    data_relatorio: date
    fizeram: list[ItemFeito] = field(default_factory=list)
    ainda_pendentes: list[ItemAindaPendente] = field(default_factory=list)
    faltaram: list[ItemFaltou] = field(default_factory=list)
    inconsistencias: list[ItemInconsistencia] = field(default_factory=list)
    total_excecoes: int = 0


def processar_baixa_diaria(
    conn: Connection,
    linhas_dia: list[dict],
    data_relatorio: date,
    local_trabalho: str | None = None,
    ano_campanha: int | None = None,
    campanha_id: int | None = None,
) -> RelatorioEOD:
    ano_campanha = ano_campanha or data_relatorio.year
    relatorio = RelatorioEOD(local_trabalho=local_trabalho, data_relatorio=data_relatorio)

    resultados = cruzar_lista_rh(conn, linhas_dia, local_trabalho=local_trabalho)

    agora = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO importacoes_rh
            (filial, arquivo, data_importacao, total_linhas, total_match_automatico, total_excecoes, campanha_id)
        VALUES (?, 'baixa_diaria', ?, ?, ?, ?, ?)
        """,
        (
            local_trabalho,
            agora,
            len(resultados),
            sum(1 for r in resultados if r.camada != "excecao"),
            sum(1 for r in resultados if r.camada == "excecao"),
            campanha_id,
        ),
    )
    importacao_id = cur.lastrowid

    ids_processados_hoje: set[str] = set()

    for r in resultados:
        linha = r.linha_bruta
        nome_bruto = str(linha.get("nome") or "").strip()

        if r.camada == "excecao":
            candidatos_json = json.dumps([c.__dict__ for c in r.candidatos], ensure_ascii=False)
            conn.execute(
                """
                INSERT INTO excecoes_matching
                    (importacao_id, texto_bruto, candidatos_json, status, criado_em)
                VALUES (?, ?, ?, 'pendente', ?)
                """,
                (importacao_id, nome_bruto or json.dumps(linha, ensure_ascii=False), candidatos_json, agora),
            )
            relatorio.inconsistencias.append(
                ItemInconsistencia("Não encontrado na base mestre", nome_bruto or str(linha))
            )
            relatorio.total_excecoes += 1
            continue

        funcionario_id = r.funcionario_id

        if funcionario_id in ids_processados_hoje:
            relatorio.inconsistencias.append(
                ItemInconsistencia("Duplicado na planilha do dia", f"ID {funcionario_id} ({nome_bruto})")
            )
            continue
        ids_processados_hoje.add(funcionario_id)

        row_atual = conn.execute(
            "SELECT nome, data_ultimo_aso FROM funcionarios WHERE id = ?", (funcionario_id,)
        ).fetchone()
        nome_atual = row_atual["nome"] if row_atual else nome_bruto

        situacao, dt_da_linha, texto_bruto = _situacao_da_linha(linha)

        if situacao == "pendente":
            relatorio.ainda_pendentes.append(ItemAindaPendente(funcionario_id, nome_atual))
            continue

        if situacao == "invalido":
            relatorio.inconsistencias.append(
                ItemInconsistencia(
                    "Valor de data não reconhecido (nem data válida, nem 'Pendente')",
                    f"{nome_atual} (ID {funcionario_id}): '{texto_bruto}'",
                )
            )
            continue

        # "sem_info" (planilha de presença pura, sem coluna de data) usa a
        # data do relatório; "fez" usa a data que veio na própria linha.
        dt_realizacao = dt_da_linha or data_relatorio
        status = status_aso(dt_realizacao, ano_campanha)

        if row_atual and row_atual["data_ultimo_aso"] == dt_realizacao.isoformat():
            relatorio.inconsistencias.append(
                ItemInconsistencia(
                    "Já estava com baixa dessa mesma data (possível reenvio)",
                    f"{nome_atual} (ID {funcionario_id})",
                )
            )

        conn.execute(
            """
            UPDATE funcionarios
            SET data_ultimo_aso = ?, status_aso = ?, status_fila = 'Concluído'
            WHERE id = ?
            """,
            (dt_realizacao.isoformat(), status, funcionario_id),
        )
        relatorio.fizeram.append(ItemFeito(funcionario_id, nome_atual, dt_realizacao.isoformat()))

    # Quem estava agendado para essa data e não apareceu na planilha do dia
    query_agendados = "SELECT id, nome, data_agendada FROM funcionarios WHERE data_agendada = ?"
    params: tuple = (data_relatorio.isoformat(),)
    if local_trabalho:
        query_agendados += " AND local_trabalho = ?"
        params = (data_relatorio.isoformat(), local_trabalho)

    agendados = conn.execute(query_agendados, params).fetchall()
    for ag in agendados:
        if ag["id"] in ids_processados_hoje:
            continue
        conn.execute("UPDATE funcionarios SET status_fila = 'Faltou' WHERE id = ?", (ag["id"],))
        relatorio.faltaram.append(ItemFaltou(ag["id"], ag["nome"], ag["data_agendada"]))

    conn.commit()

    registrar_log(
        "Baixa diária processada",
        f"local_trabalho={local_trabalho or '(todas)'} data={data_relatorio.isoformat()} "
        f"campanha_id={campanha_id or '-'} fizeram={len(relatorio.fizeram)} "
        f"ainda_pendentes={len(relatorio.ainda_pendentes)} faltaram={len(relatorio.faltaram)} "
        f"inconsistencias={len(relatorio.inconsistencias)}",
    )

    return relatorio
