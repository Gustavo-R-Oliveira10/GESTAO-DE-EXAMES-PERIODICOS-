from datetime import date

import pytest

from baixa_diaria import processar_baixa_diaria
from matching import normalizar_nome


@pytest.fixture
def base_populada(conn):
    conn.execute(
        """INSERT INTO funcionarios (id, nome, nome_normalizado, local_trabalho, status_aso)
           VALUES ('1', 'Joao', ?, 'Brasilia', 'Precisa fazer exame')""",
        (normalizar_nome("Joao"),),
    )
    conn.commit()
    return conn


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
