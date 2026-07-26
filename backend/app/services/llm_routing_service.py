"""Picks a default LLM for chat requests that don't specify one.

Priority: free/local providers first, then paid providers with confirmed
remaining credit, then paid providers with no balance signal. Providers
known to be out of credit never reach here (llm_status_service already
excludes them from "available").
"""

from .llm_status_service import get_llm_statuses

FREE_LOCAL_LLMS = {"llama", "localai"}


def _tier(provider: str, balance_ok: bool | None) -> int:
    if provider in FREE_LOCAL_LLMS:
        return 0
    if balance_ok is True:
        return 1
    if balance_ok is None:
        return 2
    return 3


async def pick_auto_llm(candidates: list[str]) -> str:
    if not candidates:
        return ""
    statuses = await get_llm_statuses()
    ranked = sorted(
        candidates,
        key=lambda provider: (
            _tier(provider, statuses[provider].balance_ok if provider in statuses else None),
            candidates.index(provider),
        ),
    )
    return ranked[0]
