"""Executa manualmente o mesmo seed de demonstração usado pelo startup."""

import argparse
import asyncio

from app.core.database import AsyncSessionLocal, engine, init_db
from app.core.database_seed import apply_database_seed
from app.core.demo_seed import SEED_NAME, reset_demo_data


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed de demonstração do backend.")
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Remove somente os dados identificados como demo antes de recriá-los.",
    )
    return parser.parse_args()


async def main(reset: bool = False) -> None:
    await init_db()
    try:
        if reset:
            async with AsyncSessionLocal() as db:
                await reset_demo_data(db)
                await db.commit()

        applied = await apply_database_seed(SEED_NAME)
        if applied:
            print("\n✅ Seed concluído!\n")
        else:
            print(f"\n· Seed {SEED_NAME} já aplicado; nenhuma alteração necessária.\n")
    finally:
        await engine.dispose()


if __name__ == "__main__":
    args = _parse_args()
    asyncio.run(main(reset=args.reset))
