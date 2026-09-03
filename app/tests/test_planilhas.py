from datetime import date

import pandas as pd
import pytest

from planilhas import mapear_colunas, parse_data, validar_colunas_identificacao


class TestParseData:
    def test_none_e_vazio(self):
        assert parse_data(None) is None
        assert parse_data("") is None
        assert parse_data("   ") is None
        assert parse_data(float("nan")) is None

    def test_formato_brasileiro_dd_mm_yyyy(self):
        assert parse_data("22/10/2022") == date(2022, 10, 22)
        assert parse_data("02/09/2026") == date(2026, 9, 2)

    def test_serial_excel(self):
        assert parse_data("45976") == date(2025, 11, 15)

    def test_timestamp_pandas_e_date_nativo(self):
        assert parse_data(pd.Timestamp("2026-03-05")) == date(2026, 3, 5)
        assert parse_data(date(2026, 3, 5)) == date(2026, 3, 5)

    @pytest.mark.parametrize(
        "texto, esperado",
        [
            ("2026-09-02", date(2026, 9, 2)),
            ("2026-02-09", date(2026, 2, 9)),
            ("2026-01-05", date(2026, 1, 5)),
            ("2025-08-18", date(2025, 8, 18)),
        ],
    )
    def test_iso_puro_nao_troca_dia_e_mes(self, texto, esperado):
        """Regressão: pd.to_datetime(dayfirst=True) reinterpretava ISO como
        YYYY-DD-MM quando o dia era <=12 (2026-09-02 virava fevereiro)."""
        assert parse_data(texto) == esperado

    @pytest.mark.parametrize(
        "texto, esperado",
        [
            ("2026-09-02 00:00:00", date(2026, 9, 2)),
            ("2026-02-09 00:00:00", date(2026, 2, 9)),
            ("2026-01-05 00:00:00", date(2026, 1, 5)),
            ("2025-08-18 00:00:00", date(2025, 8, 18)),
        ],
    )
    def test_iso_com_hora_nao_troca_dia_e_mes(self, texto, esperado):
        """Mesma regressão acima, mas com hora junto — é assim que o pandas
        serializa uma célula de data do Excel quando lida com dtype=str
        (formato real encontrado na planilha mestra da empresa). Achado
        depois do primeiro fix, porque o regex do ISO só cobria data pura."""
        assert parse_data(texto) == esperado

    def test_texto_invalido_retorna_none(self):
        assert parse_data("não é uma data") is None


class TestMapearColunas:
    def test_reconhece_nomes_reais_da_empresa(self):
        df = pd.DataFrame([{
            "Matricula": "1", "Nome": "X", "Empresa": "HB", "Filial": "F",
            "GHE/Area": "G", "Local de Trabalho": "SP", "Funcao": "Y",
            "Data de Admissao": "01/01/2020", "Tipo de Aso": "PERIODICO",
            "Data Aso": "01/01/2026",
        }])
        mapeado = mapear_colunas(df)
        esperado = {
            "id", "nome", "empresa", "filial", "ghe_area", "local_trabalho",
            "funcao", "data_admissao", "tipo_aso", "data_ultimo_aso",
        }
        assert esperado.issubset(set(mapeado.columns))

    def test_ignora_acentuacao_do_cabecalho(self):
        """'Matrícula' (com acento) precisa bater com o alias 'matricula'
        independente de quem escreveu a planilha ter acentuado ou não."""
        df = pd.DataFrame([{"Matrícula": "1", "Nome": "X"}])
        mapeado = mapear_colunas(df)
        assert "id" in mapeado.columns

    def test_filial_e_local_trabalho_nao_se_confundem(self):
        """'Filial' nunca deve virar alias de 'local_trabalho' — são colunas
        cadastrais distintas; só local_trabalho entra em lógica de negócio."""
        df = pd.DataFrame([{"Matricula": "1", "Nome": "X", "Filial": "Razao Social", "Local de Trabalho": "Curitiba"}])
        mapeado = mapear_colunas(df)
        assert mapeado.iloc[0]["filial"] == "Razao Social"
        assert mapeado.iloc[0]["local_trabalho"] == "Curitiba"


class TestValidarColunasIdentificacao:
    def test_aceita_planilha_com_id(self):
        df = mapear_colunas(pd.DataFrame([{"Matricula": "1", "Nome": "X"}]))
        validar_colunas_identificacao(df)  # não deve levantar

    def test_recusa_planilha_sem_cabecalho_reconhecivel(self):
        """Sintoma real: planilha sem linha de cabeçalho vira 'Unnamed: 0/1' —
        deve recusar em vez de silenciosamente jogar tudo em exceção."""
        df = pd.DataFrame([["374411", "Joao"], ["379065", "Maria"]])
        with pytest.raises(ValueError, match="Não consegui reconhecer"):
            validar_colunas_identificacao(df)
