from app.core.config import Settings


def test_railway_local_urls_accept_bare_internal_hostnames():
    settings = Settings(
        _env_file=None,
        ollama_base_url=(
            "ollama-7c414367-1ecc-440a-99b9-5125eb1185e9."
            "railway.internal:11434"
        ),
        localai_base_url="localai.railway.internal",
        localai_model="",
    )

    assert settings.ollama_base_url == (
        "http://ollama-7c414367-1ecc-440a-99b9-5125eb1185e9."
        "railway.internal:11434"
    )
    assert settings.localai_base_url == "http://localai.railway.internal:8080"
    assert settings.localai_v1_base_url == (
        "http://localai.railway.internal:8080/v1"
    )
    assert "localai" in settings.active_llms


def test_localai_v1_path_is_not_duplicated():
    settings = Settings(
        _env_file=None,
        localai_base_url="https://localai.example.com/v1/",
    )

    assert settings.localai_v1_base_url == "https://localai.example.com/v1"


def test_groq_key_selects_the_groq_model_instead_of_the_xai_model():
    settings = Settings(
        _env_file=None,
        GROQ_API_KEY="gsk_test",
        groq_model="llama-3.1-8b-instant",
        grok_model="grok-3",
    )

    assert settings.uses_groq_cloud is True
    assert settings.active_grok_model == "llama-3.1-8b-instant"
    assert settings.grok_chat_base_url == "https://api.groq.com/openai/v1"


def test_ollama_sem_endereco_nao_entra_na_lista_de_provedores():
    # Ambiente sem Ollama desliga o provedor deixando OLLAMA_BASE_URL vazia. O
    # roteamento continuava oferecendo "llama", escolhia ele e a chamada morria
    # em "Request URL is missing an 'http://' or 'https://' protocol" - erro de
    # biblioteca, que nao diz ao professor o que configurar.
    settings = Settings(_env_file=None, ollama_base_url="", claude_api_key="k")

    assert settings.active_llms == ["claude"]


def test_ollama_configurado_continua_disponivel():
    settings = Settings(_env_file=None, ollama_base_url="localhost:11434")

    assert settings.ollama_base_url == "http://localhost:11434"
    assert "llama" in settings.active_llms
