"""Log de auditoria simples em arquivo CSV local — registra data/hora e ação
de todo processamento que altera a base mestre (baixa diária, criação de
campanha, recarga da base mestre a partir do arquivo fixo, etc.)."""
from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path

CAMINHO_LOG = Path(__file__).parent / "data" / "log_eventos.csv"
CABECALHO = ["data_hora", "acao", "detalhe"]


def registrar_log(acao: str, detalhe: str = "") -> None:
    CAMINHO_LOG.parent.mkdir(parents=True, exist_ok=True)
    arquivo_novo = not CAMINHO_LOG.exists()
    with open(CAMINHO_LOG, "a", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        if arquivo_novo:
            writer.writerow(CABECALHO)
        writer.writerow([datetime.now().isoformat(timespec="seconds"), acao, detalhe])


def ler_logs(limite: int = 500) -> list[dict]:
    """Retorna os eventos mais recentes primeiro."""
    if not CAMINHO_LOG.exists():
        return []
    with open(CAMINHO_LOG, newline="", encoding="utf-8-sig") as f:
        linhas = list(csv.DictReader(f))
    return list(reversed(linhas))[:limite]
