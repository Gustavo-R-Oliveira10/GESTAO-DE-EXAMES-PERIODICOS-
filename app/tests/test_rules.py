from datetime import date

import pytest

from rules import aso_esta_valido, status_aso


class TestStatusAso:
    def test_abril_precisa_fazer_exame(self):
        assert status_aso(date(2026, 4, 30), 2026) == "Precisa fazer exame"

    def test_maio_dispensado(self):
        assert status_aso(date(2026, 5, 1), 2026) == "Dispensado"

    def test_qualquer_mes_apos_maio_dispensado(self):
        assert status_aso(date(2026, 12, 31), 2026) == "Dispensado"

    def test_sem_data_registrada(self):
        assert status_aso(None, 2026) == "Sem ASO registrado"

    def test_tipo_aso_nao_influencia_a_regra(self):
        """Decisão confirmada com o usuário: só a data importa, nunca o
        campo Tipo de Aso (PERIÓDICO BIENAL etc) — não há parâmetro pra
        isso na função de propósito."""
        # a assinatura da função não aceita tipo_aso — é a própria garantia
        assert status_aso(date(2026, 4, 1), 2026) == "Precisa fazer exame"

    @pytest.mark.parametrize("mes_corte", ["maio", "MAIO", "Maio"])
    def test_mes_corte_case_insensitive(self, mes_corte):
        assert aso_esta_valido(date(2026, 5, 1), 2026, mes_corte) is True
