"""Servidor web (Flask) — frontend HTML próprio.

Reaproveita a lógica de negócio dos módulos: db.py, rules.py, matching.py,
resolvers.py, planilhas.py, baixa_diaria.py, pdf_pipeline.py, campanhas.py,
importacao_base.py, logs.py. Este arquivo só cuida de rotas HTTP e
renderização — nenhuma regra de negócio mora aqui.

Categorização de local usa exclusivamente a coluna 'local_trabalho' — nunca
'filial' (que é só dado cadastral/legal, guardado mas não usado em lógica).
"""
from __future__ import annotations

import io
import tempfile
from datetime import date, datetime
from pathlib import Path

import pandas as pd
from flask import Flask, flash, redirect, render_template, request, Response, url_for

import campanhas as campanhas_mod
import json
from baixa_diaria import processar_baixa_diaria
from db import get_connection, init_db
from matching import cruzar_lista_rh
from importacao_base import (
    CAMINHO_BASE_MESTRE_FIXA,
    PASTA_BACKUPS_BASE_MESTRA,
    base_mestre_fixa_existe,
    carregar_base_mestre_se_vazia,
    recarregar_base_mestre,
)
from logs import ler_logs, registrar_log
from pdf_pipeline import processar_lote_pdf, resolver_excecao_pdf
from planilhas import mapear_colunas, parse_data, validar_colunas_identificacao

app = Flask(__name__)
app.secret_key = "controle-periodicos-local"  # app local de uso único, sem exposição externa

init_db()
with get_connection() as _conn:
    carregar_base_mestre_se_vazia(_conn)
    campanhas_mod.seed_campanhas_oficiais(_conn)


@app.template_filter("from_json")
def from_json_filter(valor):
    return json.loads(valor) if valor else []


@app.template_filter("data_br")
def data_br_filter(valor):
    """Formata uma data (ISO ou já um date/datetime) para o padrão brasileiro DD/MM/AAAA."""
    if not valor:
        return "—"
    d = parse_data(valor)
    return d.strftime("%d/%m/%Y") if d else valor


@app.template_filter("datahora_br")
def datahora_br_filter(valor):
    """Formata um timestamp ISO (ex: dos logs) para DD/MM/AAAA HH:MM:SS."""
    if not valor:
        return "—"
    try:
        dt = datetime.fromisoformat(str(valor))
        return dt.strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return valor


@app.context_processor
def injetar_contadores():
    conn = get_connection()
    contagem_excecoes = conn.execute(
        "SELECT COUNT(*) AS n FROM excecoes_matching WHERE status = 'pendente'"
    ).fetchone()["n"]
    contagem_pdfs_pendentes = conn.execute(
        "SELECT COUNT(*) AS n FROM excecoes_pdf WHERE status = 'pendente'"
    ).fetchone()["n"]
    conn.close()
    return dict(contagem_excecoes=contagem_excecoes, contagem_pdfs_pendentes=contagem_pdfs_pendentes)


# ---------------------------------------------------------------------------
# Dashboard (home)
# ---------------------------------------------------------------------------
@app.route("/", methods=["GET"])
def index():
    return redirect(url_for("dashboard"))


@app.route("/dashboard", methods=["GET"])
def dashboard():
    conn = get_connection()
    totais = conn.execute(
        """
        SELECT COUNT(*) AS total,
               SUM(CASE WHEN status_aso = 'Dispensado' THEN 1 ELSE 0 END) AS dispensados,
               SUM(CASE WHEN status_aso != 'Dispensado' THEN 1 ELSE 0 END) AS precisam_exame
        FROM funcionarios
        """
    ).fetchone()
    progresso_local = conn.execute(
        """
        SELECT local_trabalho,
               COUNT(*) AS total,
               SUM(CASE WHEN status_aso = 'Dispensado' THEN 1 ELSE 0 END) AS dispensados
        FROM funcionarios
        GROUP BY local_trabalho
        ORDER BY local_trabalho
        """
    ).fetchall()
    conn.close()

    progresso = [
        {
            "local_trabalho": r["local_trabalho"] or "(sem local)",
            "total": r["total"],
            "dispensados": r["dispensados"],
            "percentual": round((r["dispensados"] or 0) / r["total"] * 100, 1) if r["total"] else 0,
        }
        for r in progresso_local
    ]

    backups = []
    if PASTA_BACKUPS_BASE_MESTRA.exists():
        arquivos = sorted(PASTA_BACKUPS_BASE_MESTRA.glob("*.xlsx"), key=lambda p: p.stat().st_mtime, reverse=True)
        backups = [{"nome": p.name, "tamanho_kb": round(p.stat().st_size / 1024)} for p in arquivos[:15]]

    return render_template(
        "dashboard.html",
        active="dashboard",
        base_existe=base_mestre_fixa_existe(),
        caminho_base=str(CAMINHO_BASE_MESTRE_FIXA),
        totais=totais,
        progresso=progresso,
        backups=backups,
    )


@app.route("/dashboard/recarregar", methods=["POST"])
def dashboard_recarregar():
    conn = get_connection()
    try:
        resultado = recarregar_base_mestre(conn)
        flash(
            f"Base recarregada: {resultado['novos']} novo(s), {resultado['atualizados']} atualizado(s). "
            f"Backup salvo: {resultado['backup']}",
            "success",
        )
    except FileNotFoundError as e:
        flash(str(e), "danger")
    finally:
        conn.close()
    return redirect(url_for("dashboard"))


# ---------------------------------------------------------------------------
# Consulta geral (tabela dinâmica, substitui a Busca por ID)
# ---------------------------------------------------------------------------
@app.route("/consulta", methods=["GET"])
def consulta():
    conn = get_connection()
    funcionarios = conn.execute(
        """
        SELECT id, nome, local_trabalho, funcao, data_ultimo_aso, status_aso, status_fila
        FROM funcionarios ORDER BY nome
        """
    ).fetchall()
    locais = conn.execute(
        "SELECT DISTINCT local_trabalho FROM funcionarios WHERE local_trabalho IS NOT NULL ORDER BY local_trabalho"
    ).fetchall()
    conn.close()
    return render_template(
        "consulta.html",
        active="consulta",
        funcionarios=funcionarios,
        locais=[l["local_trabalho"] for l in locais],
    )


@app.route("/consulta/exportar", methods=["GET"])
def consulta_exportar():
    conn = get_connection()
    df = pd.read_sql_query("SELECT * FROM funcionarios ORDER BY nome", conn)
    conn.close()

    for coluna in ("data_admissao", "data_ultimo_aso", "data_agendada"):
        if coluna in df.columns:
            df[coluna] = df[coluna].map(lambda v: data_br_filter(v) if v else "")

    buffer = io.BytesIO()
    df.to_excel(buffer, index=False)
    buffer.seek(0)
    return Response(
        buffer.read(),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename=base_atualizada_{date.today().isoformat()}.xlsx"},
    )


# ---------------------------------------------------------------------------
# Campanhas
# ---------------------------------------------------------------------------
@app.route("/campanhas", methods=["GET", "POST"])
def campanhas():
    if request.method == "POST":
        local_trabalho = request.form.get("local_trabalho", "").strip()
        data_inicio = parse_data(request.form.get("data_inicio"))
        data_fim = parse_data(request.form.get("data_fim"))
        kits_enviados = bool(request.form.get("kits_enviados"))
        detalhe_operacao = request.form.get("detalhe_operacao", "").strip() or None

        if not local_trabalho or not data_inicio or not data_fim:
            flash("Preencha local de trabalho e o período completo.", "danger")
            return redirect(url_for("campanhas"))

        conn = get_connection()
        campanha_id = campanhas_mod.criar_campanha(
            conn, local_trabalho, data_inicio, data_fim, kits_enviados, detalhe_operacao
        )
        conn.close()
        flash("Campanha criada.", "success")
        return redirect(url_for("campanha_detalhe", campanha_id=campanha_id))

    conn = get_connection()
    lista = campanhas_mod.listar_campanhas(conn)
    locais = conn.execute(
        "SELECT DISTINCT local_trabalho FROM funcionarios WHERE local_trabalho IS NOT NULL ORDER BY local_trabalho"
    ).fetchall()
    conn.close()
    return render_template(
        "campanhas.html", active="campanhas", campanhas=lista, locais=[l["local_trabalho"] for l in locais]
    )


@app.route("/campanhas/<int:campanha_id>", methods=["GET"])
def campanha_detalhe(campanha_id):
    conn = get_connection()
    campanha = campanhas_mod.obter_campanha(conn, campanha_id)
    if campanha is None:
        conn.close()
        flash("Campanha não encontrada.", "danger")
        return redirect(url_for("campanhas"))
    pendentes = campanhas_mod.listar_membros_pendentes(conn, campanha_id)
    concluidos = campanhas_mod.listar_membros_concluidos(conn, campanha_id)
    convocados, ja_dispensados = campanhas_mod.obter_resultado_lista_rh(conn, campanha_id)
    conn.close()
    return render_template(
        "campanha_detalhe.html",
        active="campanhas",
        campanha=campanha,
        pendentes=pendentes,
        concluidos=concluidos,
        convocados=convocados,
        ja_dispensados=ja_dispensados,
        hoje=date.today().isoformat(),
        relatorio=None,
    )


@app.route("/campanhas/<int:campanha_id>/importar-rh", methods=["POST"])
def campanha_importar_rh(campanha_id):
    """1º e ÚNICO upload da campanha: a lista do local de trabalho que o RH
    manda. Cruza contra a base mestre e barra quem já está 'Dispensado' — só
    quem está com o ASO vencido vira 'Convocado' e conta pra meta da campanha
    (denominador do progresso). Quem não bateu vai pra fila de exceções, como
    sempre. Trava dupla (backend + esconder o form no template): uma vez
    processada, a lista não pode ser reenviada para a mesma campanha."""
    from datetime import datetime

    conn = get_connection()
    campanha = campanhas_mod.obter_campanha(conn, campanha_id)
    if campanha is None:
        conn.close()
        flash("Campanha não encontrada.", "danger")
        return redirect(url_for("campanhas"))

    if campanhas_mod.campanha_ja_processou_lista_rh(conn, campanha_id):
        conn.close()
        flash("A lista do RH desta campanha já foi processada e não pode ser reenviada.", "warning")
        return redirect(url_for("campanha_detalhe", campanha_id=campanha_id))

    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        conn.close()
        flash("Selecione um arquivo Excel.", "danger")
        return redirect(url_for("campanha_detalhe", campanha_id=campanha_id))

    df_rh = mapear_colunas(pd.read_excel(arquivo, dtype=str))
    try:
        validar_colunas_identificacao(df_rh)
    except ValueError as e:
        conn.close()
        flash(str(e), "danger")
        return redirect(url_for("campanha_detalhe", campanha_id=campanha_id))

    linhas = df_rh.to_dict(orient="records")
    resultados = cruzar_lista_rh(conn, linhas, local_trabalho=campanha.local_trabalho)

    convocados = []
    ja_dispensados = []
    for r in resultados:
        if r.camada == "excecao":
            continue
        funcionario = conn.execute(
            "SELECT nome, status_aso FROM funcionarios WHERE id = ?", (r.funcionario_id,)
        ).fetchone()
        item = {"funcionario_id": r.funcionario_id, "nome": funcionario["nome"]}
        if funcionario["status_aso"] == "Dispensado":
            ja_dispensados.append(item)
        else:
            convocados.append(item)

    total_excecoes = sum(1 for r in resultados if r.camada == "excecao")

    agora = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        """
        INSERT INTO importacoes_rh
            (filial, arquivo, data_importacao, total_linhas, total_match_automatico, total_excecoes, campanha_id)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            campanha.local_trabalho, arquivo.filename, agora, len(resultados),
            len(convocados) + len(ja_dispensados), total_excecoes, campanha_id,
        ),
    )
    importacao_id = cur.lastrowid

    for r in resultados:
        if r.camada == "excecao":
            nome_bruto = str(r.linha_bruta.get("nome", "")).strip()
            candidatos_json = json.dumps([c.__dict__ for c in r.candidatos], ensure_ascii=False)
            conn.execute(
                """
                INSERT INTO excecoes_matching (importacao_id, texto_bruto, candidatos_json, status, criado_em)
                VALUES (?, ?, ?, 'pendente', ?)
                """,
                (importacao_id, nome_bruto or json.dumps(r.linha_bruta, ensure_ascii=False), candidatos_json, agora),
            )
    conn.commit()

    campanhas_mod.registrar_resultado_lista_rh(conn, campanha_id, arquivo.filename, convocados, ja_dispensados)
    conn.close()

    flash(
        f"Lista do RH processada: {len(convocados)} convocado(s) (ASO vencido), "
        f"{len(ja_dispensados)} já dispensado(s) (barrado(s) da meta), "
        f"{total_excecoes} foram para a fila de exceções.",
        "success",
    )
    return redirect(url_for("campanha_detalhe", campanha_id=campanha_id))


@app.route("/campanhas/<int:campanha_id>/processar-dia", methods=["POST"])
def campanha_processar_dia(campanha_id):
    conn = get_connection()
    campanha = campanhas_mod.obter_campanha(conn, campanha_id)
    if campanha is None:
        conn.close()
        flash("Campanha não encontrada.", "danger")
        return redirect(url_for("campanhas"))

    data_relatorio = parse_data(request.form.get("data_relatorio")) or date.today()
    arquivo = request.files.get("arquivo")
    if not arquivo or not arquivo.filename:
        conn.close()
        flash("Selecione um arquivo Excel.", "danger")
        return redirect(url_for("campanha_detalhe", campanha_id=campanha_id))

    df_dia = mapear_colunas(pd.read_excel(arquivo, dtype=str))
    try:
        validar_colunas_identificacao(df_dia)
    except ValueError as e:
        conn.close()
        flash(str(e), "danger")
        return redirect(url_for("campanha_detalhe", campanha_id=campanha_id))

    rel = processar_baixa_diaria(
        conn,
        df_dia.to_dict(orient="records"),
        data_relatorio,
        local_trabalho=campanha.local_trabalho,
        campanha_id=campanha_id,
    )

    campanha_atualizada = campanhas_mod.obter_campanha(conn, campanha_id)
    pendentes = campanhas_mod.listar_membros_pendentes(conn, campanha_id)
    concluidos = campanhas_mod.listar_membros_concluidos(conn, campanha_id)
    convocados, ja_dispensados = campanhas_mod.obter_resultado_lista_rh(conn, campanha_id)
    conn.close()

    relatorio = {
        "data_relatorio": rel.data_relatorio.isoformat(),
        "fizeram": [f.__dict__ for f in rel.fizeram],
        "ainda_pendentes": [p.__dict__ for p in rel.ainda_pendentes],
        "faltaram": [f.__dict__ for f in rel.faltaram],
        "inconsistencias": [i.__dict__ for i in rel.inconsistencias],
    }
    flash(
        f"Dia processado: {len(rel.fizeram)} concluído(s), {len(rel.ainda_pendentes)} ainda pendente(s), "
        f"{len(rel.inconsistencias)} inconsistência(s).",
        "success",
    )

    return render_template(
        "campanha_detalhe.html",
        active="campanhas",
        campanha=campanha_atualizada,
        pendentes=pendentes,
        concluidos=concluidos,
        convocados=convocados,
        ja_dispensados=ja_dispensados,
        hoje=date.today().isoformat(),
        relatorio=relatorio,
    )


# ---------------------------------------------------------------------------
# Fila de exceções
# ---------------------------------------------------------------------------
@app.route("/excecoes", methods=["GET"])
def excecoes():
    conn = get_connection()
    pendentes = conn.execute(
        "SELECT * FROM excecoes_matching WHERE status = 'pendente' ORDER BY criado_em"
    ).fetchall()
    conn.close()
    return render_template("excecoes.html", active="excecoes", pendentes=pendentes)


@app.route("/excecoes/resolver/<int:excecao_id>", methods=["POST"])
def excecoes_resolver(excecao_id):
    from datetime import datetime

    funcionario_id = request.form.get("funcionario_id") or None
    conn = get_connection()
    conn.execute(
        """
        UPDATE excecoes_matching
        SET status = 'resolvido', funcionario_id_resolvido = ?, origem_resolucao = 'manual',
            confirmado_por = ?, resolvido_em = ?
        WHERE id = ?
        """,
        (funcionario_id, "usuario_local", datetime.now().isoformat(timespec="seconds"), excecao_id),
    )
    conn.commit()
    conn.close()
    flash("Exceção resolvida.", "success")
    return redirect(url_for("excecoes"))


@app.route("/excecoes/lote", methods=["POST"])
def excecoes_lote():
    from datetime import datetime

    acao = request.form.get("acao")
    ids_selecionados = request.form.getlist("selecionados")
    if not ids_selecionados:
        flash("Selecione ao menos uma exceção.", "warning")
        return redirect(url_for("excecoes"))

    agora = datetime.now().isoformat(timespec="seconds")
    conn = get_connection()

    if acao == "excluir":
        conn.executemany(
            """
            UPDATE excecoes_matching
            SET status = 'excluido', origem_resolucao = 'manual_lote', confirmado_por = ?, resolvido_em = ?
            WHERE id = ?
            """,
            [("usuario_local", agora, eid) for eid in ids_selecionados],
        )
        conn.commit()
        registrar_log("Exceções excluídas em lote", f"quantidade={len(ids_selecionados)} ids={ids_selecionados}")
        flash(f"{len(ids_selecionados)} exceção(ões) excluída(s) da fila.", "success")

    elif acao == "aprovar":
        # Score mínimo pra aprovar em lote sem revisão individual — deliberadamente
        # mais alto que qualquer sugestão "fraca": o rapidfuzz sempre devolve os
        # top-3 candidatos, mesmo quando nenhum é realmente parecido (ex: score 39
        # pra um nome completamente diferente). Abaixo disso, fica pendente pra
        # revisão manual individual em vez de arriscar vincular a pessoa errada.
        LIMITE_APROVACAO_LOTE = 85
        aprovadas = 0
        sem_candidato_confiavel = 0
        for eid in ids_selecionados:
            row = conn.execute("SELECT candidatos_json FROM excecoes_matching WHERE id = ?", (eid,)).fetchone()
            candidatos = json.loads(row["candidatos_json"]) if row and row["candidatos_json"] else []
            melhor = max(candidatos, key=lambda c: c["score"]) if candidatos else None
            if not melhor or melhor["score"] < LIMITE_APROVACAO_LOTE:
                sem_candidato_confiavel += 1
                continue
            conn.execute(
                """
                UPDATE excecoes_matching
                SET status = 'resolvido', funcionario_id_resolvido = ?, origem_resolucao = 'manual_lote',
                    confirmado_por = ?, resolvido_em = ?
                WHERE id = ?
                """,
                (melhor["funcionario_id"], "usuario_local", agora, eid),
            )
            aprovadas += 1
        conn.commit()
        registrar_log(
            "Exceções aprovadas em lote",
            f"aprovadas={aprovadas} sem_candidato_confiavel={sem_candidato_confiavel} limite_score={LIMITE_APROVACAO_LOTE}",
        )
        msg = f"{aprovadas} exceção(ões) aprovada(s) com o melhor candidato sugerido (score ≥ {LIMITE_APROVACAO_LOTE})."
        if sem_candidato_confiavel:
            msg += f" {sem_candidato_confiavel} não tinham candidato confiável e continuam pendentes — revise individualmente."
        flash(msg, "success")

    conn.close()
    return redirect(url_for("excecoes"))


@app.route("/excecoes/limpar-tudo", methods=["POST"])
def excecoes_limpar_tudo():
    from datetime import datetime

    conn = get_connection()
    total = conn.execute("SELECT COUNT(*) AS n FROM excecoes_matching WHERE status = 'pendente'").fetchone()["n"]
    conn.execute(
        """
        UPDATE excecoes_matching
        SET status = 'excluido', origem_resolucao = 'manual_lote', confirmado_por = ?, resolvido_em = ?
        WHERE status = 'pendente'
        """,
        ("usuario_local", datetime.now().isoformat(timespec="seconds")),
    )
    conn.commit()
    conn.close()
    registrar_log("Fila de exceções limpa por completo", f"removidas={total}")
    flash(f"Fila de exceções limpa ({total} removida(s)).", "success")
    return redirect(url_for("excecoes"))


# ---------------------------------------------------------------------------
# Separar PDFs
# ---------------------------------------------------------------------------
@app.route("/separar-pdfs", methods=["GET", "POST"])
def separar_pdfs():
    relatorio = None
    if request.method == "POST":
        local_trabalho = request.form.get("local_trabalho", "").strip() or None
        arquivo = request.files.get("arquivo")
        if not arquivo or not arquivo.filename:
            flash("Selecione um arquivo PDF.", "danger")
            return redirect(url_for("separar_pdfs"))

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
            arquivo.save(tmp.name)
            caminho_tmp = tmp.name

        conn = get_connection()
        rel = processar_lote_pdf(conn, caminho_tmp, nome_arquivo_origem=arquivo.filename, local_trabalho=local_trabalho)
        conn.close()
        Path(caminho_tmp).unlink(missing_ok=True)

        relatorio = {
            "separados": [
                {"funcionario_id": s.funcionario_id, "nome": s.nome, "arquivo": s.arquivo, "paginas": s.paginas}
                for s in rel.separados
            ],
            "pendentes": [p.__dict__ for p in rel.pendentes],
        }
        flash(f"{len(rel.separados)} PDF(s) separados, {len(rel.pendentes)} pendente(s) de revisão.", "success")

    return render_template("separar_pdfs.html", active="separar_pdfs", relatorio=relatorio)


# ---------------------------------------------------------------------------
# PDFs pendentes
# ---------------------------------------------------------------------------
@app.route("/pdfs-pendentes", methods=["GET"])
def pdfs_pendentes():
    conn = get_connection()
    pendentes = conn.execute(
        "SELECT * FROM excecoes_pdf WHERE status = 'pendente' ORDER BY criado_em"
    ).fetchall()
    conn.close()
    return render_template("pdfs_pendentes.html", active="pdfs_pendentes", pendentes=pendentes)


@app.route("/pdfs-pendentes/resolver/<int:excecao_id>", methods=["POST"])
def pdfs_pendentes_resolver(excecao_id):
    funcionario_id = (request.form.get("funcionario_id_manual") or "").strip() or request.form.get("funcionario_id")
    if not funcionario_id:
        flash("Informe o ID manualmente ou selecione um candidato.", "danger")
        return redirect(url_for("pdfs_pendentes"))

    conn = get_connection()
    try:
        caminho_final = resolver_excecao_pdf(conn, excecao_id, funcionario_id)
        flash(f"PDF organizado em: {caminho_final}", "success")
    except ValueError as e:
        flash(str(e), "danger")
    finally:
        conn.close()
    return redirect(url_for("pdfs_pendentes"))


# ---------------------------------------------------------------------------
# Histórico / Logs
# ---------------------------------------------------------------------------
@app.route("/logs", methods=["GET"])
def logs():
    return render_template("logs.html", active="logs", eventos=ler_logs())


if __name__ == "__main__":
    app.run(debug=False, port=8501)
