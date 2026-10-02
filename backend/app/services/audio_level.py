"""Nivel do audio gravado, para dizer por que um bloco voltou sem fala.

"Nenhuma fala reconhecida" cobre casos que pedem providencias opostas: o microfone
que captou so silencio (mudo, dispositivo errado, fone Bluetooth que caiu) e o audio
com som que o reconhecimento nao entendeu (fala distante, baixa, sala com eco). Sem
medir o sinal, o professor recebe a mesma frase nos dois e nao sabe o que mexer.

O nivel so explica: quem decide se ha fala e o reconhecimento. Microfone de notebook
numa sala quieta mede pico de 0.0025 so de ruido de fundo, entao uma palestra falada
longe dele fica a poucas vezes disso - descartar o bloco por nivel jogaria fora fala
que o Whisper entende.
"""

from __future__ import annotations

import io
import sys
import wave
from array import array
from typing import Optional

#: Pico abaixo disso (fracao do maximo de 16 bits, ~ -60 dBFS) e dispositivo sem
#: sinal: mudo, desconectado ou capturando zeros. Ruido de fundo de uma sala quieta
#: ja passa de duas vezes esse valor.
SILENCE_PEAK = 0.001

#: Pico abaixo disso e voz que o reconhecimento tende a perder: longe do microfone
#: ou com o ganho de entrada baixo.
LOW_PEAK = 0.03

NO_SPEECH = "nenhuma fala reconhecida no bloco."


def wav_peak(data: bytes) -> Optional[float]:
    """Maior amplitude do WAV de 16 bits, de 0.0 a 1.0.

    `None` quando o formato nao e esse (o app grava m4a so se o WAV nao existir):
    sem medida, nada e afirmado sobre o nivel.
    """
    try:
        with wave.open(io.BytesIO(data), "rb") as arquivo:
            if arquivo.getsampwidth() != 2:
                return None
            frames = arquivo.readframes(arquivo.getnframes())
    except (wave.Error, EOFError):
        return None

    amostras = array("h")
    amostras.frombytes(frames[: len(frames) - len(frames) % 2])
    if not amostras:
        return 0.0
    # O arquivo esta em little-endian; array usa a ordem da maquina.
    if sys.byteorder == "big":
        amostras.byteswap()
    return max(max(amostras), -min(amostras)) / 32768.0


def no_speech_reason(peak: Optional[float]) -> str:
    """Texto para o bloco que o reconhecimento devolveu sem fala nenhuma."""
    if peak is None or peak >= LOW_PEAK:
        return NO_SPEECH
    if peak < SILENCE_PEAK:
        return (
            "o microfone captou so silencio neste bloco. Confira se ele nao "
            "esta no mudo e se e o microfone certo em Configuracoes > Sistema"
        )
    return (
        f"{NO_SPEECH} O som chegou muito baixo: aproxime o microfone de quem "
        "fala ou aumente o volume de entrada no Windows."
    )
