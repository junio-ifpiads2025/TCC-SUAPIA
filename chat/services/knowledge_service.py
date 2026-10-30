"""
Base de conhecimento do agente (RAG editável pelo administrador).

Complementa os manuais do SUAP — que continuam em sua própria coleção e nunca
são alterados aqui — com documentos adicionados, atualizados e removidos em
tempo de execução (CRUD).

Armazenamento em duas camadas:
  - Postgres (`knowledge_document`): texto completo, título, nº de chunks.
  - pgvector (`KNOWLEDGE_COLLECTION`): chunks vetorizados para a busca semântica.

Os ids dos chunks são determinísticos (uuid5 de documento + índice), então
atualizar um documento regrava os mesmos ids (upsert) e remove só os que
sobraram, sem varrer o índice vetorial.
"""

import asyncio
import uuid
from functools import lru_cache

from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_postgres import PGVector
from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select

from config import (
    KNOWLEDGE_CHUNK_OVERLAP,
    KNOWLEDGE_CHUNK_SIZE,
    KNOWLEDGE_COLLECTION,
    KNOWLEDGE_EMBEDDING_MODEL,
    KNOWLEDGE_MAX_CHARS,
    KNOWLEDGE_TOP_K,
    OPENAI_API_KEY,
    PGVECTOR_CONNECTION_STRING,
)
from models.database import AsyncSessionLocal, KnowledgeDocument
from services import logger

# Namespace fixo: mesmo (documento, índice) gera sempre o mesmo id de chunk
_NAMESPACE_IDS = uuid.UUID("b3d1a7c2-6e0f-4c55-9a1e-2f7d8c4b9e01")

_SPLITTER = RecursiveCharacterTextSplitter(
    chunk_size=KNOWLEDGE_CHUNK_SIZE,
    chunk_overlap=KNOWLEDGE_CHUNK_OVERLAP,
    separators=["\n\n", "\n", ". ", "; ", " ", ""],
)


class KnowledgeError(ValueError):
    """Entrada inválida (título/conteúdo vazio ou grande demais)."""


class KnowledgeNotFound(LookupError):
    """Documento inexistente."""


@lru_cache(maxsize=1)
def _get_vector_store() -> PGVector:
    """Conexão lazy: o import do módulo não abre conexão com o banco."""
    return PGVector(
        embeddings=OpenAIEmbeddings(model=KNOWLEDGE_EMBEDDING_MODEL, api_key=OPENAI_API_KEY),
        collection_name=KNOWLEDGE_COLLECTION,
        connection=PGVECTOR_CONNECTION_STRING,
        use_jsonb=True,
    )


def _chunk_id(doc_id: str, index: int) -> str:
    return str(uuid.uuid5(_NAMESPACE_IDS, f"{doc_id}|{index}"))


def _validar(title: str, content: str) -> tuple[str, str]:
    title, content = title.strip(), content.strip()
    if not title:
        raise KnowledgeError("O título não pode ser vazio.")
    if not content:
        raise KnowledgeError("O conteúdo não pode ser vazio.")
    if len(title) > 200:
        raise KnowledgeError("O título excede 200 caracteres.")
    if len(content) > KNOWLEDGE_MAX_CHARS:
        raise KnowledgeError(f"O conteúdo excede {KNOWLEDGE_MAX_CHARS} caracteres.")
    return title, content


def _montar_chunks(doc_id: str, title: str, content: str) -> list[Document]:
    """Divide o texto e prefixa o título em cada chunk (melhora a recuperação)."""
    partes = _SPLITTER.split_text(content)
    return [
        Document(
            id=_chunk_id(doc_id, i),
            page_content=f"Documento: {title}\nConteúdo: {parte}",
            metadata={
                "fonte": "conhecimento",
                "doc_id": doc_id,
                "titulo": title,
                "chunk_index": i,
                "total_chunks": len(partes),
            },
        )
        for i, parte in enumerate(partes)
    ]


def _indexar(doc_id: str, title: str, content: str, chunks_antigos: int) -> int:
    """Upsert dos chunks novos e remoção dos que sobraram. Retorna o novo total."""
    store = _get_vector_store()
    chunks = _montar_chunks(doc_id, title, content)
    store.add_documents(chunks, ids=[c.id for c in chunks])
    sobras = [_chunk_id(doc_id, i) for i in range(len(chunks), chunks_antigos)]
    if sobras:
        store.delete(ids=sobras)
    return len(chunks)


def _desindexar(doc_id: str, chunk_count: int) -> None:
    if chunk_count:
        _get_vector_store().delete(ids=[_chunk_id(doc_id, i) for i in range(chunk_count)])


def _resumo(doc: KnowledgeDocument, incluir_conteudo: bool = False) -> dict:
    dados = {
        "id": doc.id,
        "title": doc.title,
        "chunk_count": doc.chunk_count,
        "chars": len(doc.content),
        "created_at": doc.created_at.isoformat() if doc.created_at else None,
        "updated_at": doc.updated_at.isoformat() if doc.updated_at else None,
    }
    if incluir_conteudo:
        dados["content"] = doc.content
    else:
        dados["preview"] = doc.content[:160]
    return dados


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

async def create_document(title: str, content: str) -> dict:
    """Cria o documento, vetoriza e persiste. Falha na indexação não deixa registro órfão."""
    title, content = _validar(title, content)
    doc_id = str(uuid.uuid4())
    total = await asyncio.to_thread(_indexar, doc_id, title, content, 0)
    try:
        async with AsyncSessionLocal() as session:
            doc = KnowledgeDocument(id=doc_id, title=title, content=content, chunk_count=total)
            session.add(doc)
            await session.commit()
    except Exception:
        await asyncio.to_thread(_desindexar, doc_id, total)
        raise
    logger.success("CONHECIMENTO", f"Documento criado: '{title}' ({total} chunk(s)).")
    return _resumo(doc)


async def update_document(doc_id: str, title: str | None = None, content: str | None = None) -> dict:
    """Atualiza título e/ou conteúdo e reindexa o documento inteiro."""
    async with AsyncSessionLocal() as session:
        doc = await session.get(KnowledgeDocument, doc_id)
        if doc is None:
            raise KnowledgeNotFound(doc_id)
        novo_titulo, novo_conteudo = _validar(
            doc.title if title is None else title,
            doc.content if content is None else content,
        )
        doc.chunk_count = await asyncio.to_thread(
            _indexar, doc_id, novo_titulo, novo_conteudo, doc.chunk_count
        )
        doc.title, doc.content = novo_titulo, novo_conteudo
        await session.commit()
    logger.success("CONHECIMENTO", f"Documento atualizado: '{novo_titulo}' ({doc.chunk_count} chunk(s)).")
    return _resumo(doc)


async def delete_document(doc_id: str) -> None:
    """Remove os chunks vetorizados e o registro."""
    async with AsyncSessionLocal() as session:
        doc = await session.get(KnowledgeDocument, doc_id)
        if doc is None:
            raise KnowledgeNotFound(doc_id)
        await asyncio.to_thread(_desindexar, doc_id, doc.chunk_count)
        await session.delete(doc)
        await session.commit()
    logger.success("CONHECIMENTO", f"Documento removido: '{doc.title}'.")


async def get_document(doc_id: str) -> dict:
    async with AsyncSessionLocal() as session:
        doc = await session.get(KnowledgeDocument, doc_id)
    if doc is None:
        raise KnowledgeNotFound(doc_id)
    return _resumo(doc, incluir_conteudo=True)


async def list_documents() -> list[dict]:
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            select(KnowledgeDocument).order_by(KnowledgeDocument.updated_at.desc())
        )
        return [_resumo(d) for d in result.scalars().all()]


# ---------------------------------------------------------------------------
# Busca (usada pelo agente; chamada síncrona, como o restante do loop ReAct)
# ---------------------------------------------------------------------------

def search(query: str, k: int = KNOWLEDGE_TOP_K) -> tuple[str, list[dict]]:
    """Retorna (contexto, metadados) dos chunks mais próximos. Vazio se nada/erro."""
    try:
        docs = _get_vector_store().similarity_search(query, k=k)
    except Exception as e:
        logger.error("CONHECIMENTO", f"Erro na busca: {e}")
        return "", []
    logger.info("CONHECIMENTO", f"{len(docs)} chunk(s) recuperado(s).")
    return "\n\n".join(d.page_content for d in docs), [d.metadata for d in docs]
