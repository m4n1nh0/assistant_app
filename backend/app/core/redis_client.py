"""Accessor for the shared Redis connection created in main.py's lifespan.

Other modules (e.g. llm_status_service) read from here instead of opening
their own connection. Stays None if Redis was never configured/reachable —
callers must treat that as "no cache available", not an error.
"""

_client = None


def set_client(client) -> None:
    global _client
    _client = client


def get_client():
    return _client
