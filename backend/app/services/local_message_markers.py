"""Marcadores das mensagens que a interface monta sozinha.

A interface embrulha algumas mensagens com material que ela mesma coletou:
contexto do workspace, contexto da janela e o resultado de uma acao local que
volta para a IA analisar. Nenhuma delas e um pedido novo do usuario, e os
detectores por palavra-chave precisam ignora-las inteiras.

O caso que motivou reunir os marcadores num lugar so: o resultado do diagnostico
de rede traz `https://api.ipify.org` na saida do `ipconfig`, e o "api" ali dentro
somado ao "Analise os dados abaixo" do cabecalho fazia o detector de codigo
propor "Inspecionar workspace local" logo depois de cada diagnostico.
"""

from __future__ import annotations

import re
import unicodedata

#: Blobs de contexto que a interface anexa antes do pedido.
LOCAL_CONTEXT_MARKERS = (
    "contexto local do workspace",
    "contexto automatico do workspace",
    "contexto da janela",
    "workspace capturado pela interface",
    "snapshot local do projeto",
    "resultado da inspecao do workspace",
)

#: Resultado de acao ou script local voltando para a IA analisar.
LOCAL_RESULT_MARKERS = (
    "resultado da acao local",
    "saida da acao local",
    "resultado local coletado",
    "resultado do script local",
    "saida do script local",
)

LOCAL_MESSAGE_MARKERS = LOCAL_CONTEXT_MARKERS + LOCAL_RESULT_MARKERS


def normalize_marker_text(text: str) -> str:
    """Minusculas, sem acento e com espacos colapsados, como os detectores leem."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(
        ch for ch in decomposed if not unicodedata.combining(ch)
    )
    return re.sub(r"\s+", " ", without_accents).strip()


def has_marker(text: str, markers: tuple[str, ...]) -> bool:
    """Diz se o texto ja normalizado contem algum dos marcadores."""
    return any(marker in text for marker in markers)


def is_local_message(message: str, *, head_chars: int = 600) -> bool:
    """Diz se a mensagem e material da propria interface, nao um pedido novo.

    So o comeco e inspecionado: o marcador esta no cabecalho que a interface
    escreve, e o resto e saida coletada da maquina - que pode conter qualquer
    coisa, inclusive as palavras que os detectores procuram.
    """
    head = normalize_marker_text(message[:head_chars])
    return has_marker(head, LOCAL_MESSAGE_MARKERS)
