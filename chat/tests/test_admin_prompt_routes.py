import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import admin_prompt, admin_skills
from routes.admin_common import require_admin, verify_csrf
from services import guardrail_service as gs
from services import prompt_service as ps
from services import skill_service as ss


@pytest.fixture
def client(monkeypatch):
    versions, rules = [], []

    async def lst():
        return list(reversed(versions))

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

    async def g_list():
        return list(rules)

    async def g_insert(d):
        rules.append({**d, "id": len(rules) + 1, "created_at": None})
        return rules[-1]

    async def g_delete(i):
        rules[:] = [r for r in rules if r["id"] != i]

    skills = {"consulta-academica": {"slug": "consulta-academica", "name": "Consulta acadêmica",
              "description": "", "tools": [], "body": "b", "updated_at": None}}

    async def s_list():
        return list(skills.values())

    async def s_get(slug):
        return skills.get(slug)

    monkeypatch.setattr(ss, "_db_list", s_list)
    monkeypatch.setattr(ss, "_db_get", s_get)
    monkeypatch.setattr(ps, "_db_list", lst)
    monkeypatch.setattr(ps, "_db_insert_active", insert)
    monkeypatch.setattr(ps, "_db_activate", activate)
    monkeypatch.setattr(ps, "_active", None)
    monkeypatch.setattr(gs, "_db_list", g_list)
    monkeypatch.setattr(gs, "_db_insert", g_insert)
    monkeypatch.setattr(gs, "_db_delete", g_delete)
    monkeypatch.setattr(gs, "_rules", [])
    app = FastAPI()
    app.include_router(admin_prompt.router)
    app.include_router(admin_skills.router)
    app.dependency_overrides[require_admin] = lambda: "admin"
    app.dependency_overrides[verify_csrf] = lambda: None
    return TestClient(app, follow_redirects=False)


def test_prompt_save_activate_and_escape(client):
    r = client.post("/admin/prompt", data={"content": "<script>alert(1)</script>"})
    assert r.status_code == 303
    page = client.get("/admin/prompt").text
    assert "<script>alert(1)</script>" not in page and "&lt;script&gt;" in page
    client.post("/admin/prompt", data={"content": "dois"})
    assert ps.get_system_prompt() == "dois"
    assert client.post("/admin/prompt/1/activate").status_code == 303
    assert ps.get_system_prompt() == "<script>alert(1)</script>"
    assert client.post("/admin/prompt/9/activate").status_code == 404
    assert client.post("/admin/prompt", data={"content": " "}).status_code == 422


def test_guardrail_crud_and_test(client):
    form = {"name": "n", "scope": "output", "match_type": "keyword", "pattern": "segredo",
            "action": "mask", "priority": "1", "enabled": "on"}
    assert client.post("/admin/guardrails", data=form).status_code == 303
    page = client.get("/admin/skills").text
    assert "segredo" in page and "Consulta acadêmica" in page
    res = client.post("/admin/api/guardrails/test", json={"text": "o segredo"}).json()
    assert res["output"]["text"] == "o ***"
    bad = client.post("/admin/guardrails", data={**form, "match_type": "regex", "pattern": "(a+)+"})
    assert bad.status_code == 422
    assert client.post("/admin/guardrails/1/delete").status_code == 303
    assert client.post("/admin/api/guardrails/test", json={"text": "o segredo"}).json()["output"]["text"] == "o segredo"
