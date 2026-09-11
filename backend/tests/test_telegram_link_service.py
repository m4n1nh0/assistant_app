import asyncio
import json
from contextlib import asynccontextmanager

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import ConfigModel, scoped_config_key
from app.models.schemas import NotifConfig
from app.services import telegram_link_service as service
from app.services.runtime_config_service import load_notif_config, save_notif_config


@asynccontextmanager
async def database():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(ConfigModel.__table__.create)
    try:
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            yield db
    finally:
        await engine.dispose()


def telegram(monkeypatch, updates, *, webhook=""):
    async def call(token, method, **params):
        if method == "getMe":
            return {"username": "ExampleBot"}
        if method == "getWebhookInfo":
            return {"url": webhook}
        assert method == "getUpdates"
        assert params == {"timeout": 0, "limit": 100}
        return updates
    monkeypatch.setattr(service, "_call", call)


def test_link_matches_private_challenge_and_saves_only_owners_telegram(monkeypatch):
    updates = []
    telegram(monkeypatch, updates)

    async def scenario():
        async with database() as db:
            await save_notif_config(db, NotifConfig(wa_number="123", reminder_minutes=45), user_id="owner")
            link = await service.begin_link(db, "owner", "123:secret")
            code = link["url"].split("?start=")[1]
            assert 20 <= len(code) <= 64
            assert "secret" not in link["url"]
            message = {"text": f"/start {code}", "chat": {"id": 42, "type": "private"},
                       "from": {"id": 42, "is_bot": False}}
            updates.extend([
                {"message": {**message, "text": "/start someone_else"}},
                {"message": {**message, "chat": {"id": 42, "type": "group"}}},
                {"message": {**message, "forward_origin": {"type": "user"}}},
            ])
            assert not (await service.confirm_link(db, "owner", "123:secret"))["ok"]
            assert not (await load_notif_config(db, user_id="owner")).telegram_chat_id
            updates.append({"message": message})
            with pytest.raises(ValueError, match="expirou"):
                await service.confirm_link(db, "other", "123:secret")
            with pytest.raises(ValueError, match="token mudou"):
                await service.confirm_link(db, "owner", "456:other")
            result = await service.confirm_link(db, "owner", "123:secret")
            assert result["ok"] and result["chat_id"] == "42"
            saved = await load_notif_config(db, user_id="owner")
            assert saved.telegram_enabled and saved.telegram_token == "123:secret"
            assert saved.wa_number == "123" and saved.reminder_minutes == 45
            assert not (await load_notif_config(db, user_id="other")).telegram_chat_id
            with pytest.raises(ValueError, match="expirou"):
                await service.confirm_link(db, "owner", "123:secret")
    asyncio.run(scenario())


def test_expired_link_is_not_accepted(monkeypatch):
    telegram(monkeypatch, [])

    async def scenario():
        async with database() as db:
            await service.begin_link(db, "owner", "123:secret")
            row = await db.get(ConfigModel, scoped_config_key("owner", "telegram_link"))
            pending = json.loads(row.value)
            pending["expires"] = 0
            row.value = json.dumps(pending)
            await db.commit()
            with pytest.raises(ValueError, match="expirou"):
                await service.confirm_link(db, "owner", "123:secret")
    asyncio.run(scenario())


def test_existing_webhook_is_preserved(monkeypatch):
    telegram(monkeypatch, [], webhook="https://existing.test/hook")

    async def scenario():
        async with database() as db:
            with pytest.raises(ValueError, match="outro servico"):
                await service.begin_link(db, "owner", "123:secret")
            assert await db.get(ConfigModel, scoped_config_key("owner", "telegram_link")) is None
    asyncio.run(scenario())


@pytest.mark.parametrize("token", ["@ExampleBot", "", "123:abc/sendMessage"])
def test_bot_handle_is_not_a_token(token):
    with pytest.raises(ValueError, match="BotFather"):
        service._clean_token(token)


def test_telegram_network_errors_do_not_expose_token(monkeypatch):
    real_client = httpx.AsyncClient

    def fail(request):
        raise httpx.ConnectError(str(request.url), request=request)

    monkeypatch.setattr(service.httpx, "AsyncClient", lambda **kwargs: real_client(
        **kwargs, transport=httpx.MockTransport(fail)))
    with pytest.raises(ValueError) as error:
        asyncio.run(service._call("123:secret", "getMe"))
    assert "secret" not in str(error.value)
    assert "api.telegram" not in str(error.value)


def test_authenticated_routes_complete_the_link(monkeypatch):
    from fastapi import FastAPI
    from app.core.database import get_db
    from app.core.security import get_current_user
    from app.routers.routes import router_notif

    updates = []
    telegram(monkeypatch, updates)

    async def scenario():
        async with database() as db:
            app = FastAPI()
            app.include_router(router_notif)
            async def session():
                yield db
            app.dependency_overrides[get_db] = session
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                                         base_url="http://test") as client:
                path = "/notifications/telegram/connect"
                body = {"telegram_token": "123:secret"}
                assert (await client.post(path, json=body)).status_code == 401
                app.dependency_overrides[get_current_user] = lambda: {"uid": "owner"}
                assert (await client.post(path, json={"telegram_token": "@ExampleBot"})).status_code == 400
                response = await client.post(path, json=body)
                assert response.status_code == 200
                code = response.json()["url"].split("?start=")[1]
                updates.append({"message": {
                    "text": f"/start {code}", "chat": {"id": 42, "type": "private"},
                    "from": {"id": 42, "is_bot": False},
                }})
                response = await client.post(path + "/confirm", json=body)
                assert response.status_code == 200
                assert response.json()["chat_id"] == "42"
    asyncio.run(scenario())
