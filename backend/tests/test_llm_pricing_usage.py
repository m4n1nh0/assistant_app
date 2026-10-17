"""Preço de token no banco e consumo de IA por cliente.

O que isto protege: o preço vem do modelo e não só do provedor (com versão por data e sem confundir
`gpt-4o` com `gpt-4o-mini`), preço digitado a mão nunca é sobrescrito pela importação, modelo
gratuito custa zero de verdade, o consumo soma por dia/cliente/provedor/modelo sem tratar token
ausente como zero, cada conta só vê o próprio consumo, e a chamada ao modelo é atribuída ao cliente
dono do contexto ativo.
"""

from __future__ import annotations

import asyncio
import tempfile
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.database import LLMPriceModel, LLMUsageDailyModel, UserModel, get_db
from app.core.security import get_current_user
from app.models.schemas import LLMResponse
from app.routers import observability
from app.services import llm_price_service as prices
from app.services import llm_service, llm_usage_service as usage_service
from app.services.user_llm_config_service import (
    UserLLMRuntime, activate_user_llms, reset_user_llms)
from shared.observability import ModelPrice, build_usage, price_for, set_db_prices
from shared.observability.costs import estimate_cost


@pytest.fixture(autouse=True)
def limpa_precos():
    set_db_prices({})
    yield
    set_db_prices({})
    usage_service._enabled = False


# --- preço pelo modelo -------------------------------------------------------------------------


def test_sem_banco_vale_o_preco_do_provedor_do_codigo():
    assert price_for("claude", "qualquer").input_per_mtok == 3.0


def test_preco_do_modelo_no_banco_vence_o_do_provedor():
    set_db_prices({("claude", "claude-opus-4"): ModelPrice(15.0, 75.0)})

    assert price_for("claude", "claude-opus-4").output_per_mtok == 75.0
    assert price_for("claude", "claude-haiku-3").input_per_mtok == 3.0  # cai no padrao


def test_id_com_data_casa_com_o_modelo_sem_versao():
    set_db_prices({("claude", "claude-sonnet-4"): ModelPrice(3.0, 15.0),
                   ("gpt", "gpt-4o"): ModelPrice(2.5, 10.0)})

    assert price_for("claude", "claude-sonnet-4-20250514").output_per_mtok == 15.0
    assert price_for("gpt", "gpt-4o-2024-08-06").output_per_mtok == 10.0
    assert price_for("gpt", "gpt-4o-latest").output_per_mtok == 10.0


def test_gpt_4o_nao_se_confunde_com_gpt_4o_mini():
    set_db_prices({("gpt", "gpt-4o"): ModelPrice(9.0, 9.0)})

    # So existe o `gpt-4o`: o mini nao herda o preco do irmao caro e cai no padrao do provedor
    # (2.5 / 10.0 na tabela do codigo), nunca nos 9.0 do `gpt-4o`.
    assert price_for("gpt", "gpt-4o-mini").output_per_mtok == 10.0
    assert price_for("gpt", "gpt-4o-mini-2024-07-18").output_per_mtok == 10.0
    set_db_prices({("gpt", "gpt-4o"): ModelPrice(9.0, 9.0), ("gpt", "gpt-4o-mini"): ModelPrice(0.15, 0.6)})
    assert price_for("gpt", "gpt-4o-mini-2024-07-18").output_per_mtok == 0.6
    assert price_for("gpt", "gpt-4o-mini").output_per_mtok == 0.6


def test_modelo_gratuito_custa_zero_mesmo_com_provedor_pago():
    set_db_prices({("openrouter", "meta-llama/llama-3.3-70b:free"): ModelPrice(0.0, 0.0)})

    assert estimate_cost("openrouter", "meta-llama/llama-3.3-70b:free",
                         input_tokens=10_000, output_tokens=5_000) == 0.0
    assert estimate_cost("openrouter", "outro-modelo", input_tokens=1_000_000) == 1.0


def test_padrao_do_provedor_no_banco_vence_o_do_codigo():
    set_db_prices({("claude", ""): ModelPrice(1.0, 5.0)})

    assert price_for("claude", "modelo-novo").input_per_mtok == 1.0


def test_sem_token_informado_nao_ha_custo_e_nao_vira_zero():
    assert estimate_cost("claude", "x") is None


# --- importação da tabela pública --------------------------------------------------------------

FONTE = {
    "sample_spec": {"mode": "chat"},
    "claude-sonnet-4-20250514": {
        "litellm_provider": "anthropic", "mode": "chat", "input_cost_per_token": 3e-06,
        "output_cost_per_token": 1.5e-05, "cache_read_input_token_cost": 3e-07},
    "gpt-4o": {"litellm_provider": "openai", "mode": "chat",
               "input_cost_per_token": 2.5e-06, "output_cost_per_token": 1e-05},
    "gemini/gemini-1.5-flash": {"litellm_provider": "gemini", "mode": "chat",
                                "input_cost_per_token": 7.5e-08, "output_cost_per_token": 3e-07},
    "xai/grok-3": {"litellm_provider": "xai", "mode": "chat",
                   "input_cost_per_token": 3e-06, "output_cost_per_token": 1.5e-05},
    "openrouter/meta-llama/llama-3.3-70b:free": {
        "litellm_provider": "openrouter", "mode": "chat",
        "input_cost_per_token": 0.0, "output_cost_per_token": 0.0},
    # fora do que o app usa:
    "text-embedding-3-small": {"litellm_provider": "openai", "mode": "embedding",
                               "input_cost_per_token": 2e-08},
    "bedrock/foo": {"litellm_provider": "bedrock", "mode": "chat",
                    "input_cost_per_token": 1e-06, "output_cost_per_token": 1e-06},
    "ft:gpt-4o:minha-empresa": {"litellm_provider": "openai", "mode": "chat",
                                "input_cost_per_token": 1e-06, "output_cost_per_token": 1e-06},
    "sem-preco": {"litellm_provider": "openai", "mode": "chat"},
}


def test_importacao_le_so_modelos_de_chat_dos_provedores_do_app():
    linhas = {(r["provider"], r["model"]): r for r in prices.parse_source(FONTE)}

    assert set(linhas) == {
        ("claude", "claude-sonnet-4-20250514"), ("gpt", "gpt-4o"),
        ("gemini", "gemini-1.5-flash"), ("grok", "grok-3"),
        ("openrouter", "meta-llama/llama-3.3-70b:free")}
    claude = linhas[("claude", "claude-sonnet-4-20250514")]
    # Por token vira por milhao, sem sujeira de ponto flutuante.
    assert (claude["input_per_mtok"], claude["output_per_mtok"]) == (3.0, 15.0)
    assert claude["cached_input_per_mtok"] == 0.3
    assert linhas[("gpt", "gpt-4o")]["cached_input_per_mtok"] is None
    assert linhas[("openrouter", "meta-llama/llama-3.3-70b:free")]["input_per_mtok"] == 0.0


def test_formato_inesperado_da_fonte_e_recusado():
    with pytest.raises(prices.PriceError):
        prices.parse_source([1, 2, 3])


# --- banco -------------------------------------------------------------------------------------


@pytest.fixture
def sessions():
    engine = create_async_engine(f"sqlite+aiosqlite:///{tempfile.mkdtemp()}/p.db")
    maker = async_sessionmaker(engine, expire_on_commit=False)

    async def criar():
        async with engine.begin() as conn:
            for model in (LLMPriceModel, LLMUsageDailyModel, UserModel):
                await conn.run_sync(model.__table__.create)

    asyncio.run(criar())
    yield maker
    asyncio.run(engine.dispose())


def roda(sessions, corrotina):
    async def run():
        async with sessions() as db:
            return await corrotina(db)
    return asyncio.run(run())


def test_preco_a_mao_grava_valida_e_passa_a_valer_na_hora(sessions):
    async def caso(db):
        row = await prices.upsert_manual(
            db, provider="Claude", model="  Claude-Opus-4 ", input_per_mtok=15, output_per_mtok=75)
        return row.model, row.source

    assert roda(sessions, caso) == ("claude-opus-4", "manual")
    assert price_for("claude", "claude-opus-4").output_per_mtok == 75.0


@pytest.mark.parametrize("campos,trecho", [
    ({"provider": "inventado"}, "Provedor"),
    ({"input_per_mtok": -1}, "zero ou maior"),
    ({"output_per_mtok": float("nan")}, "zero ou maior"),
    ({"input_per_mtok": "abc"}, "invalido"),
])
def test_preco_invalido_e_recusado(sessions, campos, trecho):
    base = dict(provider="claude", model="x", input_per_mtok=1, output_per_mtok=1)

    async def caso(db):
        with pytest.raises(prices.PriceError) as erro:
            await prices.upsert_manual(db, **{**base, **campos})
        return erro.value.message

    assert trecho in roda(sessions, caso)


def test_sincronizar_traz_o_que_falta_e_nunca_pisa_no_preco_manual(sessions):
    async def fonte():
        return FONTE

    async def caso(db):
        await prices.upsert_manual(db, provider="gpt", model="gpt-4o",
                                   input_per_mtok=1.0, output_per_mtok=2.0)
        primeira = await prices.sync_from_source(db, fetch=fonte)
        segunda = await prices.sync_from_source(db, fetch=fonte)
        linhas = {(r.provider, r.model): r for r in await prices.list_prices(db)}
        return primeira, segunda, linhas

    primeira, segunda, linhas = roda(sessions, caso)

    assert primeira == {"models_in_source": 5, "added": 4, "updated": 0, "kept_manual": 1}
    assert segunda == {"models_in_source": 5, "added": 0, "updated": 0, "kept_manual": 1}
    gpt = linhas[("gpt", "gpt-4o")]
    assert (gpt.input_per_mtok, gpt.output_per_mtok, gpt.source) == (1.0, 2.0, "manual")
    assert linhas[("claude", "claude-sonnet-4-20250514")].source == "litellm"
    # E a tabela em memoria ja reflete a importacao.
    assert price_for("openrouter", "meta-llama/llama-3.3-70b:free").input_per_mtok == 0.0


def test_sincronizar_atualiza_preco_importado_que_mudou(sessions):
    async def antiga():
        return {"gpt-4o": {"litellm_provider": "openai", "mode": "chat",
                           "input_cost_per_token": 5e-06, "output_cost_per_token": 1.5e-05}}

    async def nova():
        return {"gpt-4o": {"litellm_provider": "openai", "mode": "chat",
                           "input_cost_per_token": 2.5e-06, "output_cost_per_token": 1e-05}}

    async def caso(db):
        await prices.sync_from_source(db, fetch=antiga)
        resultado = await prices.sync_from_source(db, fetch=nova)
        return resultado, (await prices.list_prices(db))[0].input_per_mtok

    resultado, preco = roda(sessions, caso)
    assert resultado["updated"] == 1 and preco == 2.5


def test_sem_rede_a_sincronizacao_falha_com_motivo_e_mantem_o_que_havia(sessions):
    async def fora():
        raise prices.PriceError("Nao consegui baixar a tabela de precos: timeout", 502)

    async def caso(db):
        await prices.upsert_manual(db, provider="claude", model="x", input_per_mtok=1, output_per_mtok=1)
        with pytest.raises(prices.PriceError):
            await prices.sync_from_source(db, fetch=fora)
        return len(await prices.list_prices(db))

    assert roda(sessions, caso) == 1


def test_apagar_o_preco_devolve_o_modelo_ao_padrao(sessions):
    async def caso(db):
        row = await prices.upsert_manual(
            db, provider="claude", model="claude-opus-4", input_per_mtok=15, output_per_mtok=75)
        apagou = await prices.delete_price(db, row.id)
        return apagou, await prices.delete_price(db, "nao-existe")

    assert roda(sessions, caso) == (True, False)
    assert price_for("claude", "claude-opus-4").output_per_mtok == 15.0  # padrao do codigo


# --- consumo por cliente -----------------------------------------------------------------------


def uso(provider="claude", model="sonnet", entrada=1000, saida=500, ok=True):
    return build_usage(provider, model=model, input_tokens=entrada, output_tokens=saida, ok=ok)


def test_consumo_soma_por_dia_cliente_provedor_e_modelo(sessions):
    async def caso(db):
        await usage_service.add_usage(db, uso(), "t1", day="2026-10-10")
        await usage_service.add_usage(db, uso(entrada=2000), "t1", day="2026-10-10")
        await usage_service.add_usage(db, uso(), "t2", day="2026-10-10")
        await usage_service.add_usage(db, uso(model="haiku"), "t1", day="2026-10-10")
        return (await db.execute(select(LLMUsageDailyModel))).scalars().all()

    linhas = roda(sessions, caso)
    por_chave = {(r.tenant_id, r.model): r for r in linhas}

    assert len(linhas) == 3
    t1 = por_chave[("t1", "sonnet")]
    assert (t1.calls, t1.input_tokens, t1.output_tokens) == (2, 3000, 1000)
    assert t1.cost_usd == pytest.approx(3000 * 3 / 1e6 + 1000 * 15 / 1e6)


def test_token_ausente_nao_vira_zero_e_a_chamada_fica_sem_preco(sessions):
    async def caso(db):
        await usage_service.add_usage(
            db, build_usage("claude", model="x"), "t1", day="2026-10-10")
        await usage_service.add_usage(db, uso(), "t1", day="2026-10-11")
        return (await db.execute(select(LLMUsageDailyModel).order_by(LLMUsageDailyModel.day))
                ).scalars().all()

    sem_token, com_token = roda(sessions, caso)
    assert (sem_token.calls, sem_token.unpriced_calls, sem_token.cost_usd) == (1, 1, 0.0)
    assert com_token.unpriced_calls == 0


def test_chamada_com_erro_e_contada(sessions):
    async def caso(db):
        await usage_service.add_usage(db, uso(ok=False), "t1", day="2026-10-10")
        await usage_service.add_usage(db, uso(), "t1", day="2026-10-10")
        return (await db.execute(select(LLMUsageDailyModel))).scalars().one()

    linha = roda(sessions, caso)
    assert (linha.calls, linha.errors) == (2, 1)


def test_chamada_que_falhou_nao_conta_como_sem_preco(sessions):
    # Falha nao tem token nem custo por natureza: e falha, e nao "sem preco". So a chamada que deu
    # certo e ficou sem custo (agente conectado, provedor que nao informou token) e "sem preco".
    async def caso(db):
        await usage_service.add_usage(db, build_usage("claude", ok=False), "t1", day="2026-10-10")
        await usage_service.add_usage(db, build_usage("claude", ok=False), "t1", day="2026-10-10")
        await usage_service.add_usage(db, build_usage("codex_cli"), "t1", day="2026-10-10")
        return (await db.execute(select(LLMUsageDailyModel).order_by(LLMUsageDailyModel.provider))
                ).scalars().all()

    claude, agente = roda(sessions, caso)

    assert (claude.calls, claude.errors, claude.unpriced_calls) == (2, 2, 0)
    assert (agente.calls, agente.errors, agente.unpriced_calls) == (1, 0, 1)


def hoje(dias_atras=0):
    return (datetime.now(timezone.utc) - timedelta(days=dias_atras)).strftime("%Y-%m-%d")


def test_resumo_agrupa_e_respeita_a_janela_e_o_cliente(sessions):
    async def caso(db):
        await usage_service.add_usage(db, uso(), "t1", day=hoje(0))
        await usage_service.add_usage(db, uso(provider="gpt", model="gpt-4o"), "t1", day=hoje(1))
        await usage_service.add_usage(db, uso(), "t2", day=hoje(1))
        await usage_service.add_usage(db, uso(), "t1", day=hoje(40))  # fora da janela de 30 dias
        return {
            "provider": await usage_service.summarize(db, days=30, group_by="provider", tenant_id="t1"),
            "model": await usage_service.summarize(db, days=30, group_by="model", tenant_id="t1"),
            "day": await usage_service.summarize(db, days=30, group_by="day", tenant_id="t1"),
            "tenant": await usage_service.summarize(db, days=30, group_by="tenant"),
            "curto": await usage_service.summarize(db, days=1, group_by="provider", tenant_id="t1"),
        }

    r = roda(sessions, caso)

    assert r["provider"]["total"]["calls"] == 2  # a de 40 dias atras nao entra
    assert {g["key"] for g in r["provider"]["groups"]} == {"claude", "gpt"}
    assert {g["label"] for g in r["model"]["groups"]} == {"claude/sonnet", "gpt/gpt-4o"}
    assert [g["key"] for g in r["day"]["groups"]] == sorted(g["key"] for g in r["day"]["groups"])
    assert {g["key"]: g["calls"] for g in r["tenant"]["groups"]} == {"t1": 2, "t2": 1}
    assert r["curto"]["total"]["calls"] == 1
    assert r["provider"]["estimated"] is True


def test_cliente_sem_conta_aparece_com_nome_legivel(sessions):
    async def caso(db):
        await usage_service.add_usage(db, uso(), "", day=hoje())
        return await usage_service.summarize(db, days=7, group_by="tenant")

    assert roda(sessions, caso)["groups"][0]["label"] == "(sem conta)"


# --- de quem é a chamada -----------------------------------------------------------------------


def test_cliente_sai_do_escopo_dos_provedores():
    assert usage_service.tenant_of_scope("tutor:abc") == "abc"
    assert usage_service.tenant_of_scope("local") == ""


def test_gravacao_e_desligada_por_padrao_e_nao_agenda_nada(monkeypatch):
    chamadas = []

    async def falso(usage, tenant):
        chamadas.append(tenant)

    monkeypatch.setattr(usage_service, "_persist", falso)

    async def roda_agora():
        usage_service.schedule(uso(), "t1")
        await asyncio.sleep(0)

    asyncio.run(roda_agora())
    assert chamadas == []


def test_chamada_ao_modelo_e_atribuida_ao_cliente_do_contexto_ativo(monkeypatch):
    chamadas = []

    async def falso(usage, tenant):
        chamadas.append((tenant, usage.provider, usage.input_tokens))

    async def chamador(message, history, system, **kwargs):
        return LLMResponse(llm="claude", content="ok", model="sonnet", input_tokens=7, output_tokens=3)

    monkeypatch.setattr(usage_service, "_persist", falso)
    monkeypatch.setitem(llm_service.LLM_CALLERS, "claude", chamador)
    usage_service.enable()

    async def roda_agora():
        token = activate_user_llms(UserLLMRuntime(scope="tutor:t9", providers={}))
        try:
            await llm_service.dispatch_single("claude", "oi", [], "sistema")
        finally:
            reset_user_llms(token)
        await asyncio.sleep(0.05)

    asyncio.run(roda_agora())
    assert chamadas == [("t9", "claude", 7)]


def test_agente_conectado_conta_a_chamada_sem_token_nem_custo(sessions, monkeypatch):
    registrado = []

    async def captura(usage, tenant):
        registrado.append((usage.provider, usage.input_tokens, usage.estimated_cost_usd, tenant))

    monkeypatch.setattr(usage_service, "_persist", captura)
    usage_service.enable()

    async def roda_agora():
        usage_service.record_agent_call("codex_cli", "t1")
        await asyncio.sleep(0.05)

    asyncio.run(roda_agora())
    assert registrado == [("codex_cli", None, None, "t1")]


# --- rotas -------------------------------------------------------------------------------------


@pytest.fixture
def api(sessions, monkeypatch):
    estado = {"user": {"uid": "u1", "tutor_id": "t1", "role": "user"}}

    async def semear(db):
        db.add_all([
            UserModel(id="u1", username="ana", email="ana@x.com", tutor_id="t1",
                      password_hash="x"),
            UserModel(id="u2", username="bia", email=None, tutor_id="t2", password_hash="x"),
        ])
        await db.commit()
        await usage_service.add_usage(db, uso(), "t1", day=hoje())
        await usage_service.add_usage(db, uso(), "t2", day=hoje())
        await usage_service.add_usage(db, uso(), "t2", day=hoje())

    roda(sessions, semear)

    async def db_dependency():
        async with sessions() as session:
            yield session

    app = FastAPI()
    app.include_router(observability.router)
    app.dependency_overrides[get_db] = db_dependency
    app.dependency_overrides[get_current_user] = lambda: estado["user"]
    client = TestClient(app)
    client.estado = estado
    client.monkeypatch = monkeypatch
    return client


def como_admin(api):
    api.estado["user"] = {"uid": "u9", "tutor_id": "t0", "role": "admin"}


def test_cada_conta_ve_so_o_proprio_consumo(api):
    dados = api.get("/observability/usage").json()

    assert dados["scope"] == "mine" and dados["total"]["calls"] == 1


def test_conta_comum_nao_ve_o_de_todos_nem_agrupa_por_cliente(api):
    assert api.get("/observability/usage", params={"scope": "all"}).status_code == 403
    assert api.get("/observability/usage", params={"group_by": "tenant"}).status_code == 403


def test_administrador_ve_todos_e_os_clientes_com_nome(api):
    como_admin(api)
    dados = api.get("/observability/usage", params={"scope": "all", "group_by": "tenant"}).json()

    por_cliente = {g["key"]: g for g in dados["groups"]}
    assert dados["total"]["calls"] == 3
    assert por_cliente["t1"]["label"] == "ana@x.com"
    assert por_cliente["t2"]["label"] == "bia"  # sem e-mail, o usuario


def test_precos_listam_para_qualquer_conta_mas_so_admin_edita(api):
    corpo = {"provider": "claude", "model": "claude-opus-4", "input_per_mtok": 15,
             "output_per_mtok": 75}

    assert api.put("/observability/prices", json=corpo).status_code == 403
    como_admin(api)
    criado = api.put("/observability/prices", json=corpo)
    assert criado.status_code == 200 and criado.json()["source"] == "manual"

    api.estado["user"] = {"uid": "u1", "tutor_id": "t1", "role": "user"}
    lista = api.get("/observability/prices").json()
    assert [p["model"] for p in lista["prices"]] == ["claude-opus-4"]
    assert "claude" in lista["providers"]
    assert api.delete(f"/observability/prices/{criado.json()['id']}").status_code == 403


def test_admin_apaga_preco_e_preco_invalido_volta_400(api):
    como_admin(api)
    criado = api.put("/observability/prices", json={
        "provider": "claude", "model": "x", "input_per_mtok": 1, "output_per_mtok": 1}).json()

    assert api.put("/observability/prices", json={
        "provider": "inventado", "model": "x", "input_per_mtok": 1,
        "output_per_mtok": 1}).status_code == 400
    assert api.delete(f"/observability/prices/{criado['id']}").status_code == 200
    assert api.delete(f"/observability/prices/{criado['id']}").status_code == 404


def test_sincronizar_so_para_admin_e_devolve_o_resumo(api):
    async def fonte():
        return FONTE

    api.monkeypatch.setattr(prices, "fetch_source", fonte)

    assert api.post("/observability/prices/sync").status_code == 403
    como_admin(api)
    resp = api.post("/observability/prices/sync")

    assert resp.status_code == 200
    assert resp.json()["added"] == 5 and "litellm" in resp.json()["source"]


def test_sem_rede_a_rota_devolve_502_com_o_motivo(api):
    async def fora():
        raise prices.PriceError("Nao consegui baixar a tabela de precos: timeout", 502)

    api.monkeypatch.setattr(prices, "fetch_source", fora)
    como_admin(api)
    resp = api.post("/observability/prices/sync")

    assert resp.status_code == 502 and "timeout" in resp.json()["detail"]
