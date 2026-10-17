"""Reescrita do material por IA: o texto extraido vira Markdown limpo e bem dividido.

A extracao de PDF, DOCX e PPTX devolve o que o arquivo tem, nao o que o aluno precisa ler:
palavra por linha, rodape repetido em todo slide, titulo sem marca. Heuristica resolve
parte disso; a IA resolve o resto, e por isso a melhoria e pedida pelo professor, com a IA
que ele escolher.

Dois caminhos, como no resumo de aula:

- **Provedor do backend** (`improve`): o servidor fatia o texto, manda cada parte ao modelo
  e junta o resultado.
- **Agente conectado** (`build_prompt`): Codex ou Claude Code rodam na maquina do professor
  e leem o material inteiro de uma vez. O backend so entrega o prompt, e o texto volta por
  `/improve/external`.

A reescrita **nao pode resumir nem inventar**. O prompt proibe, e `looks_faithful` confere o
tamanho: saida muito menor que a entrada e resumo, muito maior e invencao, e nos dois casos
o resultado e recusado em vez de gravado por cima do material.

A saida e so Markdown simples (titulos com `#`, listas com `-`, negrito): e o que o portal
do aluno e o cortador de blocos sabem ler.
"""

from __future__ import annotations

import re
from typing import Any

from loguru import logger

from .education_service import resolve_llm
from .llm_service import dispatch_single

#: Tamanho de cada parte mandada a um provedor do backend. Cabe na janela dos modelos
#: menores e deixa folga para a resposta, que tem o tamanho da entrada.
PART_CHARS = 9_000

#: Faixa aceita entre o tamanho da saida e o da entrada. Fora dela o modelo resumiu ou
#: inventou, e o texto nao pode substituir o original.
MIN_RATIO = 0.45
MAX_RATIO = 1.6

#: Teto de saida por parte (tokens). O texto reescrito tem o tamanho do original.
MAX_TOKENS = 6_000

SYSTEM_PROMPT = """Voce organiza o texto extraido de um material didatico (apostila, slides, \
capitulo) para que um aluno leia com facilidade.

O texto veio de uma extracao automatica e pode ter: palavras quebradas em linhas soltas, \
hifenizacao no fim da linha, cabecalho e rodape repetidos em toda pagina ou slide, numero de \
slide, titulos sem nenhuma marca.

Faca:
- reconstrua os paragrafos (junte linhas que pertencem a mesma frase);
- identifique titulos e subtitulos e marque-os;
- transforme enumeracoes em listas;
- apague o ruido de extracao: cabecalho/rodape repetido, numero de pagina ou de slide;
- em apresentacao, use um titulo por slide.

Nao faca:
- nao resuma, nao encurte, nao comente e nao explique;
- nao invente informacao nem complete o que estiver faltando;
- nao traduza e nao mude o sentido nem a ordem do conteudo.

Responda SOMENTE com o texto organizado, em Markdown simples:
- titulos com "## " e subtitulos com "### ";
- listas com "- ";
- negrito com **texto** so para termos-chave;
- paragrafos separados por uma linha em branco.
Nada de tabelas, blocos de codigo, HTML, imagens ou cercas de codigo. Uma tabela vira lista \
(uma linha por registro)."""


class ImproveError(Exception):
    """A reescrita falhou ou voltou fora do que se espera de uma reescrita fiel."""


def split_parts(text: str, limit: int = PART_CHARS) -> list[str]:
    """Parte o texto em trechos de ate `limit` caracteres, sempre entre paragrafos."""
    parts: list[str] = []
    current = ""
    for paragraph in re.split(r"\n\s*\n", text.strip()):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        # Paragrafo maior que o limite (texto sem quebra): corta em frases, ou no limite.
        pieces = [paragraph]
        if len(paragraph) > limit:
            pieces = re.split(r"(?<=[.!?])\s+", paragraph)
            pieces = [p[i:i + limit] for p in pieces for i in range(0, len(p), limit)]
        for piece in pieces:
            if current and len(current) + len(piece) + 2 > limit:
                parts.append(current)
                current = piece
            else:
                current = f"{current}\n\n{piece}" if current else piece
    if current:
        parts.append(current)
    return parts


def clean_output(raw: str) -> str:
    """Tira cerca de codigo e conversa que o modelo poe em volta da resposta."""
    text = (raw or "").strip()
    fence = re.match(r"^```[a-zA-Z]*\n(.*?)\n?```$", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    return text


def looks_faithful(original: str, rewritten: str) -> bool:
    """O tamanho da saida esta na faixa de uma reescrita (nao resumo, nao invencao)."""
    size = len(original.strip())
    if size == 0:
        return False
    ratio = len(rewritten.strip()) / size
    return MIN_RATIO <= ratio <= MAX_RATIO


def build_prompt(*, title: str, discipline: str, content: str, instructions: str = "") -> dict[str, Any]:
    """Prompt completo, o mesmo para o backend e para um agente conectado."""
    header = f'Material: "{title}"'
    if discipline:
        header += f" (disciplina: {discipline})"
    extra = f"\n\nPedido do professor: {instructions.strip()}" if instructions.strip() else ""
    prompt = f"{header}{extra}\n\nTexto extraido:\n\n{content.strip()}"
    return {"system_prompt": SYSTEM_PROMPT, "prompt": prompt, "chars": len(content)}


async def improve(
    *,
    title: str,
    discipline: str,
    content: str,
    llm: str | None = None,
    instructions: str = "",
) -> dict[str, str]:
    """Reescreve o material com um provedor do backend. Devolve `{content, llm}`.

    Raises:
        ImproveError: provedor indisponivel, resposta de erro, ou saida que nao parece uma
            reescrita fiel de alguma das partes.
    """
    provider = await resolve_llm(llm)
    if not provider:
        raise ImproveError("Nenhum provedor de IA configurado.")

    parts = split_parts(content)
    if not parts:
        raise ImproveError("O material esta vazio.")

    rewritten: list[str] = []
    for number, part in enumerate(parts, start=1):
        where = f" (trecho {number} de {len(parts)})" if len(parts) > 1 else ""
        built = build_prompt(
            title=title + where, discipline=discipline, content=part, instructions=instructions)
        response = await dispatch_single(
            provider,
            built["prompt"],
            [],
            built["system_prompt"],
            max_tokens=MAX_TOKENS,
            reasoning_effort="none" if provider == "localai" else None,
        )
        if response.is_error:
            logger.warning(f"Melhoria de material falhou ({provider}): {response.content}")
            raise ImproveError(f"{provider} nao respondeu: {response.content}")
        text = clean_output(response.content)
        if not looks_faithful(part, text):
            raise ImproveError(
                f"A resposta de {provider} nao parece uma reescrita fiel (resumiu ou inventou). "
                "Tente outra IA.")
        rewritten.append(text)

    return {"content": "\n\n".join(rewritten), "llm": provider}
