from app.services.desktop_window_service import (
    DesktopWindow,
    build_context_prompt,
    normalize_context_text,
)


def test_normalize_context_text_deduplicates_and_limits():
    text = "  main.py  \nmain.py\n\n  def app():   pass  \nsecond line"

    normalized = normalize_context_text(text, max_chars=100)

    assert normalized == "main.py\ndef app(): pass\nsecond line"

    limited = normalize_context_text(text, max_chars=30)
    assert limited.endswith("...[contexto truncado]")
    assert len(limited) <= 30


def test_build_context_prompt_uses_window_metadata_and_accessible_text():
    window = DesktopWindow(
        id="100",
        handle=100,
        title="main.py - assistant_app",
        process_id=42,
        process_name="Code.exe",
        executable_path=r"C:\Users\dev\AppData\Local\Programs\Code.exe",
    )

    prompt = build_context_prompt(
        window=window,
        text="class App:\n  pass",
        extraction_method="uia",
    )

    assert "Contexto da janela escolhida pelo usuario." in prompt
    assert "Titulo: main.py - assistant_app" in prompt
    assert "Processo: Code.exe (PID 42)" in prompt
    assert "Metodo de leitura: uia" in prompt
    assert "class App:" in prompt
