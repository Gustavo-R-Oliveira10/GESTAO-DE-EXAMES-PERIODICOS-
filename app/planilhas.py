"""Utilitários compartilhados para ler planilhas Excel: parsing de datas e
mapeamento das colunas reais da empresa para os nomes internos usados no banco."""
from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

import pandas as pd


_RE_DATA_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_data(valor) -> date | None:
    if valor is None or (isinstance(valor, float) and pd.isna(valor)):
        return None
    if isinstance(valor, (pd.Timestamp, datetime)):
        return valor.date()
    if isinstance(valor, date):
        return valor
    texto = str(valor).strip()
    if not texto or texto.lower() == "nan":
        return None
    if _RE_DATA_ISO.match(texto):
        # já está em ISO (YYYY-MM-DD) — normalmente uma data que o próprio
        # sistema gravou antes. Não usar dayfirst aqui: com dayfirst=True o
        # pandas pode reinterpretar ISO como YYYY-DD-MM quando o "dia" é <=12
        # (ex: "2026-09-02" virava 09/02 = fevereiro em vez de setembro).
        try:
            return date.fromisoformat(texto)
        except ValueError:
            return None
    if texto.replace(".", "", 1).isdigit():
        # serial de data do Excel (ex: 45976), caso a coluna não venha formatada
        try:
            return (pd.Timestamp("1899-12-30") + pd.to_timedelta(float(texto), unit="D")).date()
        except Exception:
            return None
    try:
        return pd.to_datetime(texto, dayfirst=True).date()
    except Exception:
        return None


# Aceita as colunas reais da planilha mestra da empresa (Matricula, Nome, Empresa,
# Filial, GHE/Area, Local de Trabalho, Funcao, Data de Admissao, Tipo de Aso, Data Aso)
# e também as colunas típicas de uma planilha de baixa diária (data de realização,
# observações livres do RH), com variações de acentuação/maiúsculas.
# "filial" (razão social/legal) e "local_trabalho" (unidade operacional real)
# são mantidas como colunas separadas — toda categorização/agrupamento do
# sistema usa exclusivamente "local_trabalho"; "filial" é só guardada como
# dado de referência, nunca usada em filtro/matching/campanha.
ALIASES_COLUNAS = {
    "id": ["matricula", "id"],
    "nome": ["nome"],
    "cpf": ["cpf"],
    "empresa": ["empresa"],
    "filial": ["filial"],
    "ghe_area": ["ghe/area", "ghe/área", "ghe area"],
    "local_trabalho": ["local de trabalho"],
    "funcao": ["funcao", "função"],
    "data_admissao": ["data de admissao", "data de admissão"],
    "tipo_aso": ["tipo de aso"],
    "data_ultimo_aso": ["data aso", "data do aso", "data ultimo aso", "data último aso", "data_ultimo_aso"],
    "data_realizacao": [
        "data realizacao", "data realização", "data do exame", "data exame",
        "data que fez", "data de realizacao", "data de realização",
    ],
    "observacoes": ["observacoes", "observações", "observacao", "observação", "obs"],
}


def _normalizar_cabecalho(texto: str) -> str:
    """minúsculo, sem acento, espaços colapsados — pra 'Matrícula' bater com o
    alias 'matricula' independente de acentuação de quem escreveu a planilha."""
    texto = str(texto).strip().lower()
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"\s+", " ", texto)


def mapear_colunas(df: pd.DataFrame) -> pd.DataFrame:
    """Renomeia as colunas da planilha (nomes reais da empresa) para os nomes internos usados no banco."""
    colunas_originais = {_normalizar_cabecalho(c): c for c in df.columns}
    renomear = {}
    for campo_interno, aliases in ALIASES_COLUNAS.items():
        for alias in aliases:
            alias_normalizado = _normalizar_cabecalho(alias)
            if alias_normalizado in colunas_originais:
                renomear[colunas_originais[alias_normalizado]] = campo_interno
                break
    return df.rename(columns=renomear)


def validar_colunas_identificacao(df: pd.DataFrame) -> None:
    """Garante que a planilha tem pelo menos uma forma de identificar quem é
    cada linha (id, cpf ou nome) depois do mapeamento de colunas. Sem isso,
    toda linha cairia silenciosamente na fila de exceções — melhor recusar
    com uma mensagem clara do que forçar revisão manual de centenas de linhas.

    Sintoma típico de planilha sem cabeçalho reconhecível: colunas aparecem
    como "Unnamed: 0", "Unnamed: 1"... (o pandas tratou a primeira linha de
    dados como se fosse o cabeçalho).
    """
    if "id" in df.columns or "cpf" in df.columns or "nome" in df.columns:
        return
    colunas_encontradas = ", ".join(str(c) for c in df.columns)
    raise ValueError(
        "Não consegui reconhecer nenhuma coluna de identificação (Matricula/ID, "
        "CPF ou Nome) nessa planilha. Colunas encontradas: "
        f"{colunas_encontradas}. Confira se a primeira linha do arquivo é "
        "mesmo o cabeçalho (com esses nomes) e não uma linha de dados."
    )
