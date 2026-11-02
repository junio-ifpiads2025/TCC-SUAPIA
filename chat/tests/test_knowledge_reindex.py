import asyncio

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from routes.admin import knowledge as admin_knowledge
from routes.admin.common import require_admin, verify_csrf
from services.shared import knowledge_service as ks


@pytest.fixture
def env(monkeypatch):
    docs = [{"id": "d1", "title": "A", "content": "um", "chunk_count": 3},
            {"id": "d2", "title": "B", "content": "dois", "chunk_count": 1}]
    progress, counts, indexed = [], {}, []

    async def all_docs():
        return docs

    async def set_count(doc_id, total):
        counts[doc_id] = total

    async def pset(data):
        progress.append(dict(data))

    async def pget():
        return progress[-1] if progress else None

    def indexar(doc_id, title, content, antigos):
        if doc_id == "d2":
            raise RuntimeError("embeddings fora")
        indexed.append((doc_id, antigos))
        return 2

    monkeypatch.setattr(ks, "_db_all_documents", all_docs)
    monkeypatch.setattr(ks, "_db_set_chunk_count", set_count)
    monkeypatch.setattr(ks, "_progress_set", pset)
    monkeypatch.setattr(ks, "_progress_get", pget)
    monkeypatch.setattr(ks, "_indexar", indexar)
    monkeypatch.setattr(ks, "_reindex_task", None)
    return progress, counts, indexed


def test_reindex_all_continues_after_failure(env):
    progress, counts, indexed = env
    final = asyncio.run(ks.reindex_all())
    assert indexed == [("d1", 3)] and counts == {"d1": 2}
    assert (final["status"], final["total"], final["done"], final["failed"]) == ("finished", 2, 1, 1)
    assert progress[0]["status"] == "running" and progress[0]["done"] == 0


def test_start_reindex_refuses_while_running(env, audit_rows):
    async def run():
        assert await ks.start_reindex() is True
        assert await ks.start_reindex() is False
        await ks._reindex_task
        return await ks.reindex_status()
    status = asyncio.run(run())
    assert status["status"] == "finished"
    assert [r["entity"] for r in audit_rows] == ["knowledge_reindex"]


def test_list_chunks_checks_document(monkeypatch):
    async def get_document(doc_id):
        if doc_id != "d1":
            raise ks.KnowledgeNotFound(doc_id)
        return {"id": "d1"}

    async def chunks(doc_id):
        return [{"id": "c0", "index": 0, "content": "Documento: A"}]

    monkeypatch.setattr(ks, "get_document", get_document)
    monkeypatch.setattr(ks, "_db_chunks", chunks)
    assert asyncio.run(ks.list_chunks("d1"))[0]["index"] == 0
    with pytest.raises(ks.KnowledgeNotFound):
        asyncio.run(ks.list_chunks("x"))


def test_routes(monkeypatch):
    state = {"started": 0}

    async def start():
        state["started"] += 1
        return state["started"] == 1

    async def status():
        return None

    async def chunks(doc_id):
        if doc_id == "x":
            raise ks.KnowledgeNotFound(doc_id)
        return [{"id": "c0", "index": 0, "content": "t"}]

    monkeypatch.setattr(ks, "start_reindex", start)
    monkeypatch.setattr(ks, "reindex_status", status)
    monkeypatch.setattr(ks, "list_chunks", chunks)
    app = FastAPI()
    app.include_router(admin_knowledge.router)
    app.dependency_overrides[require_admin] = lambda: "tester"
    app.dependency_overrides[verify_csrf] = lambda: None
    c = TestClient(app)
    assert c.get("/admin/api/knowledge/reindex").json() == {"status": "idle"}
    assert c.post("/admin/api/knowledge/reindex").status_code == 202
    assert c.post("/admin/api/knowledge/reindex").status_code == 409
    assert c.get("/admin/api/knowledge/d1/chunks").json()[0]["id"] == "c0"
    assert c.get("/admin/api/knowledge/x/chunks").status_code == 404
