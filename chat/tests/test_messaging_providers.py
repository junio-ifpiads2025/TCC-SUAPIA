import asyncio

import pytest
from fastapi import Request

from services import messaging_client, providers
from services.providers import IncomingMessage, InvalidPayload, MessagingProvider
from services.providers.waha import WahaProvider


class FakeProvider(MessagingProvider):
    name = "fake"

    def __init__(self):
        self.sent: list[tuple[str, str]] = []
        self.typing: list[str] = []

    async def parse_webhook(self, request):
        return None

    async def enviar_texto(self, chat_id, texto):
        self.sent.append((chat_id, texto))

    async def enviar_imagem(self, chat_id, url):
        self.sent.append((chat_id, url))

    async def iniciar_digitacao(self, chat_id):
        self.typing.append(chat_id)


def _request(body: dict) -> Request:
    async def receive():
        import json
        return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}

    return Request({"type": "http", "method": "POST", "headers": []}, receive)


def test_provider_must_implement_abstract_methods():
    class Incomplete(MessagingProvider):
        name = "incomplete"

    with pytest.raises(TypeError):
        Incomplete()


def test_optional_methods_default_to_noop():
    fake = FakeProvider()
    asyncio.run(fake.marcar_lida("1", "m1"))  # não levanta


def test_qualify_default_provider_keeps_native_id():
    assert providers.qualify("waha", "5586@c.us") == "5586@c.us"
    assert providers.qualify("telegram", "123") == "telegram:123"


def test_resolve_routes_by_prefix_and_strips_it():
    fake = FakeProvider()
    providers.register(fake)

    provider, native = providers.resolve("fake:42")
    assert provider is fake and native == "42"

    provider, native = providers.resolve("5586@c.us")
    assert isinstance(provider, WahaProvider) and native == "5586@c.us"


def test_messaging_client_dispatches_native_id_to_provider():
    fake = FakeProvider()
    providers.register(fake)

    asyncio.run(messaging_client.enviar_texto_async("fake:42", "oi"))
    asyncio.run(messaging_client.iniciar_digitacao_async("fake:42"))

    assert fake.sent == [("42", "oi")]
    assert fake.typing == ["42"]


def test_get_provider_unknown_raises():
    with pytest.raises(KeyError):
        providers.get_provider("nao-existe")


# ── WAHA parse_webhook ───────────────────────────────────────────────────────

def test_waha_parses_text_message():
    req = _request({"event": "message", "payload": {"body": "oi", "from": "5586@c.us", "id": "m1"}})
    msg = asyncio.run(WahaProvider().parse_webhook(req))
    assert msg == IncomingMessage(chat_id="5586@c.us", text="oi", message_id="m1")


@pytest.mark.parametrize("body", [
    {"event": "message.ack", "payload": {"body": "x", "from": "1"}},
    {"event": "message", "payload": {"body": "x", "from": "1", "fromMe": True}},
    {"event": "message", "payload": {"from": "1"}},
])
def test_waha_ignores_non_user_text(body):
    assert asyncio.run(WahaProvider().parse_webhook(_request(body))) is None


def test_waha_missing_sender_is_invalid():
    req = _request({"event": "message", "payload": {"body": "oi"}})
    with pytest.raises(InvalidPayload):
        asyncio.run(WahaProvider().parse_webhook(req))


# ── Telegram ─────────────────────────────────────────────────────────────────

from services.providers import telegram as tg  # noqa: E402


def _tg_request(body: dict, secret: str | None = None) -> Request:
    import json
    headers = [(b"x-telegram-bot-api-secret-token", secret.encode())] if secret else []

    async def receive():
        return {"type": "http.request", "body": json.dumps(body).encode(), "more_body": False}

    return Request({"type": "http", "method": "POST", "headers": headers}, receive)


def _tg_update(**message):
    base = {"message_id": 7, "chat": {"id": 123, "type": "private"}, "from": {"id": 123}, "text": "oi"}
    return {"update_id": 1, "message": {**base, **message}}


def test_telegram_parses_private_text():
    msg = asyncio.run(tg.TelegramProvider().parse_webhook(_tg_request(_tg_update())))
    assert msg == IncomingMessage(chat_id="123", text="oi", message_id="7")


@pytest.mark.parametrize("update", [
    {"update_id": 1, "edited_message": {}},
    _tg_update(chat={"id": -5, "type": "group"}),
    _tg_update(text=None),
    _tg_update(**{"from": {"id": 9, "is_bot": True}}),
])
def test_telegram_ignores_non_private_text(update):
    assert asyncio.run(tg.TelegramProvider().parse_webhook(_tg_request(update))) is None


def test_telegram_rejects_wrong_secret(monkeypatch):
    monkeypatch.setattr(tg, "TELEGRAM_WEBHOOK_SECRET", "s3cret")
    provider = tg.TelegramProvider()
    with pytest.raises(InvalidPayload):
        asyncio.run(provider.parse_webhook(_tg_request(_tg_update(), secret="wrong")))
    assert asyncio.run(provider.parse_webhook(_tg_request(_tg_update(), secret="s3cret"))) is not None


def test_telegram_split_respects_limit_and_keeps_content():
    texto = ("palavra " * 1500).strip()
    parts = tg._split(texto)
    assert len(parts) > 1 and all(len(p) <= 4096 for p in parts)
    assert " ".join(parts).split() == texto.split()
    assert tg._split("curto") == ["curto"]
