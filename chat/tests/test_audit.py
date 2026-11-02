import asyncio

import pytest
from fastapi import Depends, FastAPI
from fastapi.responses import Response
from fastapi.testclient import TestClient

from routes.admin import audit as admin_audit, common
from routes.admin.common import require_admin, verify_csrf
from services.admin import audit_revert
from services.shared import audit_service, prompt_service as ps, skill_service as ss


@pytest.fixture
def skills(monkeypatch):
    rows = {}

    async def lst():
        return list(rows.values())

    async def get(slug):
        return dict(rows[slug]) if slug in rows else None

    async def insert(slug, v):
        rows[slug] = {"slug": slug, **v, "updated_at": None}
        return dict(rows[slug])

    async def update(slug, v):
        if slug not in rows:
            raise ss.SkillNotFound(slug)
        rows[slug].update(v)
        return dict(rows[slug])

    async def delete(slug):
        if rows.pop(slug, None) is None:
            raise ss.SkillNotFound(slug)

    for n, f in (("_db_list", lst), ("_db_get", get), ("_db_insert", insert),
                 ("_db_update", update), ("_db_delete", delete)):
        monkeypatch.setattr(ss, n, f)
    return rows


@pytest.fixture
def audit_store(monkeypatch, audit_rows):
    """Lê e marca as linhas da lista do conftest como se fossem a tabela."""
    async def get(entry_id):
        row = audit_rows[entry_id - 1]
        return {"id": entry_id, "reverted_by": None, **row}

    async def mark(entry_id, admin):
        audit_rows[entry_id - 1]["reverted_by"] = admin

    monkeypatch.setattr(audit_service, "_db_get", get)
    monkeypatch.setattr(audit_service, "_db_mark_reverted", mark)
    return audit_rows


def test_records_before_after_with_admin(skills, audit_rows):
    async def run():
        audit_service.current_admin.set("ana")
        await ss.create_skill("s1", {"name": "Um", "body": "a"})
        await ss.update_skill("s1", {"name": "Dois", "body": "b"})
    asyncio.run(run())
    create, upd = audit_rows
    assert create["admin"] == "ana" and create["before"] is None and create["after"]["name"] == "Um"
    assert upd["action"] == "update" and upd["entity_id"] == "s1"
    assert upd["before"]["name"] == "Um" and upd["after"]["name"] == "Dois"
    assert "updated_at" not in upd["after"]
    assert [c["field"] for c in audit_service.changes(upd)] == ["body", "name"]


def test_admin_unknown_outside_panel(skills, audit_rows):
    asyncio.run(ss.create_skill("s1", {"name": "Um", "body": "a"}))
    assert audit_rows[0]["admin"] == audit_service.UNKNOWN_ADMIN


def test_revert_update_and_create(skills, audit_store):
    async def run():
        await ss.create_skill("s1", {"name": "Um", "body": "a"})       # entrada 1
        await ss.update_skill("s1", {"name": "Dois", "body": "b"})     # entrada 2
        await audit_revert.revert(2, "bia")                             # entrada 3 (update)
        assert skills["s1"]["name"] == "Um"
        with pytest.raises(audit_revert.RevertError):
            await audit_revert.revert(2, "bia")
        await audit_revert.revert(1, "bia")                             # remove a criada
        assert "s1" not in skills
    asyncio.run(run())
    assert audit_store[1]["reverted_by"] == "bia" and audit_store[0]["reverted_by"] == "bia"
    assert audit_store[2]["action"] == "update" and audit_store[3]["action"] == "delete"


def test_revert_prompt_reactivates_previous(monkeypatch, audit_store):
    activated = []

    async def insert_active(content, author, name):
        return {"id": 7, "content": content, "agent_name": name, "author": author, "created_at": None}

    async def activate(version_id):
        activated.append(version_id)
        return {"id": version_id, "content": "antigo", "agent_name": None, "author": None, "created_at": None}

    monkeypatch.setattr(ps, "_db_insert_active", insert_active)
    monkeypatch.setattr(ps, "_db_activate", activate)
    monkeypatch.setattr(ps, "_active", {"id": 3, "content": "antigo", "agent_name": None,
                                        "author": None, "created_at": None})

    async def run():
        await ps.save("novo")
        await audit_revert.revert(1, "bia")
    asyncio.run(run())
    assert audit_store[0]["before"]["id"] == 3 and audit_store[0]["after"]["content"] == "novo"
    assert activated == [3]


def test_require_admin_sets_current_admin(monkeypatch):
    monkeypatch.setattr(common, "ADMIN_PASSWORD", "x")
    monkeypatch.setattr(common, "ADMIN_SESSION_SECRET", "s" * 32)
    app = FastAPI()

    @app.get("/admin/who")
    async def who(admin: str = Depends(require_admin)):
        return {"ctx": audit_service.current_admin.get()}

    resp = Response()
    common.create_session_cookie(resp, "root", bootstrap=True)
    cookie = resp.headers["set-cookie"].split(";")[0].split("=", 1)[1]
    c = TestClient(app)
    c.cookies.set(common.COOKIE_NAME, cookie, path="/admin")
    assert c.get("/admin/who").json() == {"ctx": "root"}


@pytest.fixture
def client(monkeypatch):
    calls = []

    async def list_entries(**kw):
        calls.append(kw)
        return [{"id": 1, "admin": "<b>ana</b>", "action": "update", "entity": "skill", "entity_id": "s1",
                 "before": {"name": "Um"}, "after": {"name": "Dois"}, "reverted_by": None, "created_at": None}]

    async def revert(entry_id, admin):
        if entry_id == 9:
            raise audit_revert.RevertError("Essa alteração já foi revertida.")
        calls.append(("revert", entry_id, admin))

    monkeypatch.setattr(audit_service, "list_entries", list_entries)
    monkeypatch.setattr(audit_revert, "revert", revert)
    app = FastAPI()
    app.include_router(admin_audit.router)
    app.dependency_overrides[require_admin] = lambda: "tester"
    app.dependency_overrides[verify_csrf] = lambda: None
    c = TestClient(app)
    c.calls = calls
    return c


def test_audit_page_filters_and_escapes(client):
    r = client.get("/admin/audit?entity=skill&admin_filter=ana&date_from=2026-01-02")
    assert r.status_code == 200
    assert "<b>ana</b>" not in r.text and "&lt;b&gt;ana&lt;/b&gt;" in r.text
    assert "Dois" in r.text and "Reverter" in r.text
    kw = client.calls[0]
    assert kw["entity"] == "skill" and kw["admin"] == "ana" and kw["date_from"].year == 2026


def test_audit_revert_route(client):
    r = client.post("/admin/audit/1/revert", follow_redirects=False)
    assert r.status_code == 303 and ("revert", 1, "tester") in client.calls
    r = client.post("/admin/audit/9/revert", follow_redirects=True)
    assert "já foi revertida" in r.text
