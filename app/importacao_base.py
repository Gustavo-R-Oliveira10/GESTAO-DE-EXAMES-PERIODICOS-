"""Importação da base mestre a partir do arquivo Excel fixo do projeto
(campanha 2026). Não é mais feita por upload na interface.

Duas operações:
- `carregar_base_mestre_se_vazia`: roda automaticamente na inicialização do
  servidor. Só importa se a tabela `funcionarios` estiver vazia (primeiro
  uso) — evita sobrescrever o progresso de campanhas já processadas toda vez
  que o servidor reinicia.
- `recarregar_base_mestre`: ação manual (botão no Dashboard) para quando o RH
  atualiza o arquivo fixo (novas admissões, mudança de função/local etc.).
  Atualiza os campos cadastrais normalmente, mas nunca regride
  `data_ultimo_aso`/`status_aso` de quem já foi processado numa campanha —
  fica sempre a data mais recente entre a already-no-banco e a do arquivo.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from logs import registrar_log
from matching import normalizar_nome
from planilhas import mapear_colunas, parse_data
from rules import status_aso

CAMINHO_BASE_MESTRE_FIXA = Path(__file__).parent / "data" / "base_mestra_2026.xlsx"


def base_mestre_fixa_existe() -> bool:
    return CAMINHO_BASE_MESTRE_FIXA.exists()


def _linha_para_campos(row, mapa_local_trabalho: dict[str, str]) -> dict | None:
    fid = str(row.get("id", "")).strip()
    nome = str(row.get("nome", "")).strip()
    if not fid or not nome or fid.lower() == "nan":
        return None

    local_trabalho = str(row.get("local_trabalho", "")).strip() or None
    if local_trabalho:
        # Reconcilia variações de capitalização do mesmo local (ex: "CURITIBA"
        # vs "Curitiba") contra o que já existe na base, pra não fragmentar
        # dashboard/campanhas em grupos "iguais" só por causa de maiúsculas.
        chave = local_trabalho.upper()
        if chave in mapa_local_trabalho:
            local_trabalho = mapa_local_trabalho[chave]
        else:
            mapa_local_trabalho[chave] = local_trabalho

    return {
        "id": fid,
        "nome": nome,
        "cpf": str(row.get("cpf", "")).strip() or None,
        "empresa": str(row.get("empresa", "")).strip() or None,
        "filial": str(row.get("filial", "")).strip() or None,
        "ghe_area": str(row.get("ghe_area", "")).strip() or None,
        "local_trabalho": local_trabalho,
        "funcao": str(row.get("funcao", "")).strip() or None,
        "data_admissao": parse_data(row.get("data_admissao")),
        "tipo_aso": str(row.get("tipo_aso", "")).strip() or None,
        "data_ultimo_aso": parse_data(row.get("data_ultimo_aso")),
    }


def _mapa_local_trabalho_existente(conn) -> dict[str, str]:
    """Constrói {LOCAL_MAIUSCULO: 'Capitalização já usada na base'} pra reconciliar
    novas linhas contra a grafia já estabelecida em vez de criar uma variante nova."""
    rows = conn.execute(
        "SELECT DISTINCT local_trabalho FROM funcionarios WHERE local_trabalho IS NOT NULL"
    ).fetchall()
    return {r["local_trabalho"].upper(): r["local_trabalho"] for r in rows}


def _ler_planilha_mestra(caminho_arquivo: Path) -> pd.DataFrame:
    df = mapear_colunas(pd.read_excel(caminho_arquivo, dtype=str))
    faltando = [c for c in ("id", "nome", "data_ultimo_aso") if c not in df.columns]
    if faltando:
        raise ValueError(f"Colunas obrigatórias não encontradas na planilha mestra: {faltando}")
    return df


def carregar_base_mestre_se_vazia(conn, ano_campanha: int | None = None) -> int | None:
    total_atual = conn.execute("SELECT COUNT(*) AS n FROM funcionarios").fetchone()["n"]
    if total_atual > 0:
        return None
    if not base_mestre_fixa_existe():
        return None

    ano_campanha = ano_campanha or date.today().year
    df = _ler_planilha_mestra(CAMINHO_BASE_MESTRE_FIXA)
    mapa_local_trabalho: dict[str, str] = {}

    inseridos = 0
    for _, row in df.iterrows():
        campos = _linha_para_campos(row, mapa_local_trabalho)
        if not campos:
            continue
        dt = campos["data_ultimo_aso"]
        status = status_aso(dt, ano_campanha)
        conn.execute(
            """
            INSERT INTO funcionarios
                (id, nome, nome_normalizado, cpf, empresa, filial, ghe_area,
                 local_trabalho, funcao, data_admissao, tipo_aso, data_ultimo_aso, status_aso)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                campos["id"], campos["nome"], normalizar_nome(campos["nome"]), campos["cpf"],
                campos["empresa"], campos["filial"], campos["ghe_area"], campos["local_trabalho"],
                campos["funcao"], campos["data_admissao"].isoformat() if campos["data_admissao"] else None,
                campos["tipo_aso"], dt.isoformat() if dt else None, status,
            ),
        )
        inseridos += 1
    conn.commit()

    registrar_log(
        "Base mestre carregada do arquivo fixo (inicialização)",
        f"arquivo={CAMINHO_BASE_MESTRE_FIXA.name} inseridos={inseridos} ano_campanha={ano_campanha}",
    )
    return inseridos


def recarregar_base_mestre(conn, ano_campanha: int | None = None) -> dict:
    if not base_mestre_fixa_existe():
        raise FileNotFoundError(
            f"Base mestre fixa não encontrada em {CAMINHO_BASE_MESTRE_FIXA}. "
            "Coloque o arquivo Excel da campanha 2026 nesse caminho."
        )

    ano_campanha = ano_campanha or date.today().year
    df = _ler_planilha_mestra(CAMINHO_BASE_MESTRE_FIXA)
    mapa_local_trabalho = _mapa_local_trabalho_existente(conn)

    novos = 0
    atualizados = 0
    for _, row in df.iterrows():
        campos = _linha_para_campos(row, mapa_local_trabalho)
        if not campos:
            continue

        existente = conn.execute(
            "SELECT data_ultimo_aso FROM funcionarios WHERE id = ?", (campos["id"],)
        ).fetchone()

        dt_arquivo = campos["data_ultimo_aso"]
        if existente and existente["data_ultimo_aso"]:
            dt_existente = parse_data(existente["data_ultimo_aso"])
            # nunca regride: fica sempre a data mais recente entre banco e arquivo,
            # pra não apagar uma baixa já processada numa campanha em andamento.
            dt_final = max(filter(None, [dt_existente, dt_arquivo])) if (dt_existente or dt_arquivo) else None
        else:
            dt_final = dt_arquivo

        status = status_aso(dt_final, ano_campanha)

        if existente:
            conn.execute(
                """
                UPDATE funcionarios SET
                    nome = ?, nome_normalizado = ?, cpf = ?, empresa = ?, filial = ?, ghe_area = ?,
                    local_trabalho = ?, funcao = ?, data_admissao = ?, tipo_aso = ?,
                    data_ultimo_aso = ?, status_aso = ?
                WHERE id = ?
                """,
                (
                    campos["nome"], normalizar_nome(campos["nome"]), campos["cpf"], campos["empresa"],
                    campos["filial"], campos["ghe_area"], campos["local_trabalho"], campos["funcao"],
                    campos["data_admissao"].isoformat() if campos["data_admissao"] else None,
                    campos["tipo_aso"], dt_final.isoformat() if dt_final else None, status, campos["id"],
                ),
            )
            atualizados += 1
        else:
            conn.execute(
                """
                INSERT INTO funcionarios
                    (id, nome, nome_normalizado, cpf, empresa, filial, ghe_area,
                     local_trabalho, funcao, data_admissao, tipo_aso, data_ultimo_aso, status_aso)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    campos["id"], campos["nome"], normalizar_nome(campos["nome"]), campos["cpf"],
                    campos["empresa"], campos["filial"], campos["ghe_area"], campos["local_trabalho"],
                    campos["funcao"], campos["data_admissao"].isoformat() if campos["data_admissao"] else None,
                    campos["tipo_aso"], dt_final.isoformat() if dt_final else None, status,
                ),
            )
            novos += 1
    conn.commit()

    registrar_log(
        "Base mestre recarregada manualmente do arquivo fixo",
        f"arquivo={CAMINHO_BASE_MESTRE_FIXA.name} novos={novos} atualizados={atualizados}",
    )
    return {"novos": novos, "atualizados": atualizados}
