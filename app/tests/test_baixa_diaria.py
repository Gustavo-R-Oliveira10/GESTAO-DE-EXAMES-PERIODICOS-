from datetime import date

import pytest

import campanhas
from baixa_diaria import processar_baixa_diaria
from matching import normalizar_nome
from datetime import date as date_cls


@pytest.fixture
def base_populada(conn):
    conn.execute(
        """INSERT INTO funcionarios (id, nome, nome_normalizado, local_trabalho, status_aso)
           VALUES ('1', 'Joao', ?, 'Brasilia', 'Precisa fazer exame')""",
        (normalizar_nome("Joao"),),
    )
    conn.commit()
    return conn


@pytest.fixture
def campanha_id(base_populada):
    return campanhas.criar_campanha(
        base_populada, "Brasilia", date_cls(2026, 9, 2), date_cls(2026, 9, 4), kits_enviados=False
    )


class TestProcessarBaixaDiaria:
    def test_aplica_baixa_e_atualiza_status(self, base_populada):
        rel = processar_baixa_diaria(
            base_populada, [{"id": "1", "nome": "Joao", "data_realizacao": "02/09/2026"}],
            date(2026, 9, 2), local_trabalho="Brasilia",
        )
        assert len(rel.fizeram) == 1
        row = base_populada.execute("SELECT status_aso, status_fila FROM funcionarios WHERE id='1'").fetchone()
        assert row["status_aso"] == "Dispensado"
        assert row["status_fila"] == "Concluído"

    def test_nao_encontrado_vira_excecao(self, base_populada):
        rel = processar_baixa_diaria(
            base_populada, [{"nome": "Pessoa Desconhecida XPTO"}], date(2026, 9, 2), local_trabalho="Brasilia",
        )
        assert len(rel.fizeram) == 0
        assert len(rel.inconsistencias) == 1
        pendentes = base_populada.execute(
            "SELECT COUNT(*) AS n FROM excecoes_matching WHERE status='pendente'"
        ).fetchone()["n"]
        assert pendentes == 1

    def test_duplicata_na_planilha_vira_inconsistencia(self, base_populada):
        rel = processar_baixa_diaria(
            base_populada,
            [{"id": "1", "nome": "Joao"}, {"id": "1", "nome": "Joao"}],
            date(2026, 9, 2), local_trabalho="Brasilia",
        )
        assert len(rel.fizeram) == 1
        assert any("Duplicado" in i.motivo for i in rel.inconsistencias)

    def test_pendente_na_coluna_de_data_nao_aplica_baixa(self, base_populada):
        """Regressão de bug real: a planilha real da empresa traz TODO MUNDO
        (não só quem foi), com a coluna 'Data Aso' preenchida com a data real
        OU o texto 'Pendente'. O sistema estava tratando 'apareceu na
        planilha' como sinônimo de 'fez o exame', aplicando baixa em todo
        mundo — inclusive quem estava marcado como Pendente."""
        rel = processar_baixa_diaria(
            base_populada,
            [{"id": "1", "nome": "Joao", "data_ultimo_aso": "Pendente"}],
            date(2026, 9, 2), local_trabalho="Brasilia",
        )
        assert len(rel.fizeram) == 0
        assert len(rel.ainda_pendentes) == 1
        assert rel.ainda_pendentes[0].funcionario_id == "1"
        row = base_populada.execute("SELECT status_fila, status_aso FROM funcionarios WHERE id='1'").fetchone()
        assert row["status_fila"] != "Concluído"
        assert row["status_aso"] == "Precisa fazer exame"

    def test_data_real_na_coluna_data_ultimo_aso_aplica_baixa(self, base_populada):
        """Mesma planilha real: quando a coluna 'Data Aso' vem com uma data de
        verdade (mapeada para 'data_ultimo_aso'), a baixa deve ser aplicada
        normalmente, usando aquela data — não precisa de coluna dedicada
        'data_realizacao'."""
        rel = processar_baixa_diaria(
            base_populada,
            [{"id": "1", "nome": "Joao", "data_ultimo_aso": "02/09/2026"}],
            date(2026, 9, 2), local_trabalho="Brasilia",
        )
        assert len(rel.fizeram) == 1
        assert len(rel.ainda_pendentes) == 0
        row = base_populada.execute("SELECT status_fila, data_ultimo_aso FROM funcionarios WHERE id='1'").fetchone()
        assert row["status_fila"] == "Concluído"
        assert row["data_ultimo_aso"] == "2026-09-02"

    def test_lista_de_presenca_pura_sem_coluna_de_data_continua_funcionando(self, base_populada):
        """Não pode quebrar o caso de uso original: uma lista simples de
        presença (só quem foi, sem nenhuma coluna de data) ainda deve aplicar
        baixa usando a data do relatório."""
        rel = processar_baixa_diaria(
            base_populada, [{"id": "1", "nome": "Joao"}], date(2026, 9, 2), local_trabalho="Brasilia",
        )
        assert len(rel.fizeram) == 1
        assert rel.fizeram[0].data_realizacao == "2026-09-02"

    def test_registra_atendimento_na_campanha_quando_fez_o_exame(self, base_populada, campanha_id):
        rel = processar_baixa_diaria(
            base_populada, [{"id": "1", "nome": "Joao", "data_ultimo_aso": "02/09/2026"}],
            date(2026, 9, 2), local_trabalho="Brasilia", campanha_id=campanha_id,
        )
        assert len(rel.fizeram) == 1
        row = base_populada.execute(
            "SELECT data_atendimento FROM campanha_atendimentos WHERE campanha_id=? AND funcionario_id='1'",
            (campanha_id,),
        ).fetchone()
        assert row is not None
        assert row["data_atendimento"] == "2026-09-02"

    def test_nao_registra_atendimento_para_quem_esta_pendente(self, base_populada, campanha_id):
        processar_baixa_diaria(
            base_populada, [{"id": "1", "nome": "Joao", "data_ultimo_aso": "Pendente"}],
            date(2026, 9, 2), local_trabalho="Brasilia", campanha_id=campanha_id,
        )
        row = base_populada.execute(
            "SELECT 1 FROM campanha_atendimentos WHERE campanha_id=? AND funcionario_id='1'",
            (campanha_id,),
        ).fetchone()
        assert row is None

    def test_sem_campanha_id_nao_registra_atendimento(self, base_populada):
        """Baixa diária processada fora do contexto de campanha (campanha_id=None)
        continua funcionando, só não grava em campanha_atendimentos."""
        rel = processar_baixa_diaria(
            base_populada, [{"id": "1", "nome": "Joao", "data_ultimo_aso": "02/09/2026"}],
            date(2026, 9, 2), local_trabalho="Brasilia",
        )
        assert len(rel.fizeram) == 1
        total = base_populada.execute("SELECT COUNT(*) AS n FROM campanha_atendimentos").fetchone()["n"]
        assert total == 0

    def test_valor_nao_reconhecido_vira_inconsistencia_nao_pendente(self, base_populada):
        """Um valor que não é data nem 'Pendente' não deve decidir sozinho
        pra nenhum dos dois lados — vira inconsistência para revisão manual."""
        rel = processar_baixa_diaria(
            base_populada,
            [{"id": "1", "nome": "Joao", "data_ultimo_aso": "??texto estranho??"}],
            date(2026, 9, 2), local_trabalho="Brasilia",
        )
        assert len(rel.fizeram) == 0
        assert len(rel.ainda_pendentes) == 0
        assert len(rel.inconsistencias) == 1
