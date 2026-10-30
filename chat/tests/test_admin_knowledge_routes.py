import fakeredis
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes import admin_auth, admin_common
from routes.admin import router
from services import knowledge_service as ks


@pytest.fixture
def app(monkeypatch):
    monkeypatch.setattr(admin_common, "ADMIN_PASSWORD", "pw")
    monkeypatch.setattr(admin_common, "ADMIN_SESSION_SECRET", "segredo")
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)
    monkeypatch.setattr(admin_auth, "get_redis", lambda: fake)
    app = FastAPI()
    app.include_router(router)
    return app


@pytest.fixture
def client(app):
    """Cliente autenticado por sessão real, com CSRF no header."""
    c = TestClient(app, follow_redirects=False)
    assert c.post("/admin/login", data={"username": "admin", "password": "pw"}).status_code == 303
    token = c.get("/admin/knowledge").text.split('name="csrf-token" content="')[1].split('"')[0]
    c.headers["X-CSRF-Token"] = token
    return c


def test_requires_auth(app):
    c = TestClient(app, follow_redirects=False)
    assert c.get("/admin/api/knowledge").status_code == 401
    assert c.get("/admin/knowledge").status_code == 303


def test_mutation_requires_csrf(client, monkeypatch):
    async def fake_create(title, content):
        return {"id": "1"}

    monkeypatch.setattr(ks, "create_document", fake_create)
    del client.headers["X-CSRF-Token"]
    assert client.post("/admin/api/knowledge", json={"title": "t", "content": "c"}).status_code == 403


def test_create_and_validation_error(client, monkeypatch):
    async def fake_create(title, content):
        if not content.strip():
            raise ks.KnowledgeError("vazio")
        return {"id": "1", "title": title}

    monkeypatch.setattr(ks, "create_document", fake_create)
    assert client.post("/admin/api/knowledge", json={"title": "t", "content": "c"}).status_code == 201
    assert client.post("/admin/api/knowledge", json={"title": "t", "content": " "}).status_code == 422


def test_not_found_maps_to_404(client, monkeypatch):
    async def missing(doc_id):
        raise ks.KnowledgeNotFound(doc_id)

    monkeypatch.setattr(ks, "delete_document", missing)
    assert client.delete("/admin/api/knowledge/x").status_code == 404


def test_search_route_not_shadowed(client, monkeypatch):
    monkeypatch.setattr(ks, "search", lambda q: ("ctx " + q, [{"a": 1}]))
    r = client.get("/admin/api/knowledge/search", params={"q": "oi"})
    assert r.status_code == 200 and r.json()["context"] == "ctx oi"


def test_upload_rejects_binary_and_uses_filename_as_title(client, monkeypatch):
    seen = {}

    async def fake_create(title, content):
        seen.update(title=title, content=content)
        return {"id": "1"}

    monkeypatch.setattr(ks, "create_document", fake_create)
    r = client.post("/admin/api/knowledge/upload", files={"file": ("regras.md", "# oi".encode())})
    assert r.status_code == 201 and seen["title"] == "regras"
    r = client.post("/admin/api/knowledge/upload", files={"file": ("x.bin", b"\xff\xfe\x00")})
    assert r.status_code == 415
