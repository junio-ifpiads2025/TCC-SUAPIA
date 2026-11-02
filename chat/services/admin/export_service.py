"""
Exportações do painel em CSV e JSON (logs, uso, casos de qualidade, auditoria,
base de conhecimento).

- CSV gerado em streaming com o módulo `csv` da biblioteca padrão.
- Injeção de fórmula: célula de texto que começa com `=`, `+`, `-`, `@`, TAB ou
  CR ganha um apóstrofo na frente, para planilhas não a executarem.
- LGPD (minimização): o `chat_id` sai mascarado (só os últimos dígitos) e o nome
  do usuário não é exportado. Quem exporta fica registrado no log de acesso.
"""

import csv
import io
import json
from collections.abc import Iterable, Iterator
from datetime import datetime

from sqlalchemy import select

from utils.security import mask_chat_id
from models.database import AsyncSessionLocal, KnowledgeDocument, QaCase

_FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
QA_KINDS = ("up", "down", "no_answer")

LOG_COLUMNS = ["created_at", "chat_id", "matricula", "provider", "event", "detail", "duration_ms"]
USAGE_COLUMNS = ["date", "messages", "users", "calls", "prompt", "completion", "total"]
QA_COLUMNS = ["id", "created_at", "kind", "status", "chat_id", "question", "answer", "note"]
AUDIT_COLUMNS = ["id", "created_at", "admin", "entity", "action", "entity_id", "reverted_by", "before", "after"]


def neutralize(value):
    """Valor seguro para uma célula de planilha (só texto é alterado)."""
    if isinstance(value, str) and value.startswith(_FORMULA_START):
        return "'" + value
    return value


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, default=str)
    return neutralize(value) if isinstance(value, str) else value


def csv_lines(rows: Iterable[dict], columns: list[str]) -> Iterator[str]:
    """Cabeçalho + uma linha CSV por registro (gerador, para StreamingResponse)."""
    buf = io.StringIO()
    writer = csv.writer(buf)

    def flush() -> str:
        line = buf.getvalue()
        buf.seek(0)
        buf.truncate(0)
        return line

    writer.writerow(columns)
    yield flush()
    for row in rows:
        writer.writerow([_cell(row.get(c)) for c in columns])
        yield flush()


def mask_rows(rows: list[dict]) -> list[dict]:
    """Cópia dos registros com `chat_id` mascarado e sem `nome`."""
    out = []
    for r in rows:
        r = {k: v for k, v in r.items() if k != "nome"}
        r["chat_id"] = mask_chat_id(r.get("chat_id"))
        out.append(r)
    return out


# ── Consultas próprias das exportações ───────────────────────────────────────

async def _db_qa_cases(kind: str | None, limit: int) -> list[dict]:
    stmt = select(QaCase).order_by(QaCase.id.desc()).limit(limit)
    if kind in QA_KINDS:
        stmt = stmt.where(QaCase.kind == kind)
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(stmt)).scalars().all()
    return [{"id": r.id, "created_at": r.created_at, "kind": r.kind, "status": r.status,
             "chat_id": r.chat_id, "question": r.question, "answer": r.answer, "note": r.note}
            for r in rows]


async def _db_knowledge() -> list[dict]:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(KnowledgeDocument).order_by(KnowledgeDocument.title))).scalars().all()
    return [{"id": d.id, "title": d.title, "content": d.content,
             "created_at": d.created_at.isoformat() if d.created_at else None,
             "updated_at": d.updated_at.isoformat() if d.updated_at else None}
            for d in rows]


async def qa_cases(kind: str | None = None, limit: int = 5000) -> list[dict]:
    return mask_rows(await _db_qa_cases(kind, limit))


async def knowledge_json() -> str:
    """Todos os documentos da base de conhecimento, com conteúdo, em JSON."""
    return json.dumps({"documents": await _db_knowledge()}, ensure_ascii=False, indent=2)
