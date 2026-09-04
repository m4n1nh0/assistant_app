"""Per-user configuration and request context for external LLM providers.

LocalAI and Ollama are infrastructure owned by the application. API keys for
cloud providers belong to a tutor and are decrypted only for the duration of
that tutor's request.
"""

from contextvars import ContextVar, Token
from dataclasses import dataclass
from typing import Any, AsyncIterator

from fastapi import Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..core.config import get_settings
from ..core.database import ConfigModel, CredentialModel, AsyncSessionLocal, UserModel
from ..core.security import get_current_user
from .credential_storage_service import decrypt_credential, encrypt_credential


LOCAL_PROVIDERS = ("localai", "llama")
PROVIDER_ORDER = (
    "claude", "gpt", "together", "openrouter", "deepseek", "gemini",
    "grok", "hf",
)

PROVIDER_SPECS: dict[str, dict[str, str]] = {
    "claude": {"label": "Claude", "key_attr": "claude_api_key", "model": "claude-sonnet-4-6"},
    "gpt": {"label": "OpenAI", "key_attr": "openai_api_key", "model": "gpt-4o"},
    "together": {"label": "Together", "key_attr": "together_api_key", "model_attr": "together_model"},
    "openrouter": {"label": "OpenRouter", "key_attr": "openrouter_api_key", "model_attr": "openrouter_model"},
    "deepseek": {"label": "DeepSeek", "key_attr": "deepseek_api_key", "model_attr": "deepseek_model"},
    "gemini": {"label": "Gemini", "key_attr": "gemini_api_key", "model": "gemini-1.5-flash"},
    "grok": {"label": "Grok / Groq", "key_attr": "grok_api_key", "model_attr": "grok_model"},
    "hf": {"label": "Hugging Face", "key_attr": "huggingface_api_key", "model_attr": "huggingface_model"},
}


def clean_api_key(value: Any, *, strict: bool = True) -> str:
    """Normaliza a chave colada e recusa o que nao cabe num header HTTP.

    Chave de API nunca tem espaco no meio, mas colagem quebrada por largura de
    campo tem - e uma quebra de linha ali nao e erro visivel: `.strip()` nao
    alcanca o meio da string, a chave e salva, e a falha so aparece muito
    depois, como `Illegal header value` vindo do httpx no health check. Pior:
    essa mensagem carrega a chave inteira. Recusar aqui troca um vazamento por
    um erro de formulario.

    Args:
        value: o que veio do formulario ou do ambiente.
        strict: `True` levanta `ValueError` em caractere invalido, para a rota
            devolver 422; `False` descarta a chave, para a migracao de
            ambiente nao derrubar o login por causa de uma variavel suja.

    Returns:
        A chave sem espaco algum, ou "" quando nao havia chave.

    Raises:
        ValueError: em modo estrito, quando sobra caractere que nao pode ir em
            header HTTP.
    """
    raw = str(value or "")
    key = "".join(raw.split())
    if not key:
        return ""
    # Header HTTP so aceita ASCII imprimivel. Aspas curvas e espaco
    # nao-quebravel vindos de pagina web caem aqui, e sao invisiveis no campo.
    invalid = {char for char in key if not (0x20 < ord(char) < 0x7F)}
    if invalid:
        if not strict:
            return ""
        amostra = ", ".join(sorted(f"U+{ord(c):04X}" for c in invalid)[:4])
        raise ValueError(
            "A chave contém caractere que não pode ser enviado em cabeçalho "
            f"HTTP ({amostra}). Copie a chave direto do painel do provedor, "
            "sem formatação."
        )
    return key


def _default_model(provider: str) -> str:
    spec = PROVIDER_SPECS[provider]
    if spec.get("model"):
        return spec["model"]
    return str(getattr(get_settings(), spec["model_attr"], ""))


@dataclass(frozen=True)
class UserLLMRuntime:
    """Contexto de provedores de um usuario, valido durante uma requisicao.

    Carrega as chaves ja decifradas e os modelos preferidos daquele usuario. Vive em
    `ContextVar`, entao codigo assincrono concorrente de contas diferentes nao
    mistura credencial.
    """
    scope: str
    providers: dict[str, dict[str, Any]]


_runtime: ContextVar[UserLLMRuntime | None] = ContextVar(
    "user_llm_runtime", default=None
)


def runtime_scope() -> str:
    """Chave de escopo do usuario ativo, usada para separar caches por conta."""
    current = _runtime.get()
    return current.scope if current else "local"


def activate_user_llms(runtime: UserLLMRuntime) -> Token:
    """Ativa o contexto de provedores de um usuario.

    Args:
        runtime: contexto carregado por `load_user_llm_runtime`.

    Returns:
        O token que `reset_user_llms` usa para restaurar o contexto anterior.
    """
    return _runtime.set(runtime)


def reset_user_llms(token: Token) -> None:
    """Restaura o contexto de provedores anterior ao `activate_user_llms`."""
    _runtime.reset(token)


class RuntimeSettingsProxy:
    """Settings facade that masks global cloud keys outside a user context."""

    def __getattr__(self, name: str) -> Any:
        base = get_settings()
        current = _runtime.get()
        for provider, spec in PROVIDER_SPECS.items():
            if name == spec["key_attr"]:
                return str((current.providers.get(provider, {}) if current else {}).get("api_key", ""))

        model_attrs = {
            "claude_model": "claude",
            "openai_model": "gpt",
            "gemini_model": "gemini",
            "together_model": "together",
            "openrouter_model": "openrouter",
            "deepseek_model": "deepseek",
            "grok_model": "grok",
            "groq_model": "grok",
            "huggingface_model": "hf",
        }
        if name in model_attrs:
            provider = model_attrs[name]
            configured = current.providers.get(provider, {}) if current else {}
            return str(configured.get("model") or _default_model(provider))
        return getattr(base, name)

    @property
    def active_llms(self) -> list[str]:
        """Provedores disponiveis para o usuario ativo."""
        base = get_settings()
        current = _runtime.get()
        cloud = [] if current is None else [
            provider for provider in PROVIDER_ORDER
            if current.providers.get(provider, {}).get("enabled")
            and current.providers.get(provider, {}).get("api_key")
        ]
        if base.localai_base_url:
            cloud.append("localai")
        cloud.append("llama")
        return cloud

    @property
    def uses_groq_cloud(self) -> bool:
        """Diz se a chave do usuario ativo e da Groq, e nao do Grok."""
        return self.grok_api_key.strip().startswith("gsk_")

    @property
    def grok_chat_base_url(self) -> str:
        """Endpoint de chat do provedor efetivo do usuario ativo."""
        return "https://api.groq.com/openai/v1" if self.uses_groq_cloud else "https://api.x.ai/v1"

    @property
    def active_grok_model(self) -> str:
        """Modelo efetivo conforme a chave do usuario ativo."""
        return self.grok_model

    @property
    def llm_labels(self) -> dict[str, str]:
        """Rotulos de exibicao dos provedores do usuario ativo."""
        labels = {
            provider: f"{spec['label']} ({getattr(self, _model_property(provider))})"
            for provider, spec in PROVIDER_SPECS.items()
        }
        base = get_settings()
        labels["localai"] = base.llm_labels["localai"]
        labels["llama"] = base.llm_labels["llama"]
        return labels


def _model_property(provider: str) -> str:
    return {
        "claude": "claude_model", "gpt": "openai_model",
        "gemini": "gemini_model", "hf": "huggingface_model",
    }.get(provider, f"{provider}_model")


runtime_settings = RuntimeSettingsProxy()


async def load_user_llm_runtime(tutor_id: str) -> UserLLMRuntime:
    """Monta o contexto de provedores de um usuario a partir do banco.

    Decifra as credenciais do usuario e junta com a infraestrutura local (LocalAI e
    Ollama), que pertence a instalacao e nao a conta.

    Args:
        tutor_id: perfil de dados dono das credenciais.

    Returns:
        O contexto pronto para ser ativado.
    """
    providers: dict[str, dict[str, Any]] = {}
    async with AsyncSessionLocal() as db:
        rows = (
            await db.execute(
                select(CredentialModel).where(
                    CredentialModel.tutor_id == tutor_id,
                    CredentialModel.provider.in_(PROVIDER_ORDER),
                )
            )
        ).scalars().all()
    for row in rows:
        if row.provider in providers:
            continue
        metadata = row.metadata_ if isinstance(row.metadata_, dict) else {}
        providers[row.provider] = {
            "api_key": decrypt_credential(row.secret_ref),
            "model": str(metadata.get("model") or _default_model(row.provider)),
            "enabled": bool(row.enabled),
        }
    return UserLLMRuntime(scope=f"tutor:{tutor_id}", providers=providers)


async def user_llm_context(
    user: dict = Depends(get_current_user),
) -> AsyncIterator[None]:
    """Dependencia de rota que ativa o contexto do usuario e o desfaz no fim.

    Yields:
        O `UserLLMRuntime` ativo durante a requisicao.
    """
    await migrate_legacy_environment_for_user(user)
    token = activate_user_llms(await load_user_llm_runtime(user["tutor_id"]))
    try:
        yield
    finally:
        reset_user_llms(token)


async def list_provider_config(tutor_id: str) -> list[dict[str, Any]]:
    """Lista a configuracao de provedores de um usuario para a interface.

    Returns:
        Um item por provedor, com modelo e se ha chave salva - nunca a chave em si.
    """
    runtime = await load_user_llm_runtime(tutor_id)
    result = []
    for provider in PROVIDER_ORDER:
        item = runtime.providers.get(provider, {})
        result.append({
            "id": provider,
            "label": PROVIDER_SPECS[provider]["label"],
            "kind": "external",
            "enabled": bool(item.get("enabled")),
            "configured": bool(item.get("api_key")),
            "model": str(item.get("model") or _default_model(provider)),
        })
    base = get_settings()
    result.extend([
        {"id": "localai", "label": "LocalAI", "kind": "local", "enabled": bool(base.localai_base_url), "configured": bool(base.localai_base_url), "model": base.localai_model or "automático"},
        {"id": "llama", "label": "Ollama", "kind": "local", "enabled": True, "configured": True, "model": base.ollama_model},
    ])
    return result


async def save_provider_config(
    tutor_id: str, providers: list[dict[str, Any]], db: AsyncSession
) -> None:
    """Grava a configuracao de provedores de um usuario.

    Chave nova e cifrada antes de persistir; pedido de limpeza remove a credencial.
    O valor em claro nao volta para a interface em nenhuma hipotese.
    """
    for update in providers:
        provider = str(update.get("id") or "").strip().lower()
        if provider not in PROVIDER_SPECS:
            raise ValueError(f"Provedor externo inválido: {provider}")
        rows = (
            await db.execute(
                select(CredentialModel).where(
                    CredentialModel.tutor_id == tutor_id,
                    CredentialModel.provider == provider,
                )
            )
        ).scalars().all()
        row = rows[0] if rows else None
        for duplicate in rows[1:]:
            await db.delete(duplicate)
        if update.get("clear_api_key") is True:
            if row is not None:
                await db.delete(row)
            continue
        api_key = clean_api_key(update.get("api_key"))
        if row is None:
            if not api_key:
                continue
            row = CredentialModel(
                tutor_id=tutor_id,
                provider=provider,
                secret_ref=encrypt_credential(api_key),
            )
            db.add(row)
        elif api_key:
            row.secret_ref = encrypt_credential(api_key)
        metadata = row.metadata_ if isinstance(row.metadata_, dict) else {}
        model = str(update.get("model") or metadata.get("model") or _default_model(provider)).strip()
        if (
            provider == "grok"
            and api_key.startswith("gsk_")
            and model in {"", get_settings().grok_model}
        ):
            model = get_settings().groq_model
        row.metadata_ = {**metadata, "model": model}
        row.enabled = bool(update.get("enabled", True))
    await db.commit()


async def migrate_legacy_environment_for_user(user: dict) -> None:
    """One-time compatibility import, restricted to the first/admin account."""
    if user.get("role") != "admin":
        return
    marker_key = f"user:{user['uid']}:llm_credentials_migrated_v1"
    async with AsyncSessionLocal() as db:
        if await db.get(ConfigModel, marker_key):
            return
        first_admin_id = await db.scalar(
            select(UserModel.id)
            .where(UserModel.role == "admin")
            .order_by(UserModel.created_at, UserModel.id)
            .limit(1)
        )
        if first_admin_id != user["uid"]:
            db.add(ConfigModel(key=marker_key, value="true"))
            await db.commit()
            return
        base = get_settings()
        existing = set(
            (
                await db.execute(
                    select(CredentialModel.provider).where(
                        CredentialModel.tutor_id == user["tutor_id"],
                        CredentialModel.provider.in_(PROVIDER_ORDER),
                    )
                )
            ).scalars().all()
        )
        updates = []
        for provider, spec in PROVIDER_SPECS.items():
            if provider in existing:
                continue
            # Nao estrito: variavel de ambiente suja nao pode impedir o usuario
            # de entrar - ela e simplesmente ignorada, e a chave e cadastrada
            # pela tela.
            key = clean_api_key(getattr(base, spec["key_attr"], ""), strict=False)
            if key:
                model = (
                    base.groq_model if provider == "grok" and key.startswith("gsk_")
                    else _default_model(provider)
                )
                updates.append({"id": provider, "api_key": key, "model": model, "enabled": True})
        if updates:
            await save_provider_config(user["tutor_id"], updates, db)
        db.add(ConfigModel(key=marker_key, value="true"))
        await db.commit()
