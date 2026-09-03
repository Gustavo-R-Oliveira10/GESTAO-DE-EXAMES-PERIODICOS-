from datetime import date

import pytest

import campanhas


@pytest.fixture
def duas_pessoas(conn):
    """Joao: vencido. Maria: dispensado. Ambos em Brasilia."""
    conn.execute(
        """INSERT INTO funcionarios (id, nome, nome_normalizado, local_trabalho, status_aso)
           VALUES ('1', 'Joao', 'JOAO', 'Brasilia', 'Precisa fazer exame')"""
    )
    conn.execute(
        """INSERT INTO funcionarios (id, nome, nome_normalizado, local_trabalho, status_aso)
           VALUES ('2', 'Maria', 'MARIA', 'Brasilia', 'Dispensado')"""
    )
    conn.commit()
    return conn


class TestCriarCampanha:
    def test_nao_faz_snapshot_automatico(self, duas_pessoas):
        """Mudança de comportamento: a meta só é definida depois do
        cruzamento com a lista do RH, nunca na criação da campanha."""
        campanha_id = campanhas.criar_campanha(
            duas_pessoas, "Brasilia", date(2026, 9, 2), date(2026, 9, 4), kits_enviados=False
        )
        c = campanhas.obter_campanha(duas_pessoas, campanha_id)
        assert c.total_membros == 0

    def test_guarda_detalhe_operacao(self, duas_pessoas):
        campanha_id = campanhas.criar_campanha(
            duas_pessoas, "Brasilia", date(2026, 9, 2), date(2026, 9, 4),
            kits_enviados=True, detalhe_operacao="09h-18h",
        )
        c = campanhas.obter_campanha(duas_pessoas, campanha_id)
        assert c.detalhe_operacao == "09h-18h"
        assert c.kits_enviados is True


class TestRegistrarResultadoListaRh:
    def test_convocado_conta_pra_meta_ja_dispensado_nao(self, duas_pessoas):
        campanha_id = campanhas.criar_campanha(
            duas_pessoas, "Brasilia", date(2026, 9, 2), date(2026, 9, 4), kits_enviados=False
        )
        campanhas.registrar_resultado_lista_rh(
            duas_pessoas, campanha_id, "rh.xlsx",
            convocados=[{"funcionario_id": "1", "nome": "Joao"}],
            ja_dispensados=[{"funcionario_id": "2", "nome": "Maria"}],
        )
        c = campanhas.obter_campanha(duas_pessoas, campanha_id)
        assert c.total_membros == 1  # só o Joao (convocado) conta

        membros = duas_pessoas.execute(
            "SELECT funcionario_id FROM campanha_membros WHERE campanha_id=?", (campanha_id,)
        ).fetchall()
        assert [m["funcionario_id"] for m in membros] == ["1"]

    def test_trava_lista_rh_apos_registrar(self, duas_pessoas):
        campanha_id = campanhas.criar_campanha(
            duas_pessoas, "Brasilia", date(2026, 9, 2), date(2026, 9, 4), kits_enviados=False
        )
        assert campanhas.campanha_ja_processou_lista_rh(duas_pessoas, campanha_id) is False
        campanhas.registrar_resultado_lista_rh(duas_pessoas, campanha_id, "rh.xlsx", [], [])
        assert campanhas.campanha_ja_processou_lista_rh(duas_pessoas, campanha_id) is True

    def test_obter_resultado_lista_rh_retorna_as_duas_listas(self, duas_pessoas):
        campanha_id = campanhas.criar_campanha(
            duas_pessoas, "Brasilia", date(2026, 9, 2), date(2026, 9, 4), kits_enviados=False
        )
        campanhas.registrar_resultado_lista_rh(
            duas_pessoas, campanha_id, "rh.xlsx",
            convocados=[{"funcionario_id": "1", "nome": "Joao"}],
            ja_dispensados=[{"funcionario_id": "2", "nome": "Maria"}],
        )
        convocados, ja_dispensados = campanhas.obter_resultado_lista_rh(duas_pessoas, campanha_id)
        assert [c["funcionario_id"] for c in convocados] == ["1"]
        assert [c["funcionario_id"] for c in ja_dispensados] == ["2"]


class TestSeedCronogramaOficial:
    def test_cria_as_cinco_campanhas_oficiais(self, conn):
        criadas = campanhas.seed_campanhas_oficiais(conn)
        assert criadas == 5
        locais = {r["local_trabalho"] for r in conn.execute("SELECT local_trabalho FROM campanhas")}
        assert locais == {"Brasilia", "Botafogo", "Península", "Recife", "Curitiba"}

    def test_idempotente_ao_rodar_de_novo(self, conn):
        campanhas.seed_campanhas_oficiais(conn)
        criadas_segunda_vez = campanhas.seed_campanhas_oficiais(conn)
        assert criadas_segunda_vez == 0
        total = conn.execute("SELECT COUNT(*) AS n FROM campanhas").fetchone()["n"]
        assert total == 5

    def test_preserva_campanha_criada_manualmente_com_dados_diferentes(self, conn):
        """Cenário real: o usuário já tinha criado a campanha de Brasília na
        mão, com datas próprias, antes do seed rodar. O seed não pode
        sobrescrever nem duplicar."""
        id_manual = campanhas.criar_campanha(
            conn, "Brasilia", date(2026, 8, 1), date(2026, 8, 15), kits_enviados=True
        )
        criadas = campanhas.seed_campanhas_oficiais(conn)
        assert criadas == 4  # pulou Brasilia, criou as outras 4

        brasilia = conn.execute(
            "SELECT id, data_inicio, kits_enviados FROM campanhas WHERE local_trabalho='Brasilia'"
        ).fetchall()
        assert len(brasilia) == 1
        assert brasilia[0]["id"] == id_manual
        assert brasilia[0]["data_inicio"] == "2026-08-01"
        assert brasilia[0]["kits_enviados"] == 1
