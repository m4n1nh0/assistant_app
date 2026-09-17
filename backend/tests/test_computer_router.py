"""Rotas de computador com o backend fora da maquina do usuario.

Com o backend na nuvem, toda requisicao chega de um IP remoto. Salvar script e
guardar texto do usuario no banco - nao pode depender de estar na mesma
maquina. Ja o catalogo e a execucao de acoes dependem do sistema de quem roda o
backend, e continuam so locais.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import ScriptSnippetModel, get_db
from app.core.security import get_current_user
from app.routers import computer

pytestmark = pytest.mark.integration

USER = {"uid": "u1", "tutor_id": "t1"}


@pytest.fixture
def client():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    async def create():
        async with engine.begin() as conn:
            await conn.run_sync(ScriptSnippetModel.__table__.create)

    asyncio.run(create())
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def db():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(computer.router)
    app.dependency_overrides[get_db] = db
    app.dependency_overrides[get_current_user] = lambda: USER
    # TestClient se apresenta como "testclient": para a rota, um cliente remoto.
    with TestClient(app) as test_client:
        yield test_client
    asyncio.run(engine.dispose())


def test_remote_client_saves_lists_edits_and_deletes_scripts(client):
    created = client.post(
        "/computer/scripts",
        json={"name": "Limpeza", "shell": "powershell", "script": "Get-Process"},
    )
    assert created.status_code == 201, created.text
    script_id = created.json()["id"]
    assert created.json()["tutor_id"] == "t1"

    listed = client.get("/computer/scripts")
    assert [item["name"] for item in listed.json()] == ["Limpeza"]

    edited = client.patch(f"/computer/scripts/{script_id}", json={"name": "Processos"})
    assert edited.status_code == 200 and edited.json()["name"] == "Processos"

    assert client.delete(f"/computer/scripts/{script_id}").status_code == 204
    assert client.get("/computer/scripts").json() == []


def test_remote_client_reads_the_accepted_shells(client):
    assert client.get("/computer/scripts/shells").status_code == 200


@pytest.mark.parametrize(
    "method,path",
    [
        ("get", "/computer/actions"),
        ("post", "/computer/scripts/run"),
    ],
)
def test_actions_that_depend_on_the_backend_machine_stay_local(client, method, path):
    assert getattr(client, method)(path).status_code == 403


def test_forged_forwarded_for_header_does_not_make_a_client_local(client):
    response = client.get(
        "/computer/actions", headers={"X-Forwarded-For": "127.0.0.1"}
    )

    assert response.status_code == 403
