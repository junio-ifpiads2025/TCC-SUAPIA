import pytest
import config
from services.shared import acl_service as acl

pytestmark = pytest.mark.anyio


@pytest.fixture
def db(monkeypatch):
    """Banco fake: dict chat_id -> kind."""
    store = {}

    async def all_():
        return list(store.items())

    async def upsert(chat_id, kind, reason, by):
        store[chat_id] = kind

    async def delete(chat_id):
        store.pop(chat_id, None)

    async def get(chat_id):
        return {"chat_id": chat_id, "kind": store[chat_id], "reason": None} if chat_id in store else None

    async def none(*a):
        return None

    async def no_limits():
        return {}

    monkeypatch.setattr(acl, "_db_get", get)
    monkeypatch.setattr(acl, "_db_get_open", none)
    monkeypatch.setattr(acl, "_db_get_setting", none)
    monkeypatch.setattr(acl, "_db_limits", no_limits)
    monkeypatch.setattr(acl, "_db_all", all_)
    monkeypatch.setattr(acl, "_db_upsert", upsert)
    monkeypatch.setattr(acl, "_db_delete", delete)
    acl._allow.clear()
    acl._block.clear()
    monkeypatch.setattr(config, "RESPONDER_QUALQUER_NUMERO", False)
    return store


async def test_load_reads_only_from_db(db):
    db["a"] = "allow"
    await acl.load()
    assert acl.check("a") == "ok"
    db.clear(); db["z"] = "allow"
    await acl.load()
    assert acl.check("a") == "denied" and acl.check("z") == "ok"


async def test_block_wins_over_allow(db):
    await acl.add_rule("x", "allow")
    assert acl.check("x") == "ok"
    await acl.add_rule("x", "block")  # upsert muda o kind
    assert acl.check("x") == "blocked" and acl.counts() == {"allow": 0, "block": 1}


async def test_any_number_mode(db, monkeypatch):
    monkeypatch.setattr(config, "RESPONDER_QUALQUER_NUMERO", True)
    assert acl.check("novo") == "ok"
    await acl.add_rule("novo", "block")
    assert acl.check("novo") == "blocked"


async def test_cache_updates_on_write_and_remove(db):
    assert acl.check("n") == "denied"
    await acl.add_rule("n", "allow")
    assert acl.check("n") == "ok"
    await acl.remove_rule("n")
    assert acl.check("n") == "denied" and "n" not in db


async def test_invalid_input(db):
    with pytest.raises(ValueError):
        await acl.add_rule("", "allow")
    with pytest.raises(ValueError):
        await acl.add_rule("x", "foo")


async def test_block_clears_session_when_asked(db, monkeypatch):
    cleared = []

    async def fake(chat_id):
        cleared.append(chat_id)

    monkeypatch.setattr(acl, "clear_user_session", fake)
    await acl.add_rule("a", "block")
    await acl.add_rule("b", "block", clear_session=True)
    await acl.add_rule("c", "allow", clear_session=True)
    assert cleared == ["b"]


def test_open_mode_override_beats_env(monkeypatch):
    monkeypatch.setattr(config, "RESPONDER_QUALQUER_NUMERO", False)
    monkeypatch.setattr(acl, "_open_mode", True)
    acl._allow.clear(); acl._block.clear()
    assert acl.check("x") == "ok"
    acl._block.add("x")
    assert acl.check("x") == "blocked"
