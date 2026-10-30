"""Base de conhecimento (RAG) do painel: API JSON /admin/api/knowledge* e página."""

import asyncio

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from pydantic import BaseModel

from config import KNOWLEDGE_MAX_CHARS
from routes.admin_common import render, require_admin, verify_csrf
from services import access_log_service, knowledge_service
from services.knowledge_service import KnowledgeError, KnowledgeNotFound

router = APIRouter(prefix="/admin", tags=["admin"])


class KnowledgeCreate(BaseModel):
    title: str
    content: str


class KnowledgeUpdate(BaseModel):
    title: str | None = None
    content: str | None = None


async def _call(coro):
    """Converte erros do service em respostas HTTP."""
    try:
        return await coro
    except KnowledgeError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except KnowledgeNotFound:
        raise HTTPException(status_code=404, detail="Documento não encontrado.")


@router.get("/knowledge", response_class=HTMLResponse)
async def knowledge_page(request: Request, admin: str = Depends(require_admin)):
    return render(request, "knowledge.html", max_chars=KNOWLEDGE_MAX_CHARS)


@router.get("/api/knowledge", dependencies=[Depends(require_admin)])
async def list_documents():
    return await _call(knowledge_service.list_documents())


# /search antes de /{doc_id} para não ser capturada como id
@router.get("/api/knowledge/search", dependencies=[Depends(require_admin)])
async def search(q: str):
    context, metadata = await asyncio.to_thread(knowledge_service.search, q)
    return {"context": context, "metadata": metadata}


@router.get("/api/knowledge/{doc_id}", dependencies=[Depends(require_admin)])
async def get_document(doc_id: str):
    return await _call(knowledge_service.get_document(doc_id))


@router.post("/api/knowledge", status_code=201, dependencies=[Depends(require_admin), Depends(verify_csrf)])
async def create_document(body: KnowledgeCreate, admin: str = Depends(require_admin)):
    doc = await _call(knowledge_service.create_document(body.title, body.content))
    access_log_service.log_admin(admin, "knowledge_create", f"doc={doc.get('id', '')}")
    return doc


@router.post("/api/knowledge/upload", status_code=201, dependencies=[Depends(require_admin), Depends(verify_csrf)])
async def upload_document(file: UploadFile = File(...), title: str = Form(""),
                          admin: str = Depends(require_admin)):
    raw = await file.read(KNOWLEDGE_MAX_CHARS * 4 + 1)
    try:
        content = raw.decode("utf-8")
    except UnicodeDecodeError:
        raise HTTPException(status_code=415, detail="Envie um arquivo de texto UTF-8 (.txt ou .md).")
    name = (file.filename or "documento").rsplit(".", 1)[0]
    doc = await _call(knowledge_service.create_document(title.strip() or name, content))
    access_log_service.log_admin(admin, "knowledge_create", f"doc={doc.get('id', '')}")
    return doc


@router.put("/api/knowledge/{doc_id}", dependencies=[Depends(require_admin), Depends(verify_csrf)])
async def update_document(doc_id: str, body: KnowledgeUpdate, admin: str = Depends(require_admin)):
    doc = await _call(knowledge_service.update_document(doc_id, body.title, body.content))
    access_log_service.log_admin(admin, "knowledge_update", f"doc={doc_id}")
    return doc


@router.delete("/api/knowledge/{doc_id}", status_code=204, dependencies=[Depends(require_admin), Depends(verify_csrf)])
async def delete_document(doc_id: str, admin: str = Depends(require_admin)):
    await _call(knowledge_service.delete_document(doc_id))
    access_log_service.log_admin(admin, "knowledge_delete", f"doc={doc_id}")
    return Response(status_code=204)
