"""Encryption envelope for credentials that must be persisted by the backend."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from ..core.config import get_settings

_PREFIX = "enc:v1:"


class CredentialDecryptionError(RuntimeError):
    """Nao foi possivel decifrar a credencial guardada.

    Quase sempre significa que `CREDENTIAL_ENCRYPTION_KEY` mudou: as credenciais
    antigas viram ilegiveis e as contas precisam ser reconectadas.
    """
    pass


def _fernet() -> Fernet:
    settings = get_settings()
    material = settings.credential_encryption_key or settings.jwt_secret
    key = base64.urlsafe_b64encode(hashlib.sha256(material.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_credential(value: str) -> str:
    """Cifra um segredo para persistir no banco.

    Args:
        value: segredo em claro.

    Returns:
        O texto cifrado, unico valor que chega a tocar o banco.
    """
    if not value:
        return ""
    token = _fernet().encrypt(value.encode("utf-8")).decode("ascii")
    return f"{_PREFIX}{token}"


def decrypt_credential(value: str) -> str:
    """Decifra um segredo lido do banco.

    Raises:
        CredentialDecryptionError: quando a chave de cifra nao corresponde.
    """
    if not value or not value.startswith(_PREFIX):
        # Backward-compatible read for tokens created before encrypted storage.
        return value
    try:
        return _fernet().decrypt(value[len(_PREFIX):].encode("ascii")).decode("utf-8")
    except (InvalidToken, ValueError) as exc:
        raise CredentialDecryptionError(
            "A credencial armazenada nao pode ser decifrada; reconecte a conta."
        ) from exc
