import pytest

from matching import cruzar_lista_rh, normalizar_nome


@pytest.fixture
def base_populada(conn):
    funcionarios = [
        ("1", "Joao da Silva Santos", normalizar_nome("Joao da Silva Santos"), "11122233344", "Brasilia"),
        ("2", "Maria Aparecida Souza", normalizar_nome("Maria Aparecida Souza"), None, "Brasilia"),
        ("3", "Carlos Eduardo Pereira", normalizar_nome("Carlos Eduardo Pereira"), "55566677788", "Sao Paulo"),
    ]
    for f in funcionarios:
        conn.execute(
            "INSERT INTO funcionarios (id, nome, nome_normalizado, cpf, local_trabalho) VALUES (?,?,?,?,?)", f
        )
    conn.commit()
    return conn


class TestCruzarListaRh:
    def test_match_por_id_exato(self, base_populada):
        r = cruzar_lista_rh(base_populada, [{"id": "1", "nome": "Joao da Silva Santos"}])
        assert r[0].camada == "id"
        assert r[0].funcionario_id == "1"

    def test_match_por_cpf_exato(self, base_populada):
        r = cruzar_lista_rh(base_populada, [{"cpf": "55566677788", "nome": "Carlos"}])
        assert r[0].camada == "cpf"
        assert r[0].funcionario_id == "3"

    def test_match_por_nome_normalizado_exato(self, base_populada):
        r = cruzar_lista_rh(base_populada, [{"nome": "MARIA APARECIDA SOUZA"}])
        assert r[0].camada == "nome_exato"
        assert r[0].funcionario_id == "2"

    def test_match_fuzzy_por_typo(self, base_populada):
        r = cruzar_lista_rh(base_populada, [{"nome": "Joao da Silva Santoss"}])
        assert r[0].camada == "fuzzy"
        assert r[0].funcionario_id == "1"

    def test_sem_match_vira_excecao_com_candidatos(self, base_populada):
        r = cruzar_lista_rh(base_populada, [{"nome": "Pessoa Completamente Desconhecida"}])
        assert r[0].camada == "excecao"
        assert r[0].funcionario_id is None
        assert len(r[0].candidatos) > 0

    def test_id_e_cpf_sao_globais_mesmo_filtrando_por_local(self, base_populada):
        """Carlos é de Sao Paulo, mas se o ID/CPF bate, encontra mesmo
        filtrando o cruzamento pelo local_trabalho de Brasilia."""
        r = cruzar_lista_rh(base_populada, [{"id": "3", "nome": "Carlos"}], local_trabalho="Brasilia")
        assert r[0].camada == "id"
        assert r[0].funcionario_id == "3"

    def test_nome_fica_restrito_ao_local_trabalho_informado(self, base_populada):
        """Sem ID/CPF, um nome parecido só deve casar dentro do local
        informado — evita falso-positivo entre locais diferentes."""
        r = cruzar_lista_rh(base_populada, [{"nome": "Carlos Eduardo Pereira"}], local_trabalho="Brasilia")
        assert r[0].camada == "excecao"

    def test_duplicata_na_planilha_gera_dois_resultados_independentes(self, base_populada):
        r = cruzar_lista_rh(base_populada, [{"id": "1"}, {"id": "1"}])
        assert len(r) == 2
        assert all(x.funcionario_id == "1" for x in r)
