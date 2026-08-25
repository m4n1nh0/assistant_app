"""Shared backend-only Microsoft application and account credential boundary."""

from ..core.config import get_settings
from .credential_storage_service import CredentialDecryptionError, decrypt_credential


def microsoft_application_config() -> dict[str, str]:
    """Credenciais do App Registration Microsoft, que pertencem ao deploy.

    E uma aplicacao multitenant unica do produto, nao uma por organizacao de usuario.
    O segredo fica no ambiente do backend e nunca vai para a interface.
    """
    settings = get_settings()
    return {
        "client_id": settings.microsoft_oauth_client_id,
        "client_secret": settings.microsoft_oauth_client_secret,
        "tenant_id": settings.microsoft_oauth_tenant_id or "common",
    }


def hydrate_microsoft_account(stored: dict) -> dict:
    """Returns an in-memory Graph account without mutating persisted data."""
    account = dict(stored)
    try:
        account["refresh_token"] = decrypt_credential(
            str(account.get("refresh_token") or "")
        )
        account["pkce_verifier"] = decrypt_credential(
            str(account.get("pkce_verifier") or "")
        )
    except CredentialDecryptionError:
        account["refresh_token"] = ""
        account["connection_status"] = "reconnect_required"
    account.update(microsoft_application_config())
    return account
