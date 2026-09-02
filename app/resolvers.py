"""Camada de reconciliação de exceções — interface plugável.

Hoje só existe o ResolvedorManual (você decide na tela do Streamlit).
Para plugar uma LLM (OpenAI/Gemini) no futuro, implemente a mesma interface
em ResolvedorLLM e troque a instância usada em pipeline de matching — nada
mais no sistema precisa mudar. Nenhum resolvedor escreve na base mestre:
ele só sugere, quem confirma é sempre o humano na tela de exceções.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Candidato:
    funcionario_id: str
    nome: str
    score: float  # 0-100


@dataclass
class ResolucaoSugerida:
    funcionario_id: str | None
    confianca: float  # 0-100
    justificativa: str


class ResolvedorDeExcecao(ABC):
    """Interface que qualquer resolvedor de exceção deve implementar."""

    @abstractmethod
    def resolver(self, registro_bruto: str, candidatos: list[Candidato]) -> ResolucaoSugerida:
        ...


class ResolvedorManual(ResolvedorDeExcecao):
    """Não decide nada sozinho — apenas devolve os candidatos para confirmação humana na tela."""

    def resolver(self, registro_bruto: str, candidatos: list[Candidato]) -> ResolucaoSugerida:
        return ResolucaoSugerida(
            funcionario_id=None,
            confianca=0.0,
            justificativa="Resolução manual: aguardando confirmação humana na tela de exceções.",
        )


class ResolvedorLLM(ResolvedorDeExcecao):
    """Esqueleto pronto para plugar uma API de LLM (OpenAI ou Gemini).

    Implementação futura: montar um prompt com `registro_bruto` (nome digitado
    errado, observação livre de RH, etc.) + `candidatos` da base mestre, chamar
    a API configurada via .env (PROVEDOR_LLM, LLM_API_KEY, LLM_MODEL) e
    devolver uma ResolucaoSugerida. A sugestão sempre passa pela mesma tela de
    confirmação do ResolvedorManual — nunca escreve direto na base mestre.
    Toda chamada deve ser registrada em auditoria_llm (ver app/db.py).
    """

    def __init__(self, provedor: str, api_key: str, model: str):
        self.provedor = provedor
        self.api_key = api_key
        self.model = model

    def resolver(self, registro_bruto: str, candidatos: list[Candidato]) -> ResolucaoSugerida:
        raise NotImplementedError(
            "ResolvedorLLM ainda não implementado — plugue a chamada à API "
            f"do provedor '{self.provedor}' aqui quando for habilitar a resolução assistida por IA."
        )
