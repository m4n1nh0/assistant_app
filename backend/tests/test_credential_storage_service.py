from app.services.credential_storage_service import (
    decrypt_credential,
    encrypt_credential,
)
from app.services.microsoft_identity_service import hydrate_microsoft_account


def test_oauth_credential_is_encrypted_at_rest():
    stored = encrypt_credential("microsoft-refresh-token")

    assert stored.startswith("enc:v1:")
    assert "microsoft-refresh-token" not in stored
    assert decrypt_credential(stored) == "microsoft-refresh-token"


def test_legacy_plaintext_token_can_be_read_for_reconnection_migration():
    assert decrypt_credential("legacy-token") == "legacy-token"


def test_microsoft_account_is_hydrated_only_in_backend_memory(monkeypatch):
    from app.services import microsoft_identity_service

    monkeypatch.setattr(
        microsoft_identity_service,
        "microsoft_application_config",
        lambda: {
            "client_id": "central-client",
            "client_secret": "central-secret",
            "tenant_id": "common",
        },
    )
    stored = {
        "id": "microsoft-1",
        "refresh_token": encrypt_credential("refresh-token"),
    }

    hydrated = hydrate_microsoft_account(stored)

    assert hydrated["refresh_token"] == "refresh-token"
    assert hydrated["client_id"] == "central-client"
    assert stored["refresh_token"].startswith("enc:v1:")
    assert "client_secret" not in stored
