import asyncio
import functools


def arun(fn):
    """Roda teste async sem plugin (pytest-asyncio não instalado)."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return asyncio.run(fn(*a, **kw))
    return wrapper


import pytest

from services import guardrail_service as gs
from services import prompt_service as ps


@pytest.fixture
def db(monkeypatch):
    versions = []

    async def active():
        return next((v for v in versions if v["active"]), None)

    async def insert(content, author):
        for v in versions:
            v["active"] = False
        v = {"id": len(versions) + 1, "content": content, "active": True, "author": author, "created_at": "t"}
        versions.append(v)
        return v

    async def activate(vid):
        v = next((x for x in versions if x["id"] == vid), None)
        if v is None:
            raise ps.PromptNotFound(vid)
        for x in versions:
            x["active"] = False
        v["active"] = True
        return v

    async def lst():
        return list(reversed(versions))

    monkeypatch.setattr(ps, "_db_active", active)
    monkeypatch.setattr(ps, "_db_insert_active", insert)
    monkeypatch.setattr(ps, "_db_activate", activate)
    monkeypatch.setattr(ps, "_db_list", lst)
    monkeypatch.setattr(ps, "_active", None)
    monkeypatch.setattr(gs, "_rules", [])
    return versions


@arun
async def test_env_is_ignored(db, monkeypatch):
    monkeypatch.setenv("SYSTEM_PROMPT", "Sou {AGENT_NAME}")
    await ps.load()
    assert db == [] and ps.get_system_prompt() == ""


@arun
async def test_no_version_no_seed(db):
    await ps.load()
    assert db == [] and ps.get_system_prompt() == "" and ps.active_info() is None
    assert ps.get_system_prompt("padrão") == "padrão"


@arun
async def test_save_changes_without_restart_and_activate(db):
    await ps.save("v1", "ana")
    assert ps.get_system_prompt() == "v1"
    v2 = await ps.save("v2", "bia")
    assert ps.get_system_prompt() == "v2" and ps.active_info()["id"] == v2["id"]
    await ps.activate(1)
    assert ps.get_system_prompt() == "v1"
    assert [v["id"] for v in await ps.list_versions()] == [2, 1]
    with pytest.raises(ps.PromptNotFound):
        await ps.activate(99)


@arun
async def test_save_rejects_empty(db):
    with pytest.raises(ps.PromptError):
        await ps.save("   ")


@arun
async def test_instruction_block_appended(db, monkeypatch):
    await ps.save("base", "x")
    monkeypatch.setattr(gs, "_rules", gs._build([{
        "id": 1, "name": "i", "scope": "prompt", "action": "instruct", "response": None,
        "instruction": "Seja breve.", "priority": 1, "enabled": True,
        "match_type": None, "pattern": None}]))
    out = ps.get_system_prompt()
    assert out.startswith("base") and "Regras de comportamento" in out and "Seja breve." in out
