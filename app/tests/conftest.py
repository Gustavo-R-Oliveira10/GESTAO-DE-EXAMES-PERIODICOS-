"""Configuração compartilhada dos testes.

A fixture `banco_isolado` roda automaticamente (autouse) em TODO teste e
redireciona banco, log e pasta de backups para um diretório temporário —
nenhum teste toca nos arquivos reais em app/data/. Isso existe porque, na
prática, esquecer de isolar já vazou dado de teste pra arquivo real mais de
uma vez durante o desenvolvimento (ver CHANGELOG.md) — a fixture autouse
torna esse cuidado automático em vez de depender de lembrar toda vez.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import db  # noqa: E402
import logs  # noqa: E402
import importacao_base  # noqa: E402


@pytest.fixture(autouse=True)
def banco_isolado(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    monkeypatch.setattr(logs, "CAMINHO_LOG", tmp_path / "log_eventos.csv")
    monkeypatch.setattr(importacao_base, "PASTA_BACKUPS_BASE_MESTRA", tmp_path / "backups")
    db.init_db()
    yield tmp_path


@pytest.fixture
def conn(banco_isolado):
    connection = db.get_connection()
    yield connection
    connection.close()
