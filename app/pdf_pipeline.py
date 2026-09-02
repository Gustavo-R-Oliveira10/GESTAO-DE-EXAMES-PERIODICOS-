"""Módulo 5 — Separação inteligente de PDFs de ASO em lote.

Fluxo:
1. Abre o PDF (lote enviado pela clínica) e extrai o texto de cada página —
   primeiro por extração nativa (PyMuPDF, PDFs digitais); se a página não tiver
   texto (documento escaneado/imagem), tenta OCR via pytesseract (requer o
   binário do Tesseract instalado na máquina — se não estiver, a página cai em
   pendente com aviso claro em vez de travar o processamento).
2. Em cada página, procura CPF e/ou matrícula (regex) e, na falta desses,
   linhas candidatas a nome. Páginas consecutivas sem identificação própria são
   tratadas como continuação do documento da pessoa identificada anterior
   (comum em ASOs com verso/anexo).
3. Cada grupo de páginas (= um ASO) é cruzado contra a base mestre pelo mesmo
   pipeline de matching do módulo 1. Se identificar com confiança, salva um PDF
   individual renomeado em pasta por filial/mês. Se não identificar, salva o
   PDF do grupo em uma pasta de pendências e cria um registro em
   `excecoes_pdf` para revisão manual na tela (nunca decide sozinho).
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from sqlite3 import Connection

import pymupdf as fitz

from matching import cruzar_lista_rh

PASTA_SAIDA_PADRAO = Path(__file__).parent / "data" / "asos_separados"
PASTA_PENDENTES_PADRAO = Path(__file__).parent / "data" / "asos_pendentes"

RE_CPF = re.compile(r"\b(\d{3}\.?\d{3}\.?\d{3}-?\d{2})\b")
RE_MATRICULA = re.compile(r"(?:matr[ií]cula|registro|chapa)\s*[:\-]?\s*(\d{4,12})", re.IGNORECASE)
RE_LINHA_NOME = re.compile(r"^[A-ZÀ-Ú][A-ZÀ-Ú\s]{6,60}$")
# Modelo real de ASO usado pela empresa (TAP Saúde/Huawei): "Atesto para os
# devidos fins, que o(a) Sr(a). NOME COMPLETO" — nome na mesma linha da frase,
# ou na linha seguinte. Captura restrita a uma única linha (sem \n no grupo)
# e case-sensitive no nome, para não vazar para o campo seguinte do formulário
# (ex: "Idade") caso ele também comece com letra maiúscula.
RE_NOME_ASO_SR = re.compile(r"(?i:Sr\(a\))\.?[ \t]*\n?[ \t]*([A-ZÀ-Ú][A-ZÀ-Ú \t]{5,60})")

MAX_PAGINAS_POR_GRUPO = 4  # trava de segurança para não juntar o PDF inteiro em um só grupo
LIMITE_CARACTERES_PAGINA_QUASE_VAZIA = 40  # só quase-em-branco conta como possível verso/assinatura
PALAVRAS_CONTINUACAO = (
    "continuacao", "continuação", "verso", "anexo", "assinatura", "pagina 2", "página 2",
)


def _e_continuacao_provavel(texto: str) -> bool:
    """Sinal explícito de que a página é continuação do ASO anterior (verso, anexo,
    assinatura) — nunca assume continuação só por falta de CPF/matrícula na página,
    pois isso poderia colar o ASO de uma pessoa desconhecida no arquivo de outra."""
    texto_norm = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii").lower()
    if any(palavra in texto_norm for palavra in PALAVRAS_CONTINUACAO):
        return True
    return len(texto.strip()) <= LIMITE_CARACTERES_PAGINA_QUASE_VAZIA


def _normalizar_cpf(cpf_bruto: str) -> str:
    return re.sub(r"\D", "", cpf_bruto)


def _slug(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode("ascii")
    texto = re.sub(r"[^A-Za-z0-9]+", "_", texto).strip("_")
    return texto.upper()


@dataclass
class TextoPagina:
    indice: int
    texto: str
    metodo: str  # "nativo" | "ocr" | "falhou"


def extrair_texto_pagina(pagina: fitz.Page, tentar_ocr: bool = True) -> TextoPagina:
    texto_nativo = pagina.get_text().strip()
    if texto_nativo:
        return TextoPagina(pagina.number, texto_nativo, "nativo")

    if not tentar_ocr:
        return TextoPagina(pagina.number, "", "falhou")

    try:
        import pytesseract
        from PIL import Image
        import io

        pix = pagina.get_pixmap(dpi=300)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        texto_ocr = pytesseract.image_to_string(img, lang="por").strip()
        return TextoPagina(pagina.number, texto_ocr, "ocr" if texto_ocr else "falhou")
    except Exception:
        # Tesseract não instalado na máquina, ou falha de OCR — não trava o lote,
        # a página vira pendente de revisão manual.
        return TextoPagina(pagina.number, "", "falhou")


@dataclass
class IdentificacaoPagina:
    cpf: str | None
    matricula: str | None
    nome_candidato: str | None


def identificar_pessoa_na_pagina(texto: str) -> IdentificacaoPagina:
    cpf = None
    m = RE_CPF.search(texto)
    if m:
        cpf = _normalizar_cpf(m.group(1))

    matricula = None
    m = RE_MATRICULA.search(texto)
    if m:
        matricula = m.group(1)

    nome_candidato = None
    m = RE_NOME_ASO_SR.search(texto)
    if m:
        nome_candidato = m.group(1).strip().title()

    if not nome_candidato:
        for linha in texto.splitlines():
            linha = linha.strip()
            if RE_LINHA_NOME.match(linha) and "ASO" not in linha and "ATESTADO" not in linha:
                nome_candidato = linha.title()
                break

    return IdentificacaoPagina(cpf, matricula, nome_candidato)


@dataclass
class GrupoPaginas:
    indices: list[int]
    identificacao: IdentificacaoPagina
    texto_completo: str
    metodo_extracao: str


def agrupar_paginas(paginas: list[TextoPagina]) -> list[GrupoPaginas]:
    """Junta páginas consecutivas sem identificação própria ao grupo anterior
    (continuação do mesmo ASO), até o limite de segurança MAX_PAGINAS_POR_GRUPO."""
    grupos: list[GrupoPaginas] = []

    for pag in paginas:
        ident = identificar_pessoa_na_pagina(pag.texto)
        tem_identificacao_propria = bool(ident.cpf or ident.matricula)

        pode_juntar_ao_anterior = (
            grupos
            and not tem_identificacao_propria
            and _e_continuacao_provavel(pag.texto)
            and len(grupos[-1].indices) < MAX_PAGINAS_POR_GRUPO
        )

        if pode_juntar_ao_anterior:
            grupo = grupos[-1]
            grupo.indices.append(pag.indice)
            grupo.texto_completo += "\n" + pag.texto
        else:
            grupos.append(
                GrupoPaginas(
                    indices=[pag.indice],
                    identificacao=ident,
                    texto_completo=pag.texto,
                    metodo_extracao=pag.metodo,
                )
            )

    return grupos


@dataclass
class ItemSeparado:
    funcionario_id: str
    nome: str
    arquivo: str
    paginas: list[int]


@dataclass
class ItemPendente:
    excecao_id: int
    paginas: list[int]
    motivo: str
    arquivo_pendente: str


@dataclass
class RelatorioSeparacao:
    separados: list[ItemSeparado] = field(default_factory=list)
    pendentes: list[ItemPendente] = field(default_factory=list)


def processar_lote_pdf(
    conn: Connection,
    caminho_pdf: str | Path,
    nome_arquivo_origem: str,
    local_trabalho: str | None = None,
    pasta_saida: Path = PASTA_SAIDA_PADRAO,
    pasta_pendentes: Path = PASTA_PENDENTES_PADRAO,
    tentar_ocr: bool = True,
) -> RelatorioSeparacao:
    doc = fitz.open(caminho_pdf)
    paginas_texto = [extrair_texto_pagina(doc[i], tentar_ocr=tentar_ocr) for i in range(len(doc))]
    grupos = agrupar_paginas(paginas_texto)

    relatorio = RelatorioSeparacao()
    hoje = date.today()
    agora = datetime.now().isoformat(timespec="seconds")

    for grupo in grupos:
        linha_busca = {
            "cpf": grupo.identificacao.cpf,
            "id": grupo.identificacao.matricula,
            "nome": grupo.identificacao.nome_candidato or "",
        }
        resultados = cruzar_lista_rh(conn, [linha_busca], local_trabalho=local_trabalho)
        resultado = resultados[0]

        novo_doc = fitz.open()
        for indice in grupo.indices:
            novo_doc.insert_pdf(doc, from_page=indice, to_page=indice)

        if resultado.camada != "excecao":
            funcionario = conn.execute(
                "SELECT nome, local_trabalho FROM funcionarios WHERE id = ?", (resultado.funcionario_id,)
            ).fetchone()
            nome = funcionario["nome"] if funcionario else (grupo.identificacao.nome_candidato or "DESCONHECIDO")
            local_pessoa = (funcionario["local_trabalho"] if funcionario else local_trabalho) or "GERAL"

            pasta_destino = pasta_saida / _slug(local_pessoa) / f"{hoje.year}-{hoje.month:02d}"
            pasta_destino.mkdir(parents=True, exist_ok=True)
            nome_arquivo = f"{resultado.funcionario_id}_{_slug(nome)}_{hoje.isoformat()}.pdf"
            caminho_final = pasta_destino / nome_arquivo
            novo_doc.save(str(caminho_final))
            novo_doc.close()

            relatorio.separados.append(
                ItemSeparado(resultado.funcionario_id, nome, str(caminho_final), grupo.indices)
            )
        else:
            pasta_pendentes.mkdir(parents=True, exist_ok=True)
            nome_pendente = f"pendente_{nome_arquivo_origem}_{'-'.join(map(str, grupo.indices))}.pdf"
            caminho_pendente = pasta_pendentes / nome_pendente
            novo_doc.save(str(caminho_pendente))
            novo_doc.close()

            candidatos_json = json.dumps([c.__dict__ for c in resultado.candidatos], ensure_ascii=False)
            motivo = "Sem texto extraível (possível PDF escaneado sem OCR disponível)" if grupo.metodo_extracao == "falhou" else "Não identificado com confiança na base mestre"

            cur = conn.execute(
                """
                INSERT INTO excecoes_pdf
                    (arquivo_origem, paginas, texto_extraido, metodo_extracao, candidatos_json,
                     caminho_pdf_pendente, status, criado_em)
                VALUES (?, ?, ?, ?, ?, ?, 'pendente', ?)
                """,
                (
                    nome_arquivo_origem,
                    json.dumps(grupo.indices),
                    grupo.texto_completo[:5000],
                    grupo.metodo_extracao,
                    candidatos_json,
                    str(caminho_pendente),
                    agora,
                ),
            )
            relatorio.pendentes.append(
                ItemPendente(cur.lastrowid, grupo.indices, motivo, str(caminho_pendente))
            )

    conn.commit()
    doc.close()
    return relatorio


def resolver_excecao_pdf(
    conn: Connection,
    excecao_id: int,
    funcionario_id: str,
    confirmado_por: str = "usuario_local",
    pasta_saida: Path = PASTA_SAIDA_PADRAO,
) -> Path:
    """Move o PDF pendente para a pasta final, renomeado no padrão da empresa,
    após confirmação manual de quem é o funcionário."""
    exc = conn.execute("SELECT * FROM excecoes_pdf WHERE id = ?", (excecao_id,)).fetchone()
    if exc is None:
        raise ValueError(f"Exceção de PDF {excecao_id} não encontrada.")

    funcionario = conn.execute(
        "SELECT nome, local_trabalho FROM funcionarios WHERE id = ?", (funcionario_id,)
    ).fetchone()
    if funcionario is None:
        raise ValueError(f"Funcionário {funcionario_id} não encontrado na base mestre.")

    hoje = date.today()
    local_pessoa = funcionario["local_trabalho"] or "GERAL"
    pasta_destino = pasta_saida / _slug(local_pessoa) / f"{hoje.year}-{hoje.month:02d}"
    pasta_destino.mkdir(parents=True, exist_ok=True)
    nome_arquivo = f"{funcionario_id}_{_slug(funcionario['nome'])}_{hoje.isoformat()}.pdf"
    caminho_final = pasta_destino / nome_arquivo

    Path(exc["caminho_pdf_pendente"]).replace(caminho_final)

    conn.execute(
        """
        UPDATE excecoes_pdf
        SET status = 'resolvido', funcionario_id_resolvido = ?, confirmado_por = ?, resolvido_em = ?
        WHERE id = ?
        """,
        (funcionario_id, confirmado_por, datetime.now().isoformat(timespec="seconds"), excecao_id),
    )
    conn.commit()
    return caminho_final
