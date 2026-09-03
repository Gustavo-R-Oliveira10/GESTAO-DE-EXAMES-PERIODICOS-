from datetime import date

import pandas as pd
import pytest

import importacao_base


def _escrever_planilha_mestra(caminho, linhas):
    pd.DataFrame(linhas).to_excel(caminho, index=False)


@pytest.fixture
def arquivo_mestre(tmp_path, monkeypatch):
    caminho = tmp_path / "mestra.xlsx"
    monkeypatch.setattr(importacao_base, "CAMINHO_BASE_MESTRE_FIXA", caminho)
    return caminho


class TestCarregarSeVazia:
    def test_nao_faz_nada_se_arquivo_nao_existe(self, conn, arquivo_mestre):
        assert importacao_base.carregar_base_mestre_se_vazia(conn) is None

    def test_carrega_quando_banco_vazio(self, conn, arquivo_mestre):
        _escrever_planilha_mestra(arquivo_mestre, [
            {"Matricula": "1", "Nome": "Joao", "Local de Trabalho": "Brasilia", "Data Aso": "01/01/2026"},
        ])
        inseridos = importacao_base.carregar_base_mestre_se_vazia(conn)
        assert inseridos == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM funcionarios").fetchone()["n"] == 1

    def test_nao_recarrega_se_banco_ja_tem_dados(self, conn, arquivo_mestre):
        conn.execute(
            "INSERT INTO funcionarios (id, nome, nome_normalizado) VALUES ('99','X','X')"
        )
        conn.commit()
        _escrever_planilha_mestra(arquivo_mestre, [{"Matricula": "1", "Nome": "Joao", "Data Aso": "01/01/2026"}])
        assert importacao_base.carregar_base_mestre_se_vazia(conn) is None
        assert conn.execute("SELECT COUNT(*) AS n FROM funcionarios").fetchone()["n"] == 1

    def test_cria_backup_com_timestamp(self, conn, arquivo_mestre):
        _escrever_planilha_mestra(arquivo_mestre, [{"Matricula": "1", "Nome": "Joao", "Data Aso": "01/01/2026"}])
        importacao_base.carregar_base_mestre_se_vazia(conn)
        backups = list(importacao_base.PASTA_BACKUPS_BASE_MESTRA.glob("*.xlsx"))
        assert len(backups) == 1
        assert backups[0].name.startswith("mestra_")


class TestRecarregarBaseMestre:
    def test_levanta_erro_se_arquivo_nao_existe(self, conn, arquivo_mestre):
        with pytest.raises(FileNotFoundError):
            importacao_base.recarregar_base_mestre(conn)

    def test_nao_regride_data_ultimo_aso_ja_processada(self, conn, arquivo_mestre):
        """Cenário real: alguém já fez o exame (baixa aplicada, data recente
        no banco), mas o arquivo fixo ainda tem a data antiga (RH não
        atualizou a planilha original). Recarregar não pode apagar a baixa."""
        conn.execute(
            """INSERT INTO funcionarios (id, nome, nome_normalizado, data_ultimo_aso, status_aso)
               VALUES ('1', 'Joao', 'JOAO', '2026-09-02', 'Dispensado')"""
        )
        conn.commit()
        _escrever_planilha_mestra(arquivo_mestre, [
            {"Matricula": "1", "Nome": "Joao", "Data Aso": "22/10/2022"},  # data antiga no arquivo
        ])
        importacao_base.recarregar_base_mestre(conn)
        row = conn.execute("SELECT data_ultimo_aso, status_aso FROM funcionarios WHERE id='1'").fetchone()
        assert row["data_ultimo_aso"] == "2026-09-02"
        assert row["status_aso"] == "Dispensado"

    def test_atualiza_cadastro_incluindo_local_trabalho(self, conn, arquivo_mestre):
        """Caso de uso real do usuário: corrigir local de trabalho de
        alguém (ex: estava como RJ, na verdade é de SP) direto no Excel e
        recarregar pra refletir no banco."""
        conn.execute(
            """INSERT INTO funcionarios (id, nome, nome_normalizado, local_trabalho)
               VALUES ('1', 'Joao', 'JOAO', 'Botafogo')"""
        )
        conn.commit()
        _escrever_planilha_mestra(arquivo_mestre, [
            {"Matricula": "1", "Nome": "Joao", "Local de Trabalho": "Sao Paulo", "Data Aso": "01/01/2026"},
        ])
        resultado = importacao_base.recarregar_base_mestre(conn)
        assert resultado["atualizados"] == 1
        row = conn.execute("SELECT local_trabalho FROM funcionarios WHERE id='1'").fetchone()
        assert row["local_trabalho"] == "Sao Paulo"

    def test_insere_funcionario_novo(self, conn, arquivo_mestre):
        _escrever_planilha_mestra(arquivo_mestre, [
            {"Matricula": "99", "Nome": "Novato", "Data Aso": "01/01/2026"},
        ])
        resultado = importacao_base.recarregar_base_mestre(conn)
        assert resultado["novos"] == 1
        assert conn.execute("SELECT COUNT(*) AS n FROM funcionarios").fetchone()["n"] == 1

    def test_reconcilia_capitalizacao_do_local_trabalho(self, conn, arquivo_mestre):
        """'CURITIBA' e 'Curitiba' não podem virar dois locais diferentes —
        a recarga deve usar a grafia já estabelecida na base."""
        conn.execute(
            """INSERT INTO funcionarios (id, nome, nome_normalizado, local_trabalho)
               VALUES ('1', 'Joao', 'JOAO', 'Curitiba')"""
        )
        conn.commit()
        _escrever_planilha_mestra(arquivo_mestre, [
            {"Matricula": "2", "Nome": "Maria", "Local de Trabalho": "CURITIBA", "Data Aso": "01/01/2026"},
        ])
        importacao_base.recarregar_base_mestre(conn)
        row = conn.execute("SELECT local_trabalho FROM funcionarios WHERE id='2'").fetchone()
        assert row["local_trabalho"] == "Curitiba"

    def test_cria_backup_a_cada_recarga(self, conn, arquivo_mestre):
        _escrever_planilha_mestra(arquivo_mestre, [{"Matricula": "1", "Nome": "Joao", "Data Aso": "01/01/2026"}])
        importacao_base.recarregar_base_mestre(conn)
        importacao_base.recarregar_base_mestre(conn)
        backups = list(importacao_base.PASTA_BACKUPS_BASE_MESTRA.glob("*.xlsx"))
        assert len(backups) == 2

    def test_nunca_escreve_no_arquivo_original(self, conn, arquivo_mestre):
        _escrever_planilha_mestra(arquivo_mestre, [{"Matricula": "1", "Nome": "Joao", "Data Aso": "01/01/2026"}])
        conteudo_antes = arquivo_mestre.read_bytes()
        importacao_base.recarregar_base_mestre(conn)
        assert arquivo_mestre.read_bytes() == conteudo_antes
