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


class TestDashboardPorCampanha:
    """Fizeram / Não precisaram / Pendentes — a diferença entre 'concluído
    porque compareceu nesta campanha' e 'concluído por algum outro motivo'."""

    def test_fez_o_exame_aqui_conta_como_fizeram(self, duas_pessoas):
        campanha_id = campanhas.criar_campanha(
            duas_pessoas, "Brasilia", date(2026, 9, 2), date(2026, 9, 4), kits_enviados=False
        )
        campanhas.registrar_resultado_lista_rh(
            duas_pessoas, campanha_id, "rh.xlsx",
            convocados=[{"funcionario_id": "1", "nome": "Joao"}], ja_dispensados=[],
        )
        duas_pessoas.execute("UPDATE funcionarios SET status_aso='Dispensado' WHERE id='1'")
        duas_pessoas.execute(
            """INSERT INTO campanha_atendimentos (campanha_id, funcionario_id, data_atendimento, criado_em)
               VALUES (?, '1', '2026-09-02', '2026-09-02T10:00:00')""",
            (campanha_id,),
        )
        duas_pessoas.commit()

        c = campanhas.obter_campanha(duas_pessoas, campanha_id)
        assert c.fizeram == 1
        assert c.nao_precisou == 0
        assert c.pendentes == 0
        assert c.concluidos == 1

    def test_dispensado_sem_comparecer_conta_como_nao_precisou(self, duas_pessoas):
        """Alguém convocado (estava vencido) que virou Dispensado sem nunca
        ter um registro de comparecimento nesta campanha — ex: recarga da
        base trouxe um ASO mais recente feito por fora."""
        campanha_id = campanhas.criar_campanha(
            duas_pessoas, "Brasilia", date(2026, 9, 2), date(2026, 9, 4), kits_enviados=False
        )
        campanhas.registrar_resultado_lista_rh(
            duas_pessoas, campanha_id, "rh.xlsx",
            convocados=[{"funcionario_id": "1", "nome": "Joao"}], ja_dispensados=[],
        )
        duas_pessoas.execute("UPDATE funcionarios SET status_aso='Dispensado' WHERE id='1'")
        duas_pessoas.commit()

        c = campanhas.obter_campanha(duas_pessoas, campanha_id)
        assert c.fizeram == 0
        assert c.nao_precisou == 1
        assert c.pendentes == 0

        nao_precisou = campanhas.listar_membros_nao_precisou(duas_pessoas, campanha_id)
        assert [n["id"] for n in nao_precisou] == ["1"]

    def test_ainda_vencido_conta_como_pendente(self, duas_pessoas):
        campanha_id = campanhas.criar_campanha(
            duas_pessoas, "Brasilia", date(2026, 9, 2), date(2026, 9, 4), kits_enviados=False
        )
        campanhas.registrar_resultado_lista_rh(
            duas_pessoas, campanha_id, "rh.xlsx",
            convocados=[{"funcionario_id": "1", "nome": "Joao"}], ja_dispensados=[],
        )
        c = campanhas.obter_campanha(duas_pessoas, campanha_id)
        assert c.pendentes == 1
        assert c.fizeram == 0
        assert c.nao_precisou == 0

    def test_listar_membros_fizeram_traz_data_de_comparecimento(self, duas_pessoas):
        campanha_id = campanhas.criar_campanha(
            duas_pessoas, "Brasilia", date(2026, 9, 2), date(2026, 9, 4), kits_enviados=False
        )
        campanhas.registrar_resultado_lista_rh(
            duas_pessoas, campanha_id, "rh.xlsx",
            convocados=[{"funcionario_id": "1", "nome": "Joao"}], ja_dispensados=[],
        )
        duas_pessoas.execute("UPDATE funcionarios SET status_aso='Dispensado' WHERE id='1'")
        duas_pessoas.execute(
            """INSERT INTO campanha_atendimentos (campanha_id, funcionario_id, data_atendimento, criado_em)
               VALUES (?, '1', '2026-09-04', '2026-09-04T10:00:00')""",
            (campanha_id,),
        )
        duas_pessoas.commit()

        fizeram = campanhas.listar_membros_fizeram(duas_pessoas, campanha_id)
        assert fizeram[0]["data_atendimento"] == "2026-09-04"


class TestCronogramaDias:
    def test_seed_dias_cria_dois_dias_para_brasilia(self, conn):
        campanhas.seed_campanhas_oficiais(conn)
        criados = campanhas.seed_dias_campanhas_oficiais(conn)
        assert criados > 0

        campanha_id = conn.execute("SELECT id FROM campanhas WHERE local_trabalho='Brasilia'").fetchone()["id"]
        dias = campanhas.listar_dias_campanha(conn, campanha_id)
        assert len(dias) == 2
        assert dias[0]["data"] == "2026-09-02"
        assert dias[0]["hora_inicio"] == "09:00"
        assert dias[0]["hora_fim"] == "18:00"
        assert dias[1]["data"] == "2026-09-04"
        assert dias[1]["hora_fim"] == "14:00"

    def test_seed_dias_funciona_em_campanha_criada_manualmente(self, conn):
        """Não depende de ter sido criada pelo seed de campanhas — casa pelo
        local_trabalho, então funciona pra campanha manual também."""
        campanhas.criar_campanha(conn, "Brasilia", date(2026, 8, 1), date(2026, 8, 15), kits_enviados=True)
        criados = campanhas.seed_dias_campanhas_oficiais(conn)
        assert criados == 2

    def test_seed_dias_e_idempotente(self, conn):
        campanhas.seed_campanhas_oficiais(conn)
        campanhas.seed_dias_campanhas_oficiais(conn)
        segunda_vez = campanhas.seed_dias_campanhas_oficiais(conn)
        assert segunda_vez == 0

    def test_contagem_por_dia_reflete_atendimentos_reais(self, duas_pessoas):
        campanha_id = campanhas.criar_campanha(
            duas_pessoas, "Brasilia", date(2026, 9, 2), date(2026, 9, 4), kits_enviados=False
        )
        campanhas.seed_dias_campanhas_oficiais(duas_pessoas)
        duas_pessoas.execute(
            """INSERT INTO campanha_atendimentos (campanha_id, funcionario_id, data_atendimento, criado_em)
               VALUES (?, '1', '2026-09-02', '2026-09-02T10:00:00')""",
            (campanha_id,),
        )
        duas_pessoas.commit()

        dias = campanhas.listar_dias_campanha(duas_pessoas, campanha_id)
        dia_02 = next(d for d in dias if d["data"] == "2026-09-02")
        dia_04 = next(d for d in dias if d["data"] == "2026-09-04")
        assert dia_02["total_atendidos"] == 1
        assert dia_04["total_atendidos"] == 0


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
