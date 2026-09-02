"""Pipeline de matching: cruza uma lista de RH contra a base mestre.

Camadas em ordem de confiança, parando na primeira que resolver:
1. ID exato (chave da planilha mestra)
2. CPF exato
3. Nome normalizado exato
4. Nome fuzzy (rapidfuzz, threshold configurável)
5. Sem match confiável -> fila de exceções (nunca decide sozinho)
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from sqlite3 import Connection

from rapidfuzz import fuzz, process

from resolvers import Candidato

FUZZY_THRESHOLD = 90
FUZZY_TOP_N = 3


def normalizar_nome(nome: str) -> str:
    nome = nome.strip().upper()
    nome = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    nome = re.sub(r"\s+", " ", nome)
    return nome


@dataclass
class ResultadoLinha:
    linha_bruta: dict
    camada: str  # "id" | "cpf" | "nome_exato" | "fuzzy" | "excecao"
    funcionario_id: str | None
    candidatos: list[Candidato] = field(default_factory=list)


def _carregar_base_mestre(conn: Connection, local_trabalho: str | None = None) -> list[dict]:
    if local_trabalho:
        cur = conn.execute(
            "SELECT id, nome, nome_normalizado, cpf FROM funcionarios WHERE local_trabalho = ?",
            (local_trabalho,),
        )
    else:
        cur = conn.execute("SELECT id, nome, nome_normalizado, cpf FROM funcionarios")
    return [dict(row) for row in cur.fetchall()]


def cruzar_lista_rh(
    conn: Connection, linhas_rh: list[dict], local_trabalho: str | None = None
) -> list[ResultadoLinha]:
    """linhas_rh: cada dict pode conter chaves 'id', 'cpf', 'nome' (o que a lista trouxe).

    Se `local_trabalho` for informado, o cruzamento por nome (exato e fuzzy) fica
    restrito aos funcionários dessa unidade, evitando falso-positivo entre unidades
    diferentes. Match por ID e CPF continua exato/global, pois são chaves inequívocas.
    Categorização usa exclusivamente 'local_trabalho' — nunca 'filial'.
    """
    base_global = _carregar_base_mestre(conn)
    base = _carregar_base_mestre(conn, local_trabalho) if local_trabalho else base_global
    por_id_global = {f["id"]: f for f in base_global if f["id"]}
    por_cpf_global = {f["cpf"]: f for f in base_global if f["cpf"]}
    por_nome_normalizado = {f["nome_normalizado"]: f for f in base}
    nomes_normalizados = list(por_nome_normalizado.keys())

    resultados: list[ResultadoLinha] = []

    for linha in linhas_rh:
        id_informado = str(linha.get("id") or "").strip()
        cpf_informado = str(linha.get("cpf") or "").strip()
        nome_informado = str(linha.get("nome") or "").strip()
        nome_norm = normalizar_nome(nome_informado) if nome_informado else ""

        if id_informado and id_informado in por_id_global:
            resultados.append(ResultadoLinha(linha, "id", por_id_global[id_informado]["id"]))
            continue

        if cpf_informado and cpf_informado in por_cpf_global:
            resultados.append(ResultadoLinha(linha, "cpf", por_cpf_global[cpf_informado]["id"]))
            continue

        if nome_norm and nome_norm in por_nome_normalizado:
            resultados.append(ResultadoLinha(linha, "nome_exato", por_nome_normalizado[nome_norm]["id"]))
            continue

        if nome_norm and nomes_normalizados:
            candidatos_fuzzy = process.extract(
                nome_norm, nomes_normalizados, scorer=fuzz.WRatio, limit=FUZZY_TOP_N
            )
            melhor_nome, melhor_score, _ = candidatos_fuzzy[0] if candidatos_fuzzy else (None, 0, None)

            if melhor_score >= FUZZY_THRESHOLD:
                resultados.append(
                    ResultadoLinha(linha, "fuzzy", por_nome_normalizado[melhor_nome]["id"])
                )
                continue

            candidatos = [
                Candidato(
                    funcionario_id=por_nome_normalizado[nome_cand]["id"],
                    nome=por_nome_normalizado[nome_cand]["nome"],
                    score=score,
                )
                for nome_cand, score, _ in candidatos_fuzzy
            ]
            resultados.append(ResultadoLinha(linha, "excecao", None, candidatos))
            continue

        resultados.append(ResultadoLinha(linha, "excecao", None, []))

    return resultados
