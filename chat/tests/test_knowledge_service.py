import asyncio

import pytest

from models.database import KnowledgeDocument
from services import knowledge_service as ks


class FakeStore:
    """Vector store em memória com a mesma superfície usada pelo serviço."""

    def __init__(self):
        self.chunks = {}

    def add_documents(self, docs, ids):
        for d, i in zip(docs, ids):
            self.chunks[i] = d

    def delete(self, ids):
        for i in ids:
            self.chunks.pop(i, None)

    def similarity_search(self, query, k):
        return [d for d in self.chunks.values() if query.lower() in d.page_content.lower()][:k]


class FakeSession:
    """Substitui AsyncSessionLocal: persiste KnowledgeDocument num dict compartilhado."""

    rows: dict = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def add(self, doc):
        self.rows[doc.id] = doc

    async def get(self, model, doc_id):
        return self.rows.get(doc_id)

    async def delete(self, doc):
        self.rows.pop(doc.id, None)

    async def commit(self):
        pass


@pytest.fixture
def env(monkeypatch):
    store = FakeStore()
    FakeSession.rows = {}
    monkeypatch.setattr(ks, "_get_vector_store", lambda: store)
    monkeypatch.setattr(ks, "AsyncSessionLocal", FakeSession)
    return store


def run(coro):
    return asyncio.run(coro)


def test_create_indexes_chunks_and_prefixes_title(env):
    doc = run(ks.create_document("Calendário 2026", "Matrículas abrem em 10/02."))
    assert doc["chunk_count"] == 1
    (chunk,) = env.chunks.values()
    assert chunk.page_content.startswith("Documento: Calendário 2026")
    assert chunk.metadata["doc_id"] == doc["id"]


def test_update_shrinking_text_removes_stale_chunks(env):
    longo = "\n\n".join(f"Parágrafo {i}. " + "x" * 700 for i in range(5))
    doc = run(ks.create_document("Regras", longo))
    assert doc["chunk_count"] > 1
    atualizado = run(ks.update_document(doc["id"], content="Texto curto."))
    assert atualizado["chunk_count"] == 1
    assert len(env.chunks) == 1


def test_update_title_only_keeps_content(env):
    doc = run(ks.create_document("Velho", "Conteúdo original."))
    run(ks.update_document(doc["id"], title="Novo"))
    assert run(ks.get_document(doc["id"]))["content"] == "Conteúdo original."
    assert next(iter(env.chunks.values())).metadata["titulo"] == "Novo"


def test_delete_removes_chunks_and_row(env):
    doc = run(ks.create_document("Temp", "algo"))
    run(ks.delete_document(doc["id"]))
    assert env.chunks == {} and FakeSession.rows == {}
    with pytest.raises(ks.KnowledgeNotFound):
        run(ks.get_document(doc["id"]))


def test_validation(env):
    with pytest.raises(ks.KnowledgeError):
        run(ks.create_document("  ", "x"))
    with pytest.raises(ks.KnowledgeError):
        run(ks.create_document("t", "   "))
    with pytest.raises(ks.KnowledgeError):
        run(ks.create_document("t", "x" * (ks.KNOWLEDGE_MAX_CHARS + 1)))


def test_failed_db_write_rolls_back_vectors(env, monkeypatch):
    async def boom(self):
        raise RuntimeError("db down")

    monkeypatch.setattr(FakeSession, "commit", boom)
    with pytest.raises(RuntimeError):
        run(ks.create_document("T", "conteúdo"))
    assert env.chunks == {}


def test_search_returns_context_and_empty_on_error(env, monkeypatch):
    run(ks.create_document("Contatos", "Secretaria: ramal 204."))
    contexto, meta = ks.search("ramal")
    assert "ramal 204" in contexto and meta[0]["titulo"] == "Contatos"

    monkeypatch.setattr(ks, "_get_vector_store", lambda: (_ for _ in ()).throw(RuntimeError("x")))
    assert ks.search("ramal") == ("", [])
