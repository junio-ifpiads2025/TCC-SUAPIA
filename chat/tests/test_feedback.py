import fakeredis.aioredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.admin import quality as admin_quality
from routes.admin.common import require_admin, verify_csrf
from services.chat import feedback_service as fb, message_router as mr, queue_service as qs
from services.shared import qa_case_service as qa

pytestmark = pytest.mark.anyio


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def cases(monkeypatch):
    rows = []

    async def insert(row):
        rows.append({"id": len(rows) + 1, "status": "new", "note": None, **row})

    monkeypatch.setattr(qa, "_db_insert", insert)
    return rows


@pytest.fixture
def redis(monkeypatch, cases):
    r = fakeredis.aioredis.FakeRedis(decode_responses=True)
    monkeypatch.setattr(qs, "get_redis", lambda: r)
    monkeypatch.setattr(fb, "get_redis", lambda: r)
    monkeypatch.setattr(qs.access_log_service, "log_event", lambda *a, **k: None)
    sent, rate_calls = [], []

    async def noop(*a, **k):
        return None

    async def send(chat_id, texto):
        sent.append(texto)

    async def is_auth(c):
        return True

    async def inc(c):
        rate_calls.append(c)
        return 1

    for name, fn in (("marcar_lida_async", noop), ("iniciar_digitacao_async", noop),
                     ("enviar_texto_async", send), ("is_authenticated", is_auth),
                     ("increment_rate", inc)):
        monkeypatch.setattr(qs, name, fn)
    monkeypatch.setattr(qs, "get_profile", lambda c: noop())
    r.sent, r.rate_calls = sent, rate_calls
    return r


async def test_handle_up_stores_no_content(redis, cases):
    await fb.arm("u1", "pergunta", "resposta", [{"titulo": "Manual"}])
    assert await fb.handle("u1", " 1 ") == fb.THANKS_TEXT
    assert cases == [{"id": 1, "status": "new", "note": None, "kind": "up", "chat_id": "u1",
                      "question": None, "answer": None, "chunks": None}]
    assert await fb.handle("u1", "1") is None  # pendência consumida


async def test_handle_down_stores_content(redis, cases):
    await fb.arm("u1", "pergunta", "resposta", [{"titulo": "Manual", "page_content": "x"}])
    assert await fb.handle("u1", "2") == fb.THANKS_TEXT
    c = cases[0]
    assert c["kind"] == "down" and c["question"] == "pergunta" and c["answer"] == "resposta"
    assert c["chunks"] == [{"titulo": "Manual"}]  # só metadados, sem texto do trecho


async def test_without_pending_or_other_text(redis, cases):
    assert await fb.handle("u1", "1") is None
    await fb.arm("u1", "p", "r", [])
    assert await fb.handle("u1", "obrigado") is None
    assert cases == []


async def test_queue_flow_prompt_then_feedback(redis, cases, monkeypatch):
    routed = []

    async def fake_route(chat_id, content):
        routed.append(content)
        return "Resposta", {"chunks": [{"titulo": "M"}], "no_answer": False, "ask_feedback": True}

    monkeypatch.setattr(qs, "route", fake_route)
    await qs.enqueue("u1", "Como faço X?")
    await qs.process_next(timeout=1)
    assert redis.sent[-1] == "Resposta" + fb.FEEDBACK_PROMPT

    await qs.enqueue("u1", "2")
    assert redis.sent[-1] == fb.THANKS_TEXT
    assert routed == ["Como faço X?"] and len(redis.rate_calls) == 1  # "2" não chama LLM nem conta
    assert cases[0]["kind"] == "down" and cases[0]["question"] == "Como faço X?"
    assert cases[0]["answer"] == "Resposta"


async def test_queue_no_answer_records_case(redis, cases, monkeypatch):
    async def fake_route(chat_id, content):
        return "Não encontrei isso.", {"chunks": [], "no_answer": True, "ask_feedback": False}

    monkeypatch.setattr(qs, "route", fake_route)
    await qs.enqueue("u1", "Pergunta rara")
    await qs.process_next(timeout=1)
    assert redis.sent[-1] == "Não encontrei isso."
    assert cases[0]["kind"] == "no_answer" and cases[0]["question"] == "Pergunta rara"
    assert await redis.get(fb._key("u1")) is None


def test_is_no_answer():
    assert mr.is_no_answer("Desculpe, não encontrei informações sobre isso.", [])
    assert not mr.is_no_answer("Desculpe, não encontrei informações sobre isso.", [{"titulo": "M"}])
    assert not mr.is_no_answer("Sua nota é 8.", [])


async def test_route_meta(monkeypatch):
    async def token(c):
        return "t"

    async def thread(c):
        return []

    async def append(*a):
        return None

    monkeypatch.setattr(mr, "get_token", token)
    monkeypatch.setattr(mr.thread_service, "get_thread", thread)
    monkeypatch.setattr(mr.thread_service, "append_messages", append)
    monkeypatch.setattr(mr, "_call_agent", lambda m, t, h: ("Sua nota é 8.", []))
    _, meta = await mr.route("c1", "/menu")
    assert meta["ask_feedback"] is False
    _, meta = await mr.route("c1", "minha nota")
    assert meta == {"chunks": [], "no_answer": False, "ask_feedback": True}
    monkeypatch.setattr(mr, "_call_agent", lambda m, t, h: ("Não encontrei nada.", []))
    _, meta = await mr.route("c1", "algo")
    assert meta["no_answer"] is True and meta["ask_feedback"] is False


async def test_update_case_is_audited(monkeypatch, audit_rows):
    row = {"id": 5, "kind": "down", "chat_id": "u1", "question": "q", "answer": "a",
           "chunks": [], "status": "new", "note": None, "created_at": None}

    async def get(case_id):
        return dict(row) if case_id == 5 else None

    async def update(case_id, values):
        row.update(values)
        return dict(row)

    monkeypatch.setattr(qa, "_db_get", get)
    monkeypatch.setattr(qa, "_db_update", update)
    await qa.update_case(5, "reviewed", " ok ")
    assert audit_rows[-1]["entity"] == "qa_case" and audit_rows[-1]["entity_id"] == "5"
    assert audit_rows[-1]["before"] == {"status": "new", "note": None}
    assert audit_rows[-1]["after"] == {"status": "reviewed", "note": "ok"}
    with pytest.raises(ValueError):
        await qa.update_case(5, "x", None)
    with pytest.raises(qa.QaCaseNotFound):
        await qa.update_case(9, "reviewed", None)


def test_group_similar():
    cases = [{"id": 1, "question": "Como emitir a declaração de matrícula?"},
             {"id": 2, "question": "como emitir declaracao de matricula no suap"},
             {"id": 3, "question": "Qual o horário da biblioteca?"}]
    groups = qa.group_similar(cases)
    assert groups[0]["count"] == 2 and groups[0]["ids"] == [1, 2]
    assert groups[1]["ids"] == [3]


def test_mask_chat_id():
    assert qa.mask_chat_id("5586999991234@c.us") == "•••1234"
    assert qa.mask_chat_id("telegram:987654") == "•••7654"


@pytest.fixture
def client(monkeypatch):
    calls = []

    async def list_cases(kind, limit=200):
        calls.append(("list", kind))
        return [{"id": 1, "kind": kind, "chat_id_masked": "•••1234", "question": "<b>q</b>",
                 "answer": "a", "chunks": [{"titulo": "Manual X"}], "status": "new", "note": None,
                 "created_at": None}]

    async def satisfaction(days=30):
        return {"days": 30, "up": 3, "down": 1, "no_answer": 2, "rate": 75}

    async def update_case(case_id, status, note):
        calls.append(("update", case_id, status, note))

    async def get_case(case_id):
        if case_id != 1:
            raise qa.QaCaseNotFound(case_id)
        return {"id": 1, "question": "Como emitir declaração?", "note": "n"}

    for n, f in (("list_cases", list_cases), ("satisfaction", satisfaction),
                 ("update_case", update_case), ("get_case", get_case)):
        monkeypatch.setattr(qa, n, f)
    app = FastAPI()
    app.include_router(admin_quality.router)
    app.dependency_overrides[require_admin] = lambda: "tester"
    app.dependency_overrides[verify_csrf] = lambda: None
    c = TestClient(app)
    c.calls = calls
    return c


def test_quality_page(client):
    r = client.get("/admin/quality?tab=no_answer")
    assert r.status_code == 200
    assert "<b>q</b>" not in r.text and "&lt;b&gt;q&lt;/b&gt;" in r.text
    assert "75%" in r.text and "Manual X" in r.text and "Perguntas parecidas" in r.text
    assert ("list", "no_answer") in client.calls
    client.get("/admin/quality?tab=xyz")
    assert client.calls[-1] == ("list", "down")


def test_quality_update_and_convert(client):
    r = client.post("/admin/quality/1", data={"status": "reviewed", "note": "ok", "tab": "down"},
                    follow_redirects=False)
    assert r.status_code == 303 and ("update", 1, "reviewed", "ok") in client.calls
    r = client.post("/admin/quality/1/convert", data={"tab": "down"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"].startswith("/admin/knowledge?title=Como")
    assert ("update", 1, "converted", "n") in client.calls
    r = client.post("/admin/quality/2/convert", data={"tab": "down"}, follow_redirects=False)
    assert "caso+n%C3%A3o+encontrado" in r.headers["location"]
