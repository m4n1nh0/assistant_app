"""Orquestra seeds opcionais e versionados durante o startup."""

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy.exc import IntegrityError

from .database import AsyncSessionLocal, ConfigModel
from .demo_seed import SEED_MARKER_KEY, SEED_NAME, seed_demo_data

_DISABLED_VALUES = {"", "0", "false", "none", "off"}


def normalize_seed_name(requested_seed: str | None) -> str:
    """Normaliza o nome do seed pedido, tratando os valores que significam desligado."""
    return (requested_seed or "").strip().lower()


def database_seed_requested(requested_seed: str | None) -> bool:
    """Diz se `DATABASE_SEED` pede de fato a aplicacao de um seed."""
    return normalize_seed_name(requested_seed) not in _DISABLED_VALUES


async def apply_database_seed(
    requested_seed: str | None,
    session_factory: Any = None,
) -> bool:
    """
    Aplica o seed solicitado uma única vez.

    Retorna True quando os dados foram inseridos e False quando o seed está
    desabilitado ou já havia sido aplicado.
    """
    seed_name = normalize_seed_name(requested_seed)
    if not database_seed_requested(seed_name):
        return False
    if seed_name != SEED_NAME:
        raise ValueError(
            f"DATABASE_SEED inválido: {requested_seed!r}. "
            f"Valor suportado: {SEED_NAME!r}."
        )

    factory = session_factory or AsyncSessionLocal
    async with factory() as db:
        marker = await db.get(ConfigModel, SEED_MARKER_KEY)
        if marker is not None:
            return False

        try:
            await seed_demo_data(db)
            db.add(ConfigModel(
                key=SEED_MARKER_KEY,
                value=json.dumps({
                    "seed": SEED_NAME,
                    "applied_at": datetime.now(timezone.utc).isoformat(),
                }),
            ))
            await db.commit()
        except IntegrityError:
            await db.rollback()
            # Outra réplica pode ter concluído o mesmo seed enquanto esta
            # transação estava em andamento.
            marker = await db.get(ConfigModel, SEED_MARKER_KEY)
            if marker is None:
                raise
            return False
        except Exception:
            await db.rollback()
            raise

    return True
