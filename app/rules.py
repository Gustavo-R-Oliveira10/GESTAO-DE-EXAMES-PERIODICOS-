"""Regra de negócio: validade do ASO com base na data do último exame."""
from __future__ import annotations

from datetime import date

MESES = {
    "janeiro": 1, "fevereiro": 2, "março": 3, "abril": 4, "maio": 5, "junho": 6,
    "julho": 7, "agosto": 8, "setembro": 9, "outubro": 10, "novembro": 11,
    "dezembro": 12,
}


def data_corte(ano_campanha: int, mes_corte: str = "maio") -> date:
    """Primeiro dia do mês de corte: ASOs a partir dele (inclusive) dispensam novo exame."""
    return date(ano_campanha, MESES[mes_corte.lower()], 1)


def aso_esta_valido(data_ultimo_aso: date | None, ano_campanha: int, mes_corte: str = "maio") -> bool:
    """True = dispensado (ASO de maio em diante). False = precisa fazer o exame."""
    if data_ultimo_aso is None:
        return False
    return data_ultimo_aso >= data_corte(ano_campanha, mes_corte)


def status_aso(data_ultimo_aso: date | None, ano_campanha: int, mes_corte: str = "maio") -> str:
    if data_ultimo_aso is None:
        return "Sem ASO registrado"
    return "Dispensado" if aso_esta_valido(data_ultimo_aso, ano_campanha, mes_corte) else "Precisa fazer exame"
