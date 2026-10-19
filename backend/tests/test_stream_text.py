from app.services.stream_text import text_chunks


def test_chunks_rejoin_to_the_exact_text():
    text = "Primeira linha com varias palavras.\n\nSegunda linha,   com espacos  extras e acentuação: ção."
    assert "".join(text_chunks(text, size=16)) == text


def test_chunks_respect_the_size_and_cut_between_words():
    chunks = list(text_chunks("um dois tres quatro cinco seis sete", size=12))
    assert all(len(chunk) <= 12 for chunk in chunks)
    assert all(not chunk.startswith(" ") or chunk.strip() == "" for chunk in chunks)
    assert len(chunks) > 1


def test_a_word_longer_than_the_size_stays_whole():
    chunks = list(text_chunks("supercalifragilistico curta", size=5))
    assert chunks[0].startswith("supercalifragilistico")


def test_empty_text_yields_nothing():
    assert list(text_chunks("")) == []
    assert list(text_chunks(None)) == []
