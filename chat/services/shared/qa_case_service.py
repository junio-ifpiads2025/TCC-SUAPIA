"""
Casos de qualidade (tabela `qa_case`): avaliações dos usuários e perguntas sem resposta.

- `up`        : resposta útil. Guarda só o chat_id e a data (LGPD: sem conteúdo).
- `down`      : resposta não útil. Guarda pergunta, resposta e trechos usados.
- `no_answer` : o assistente não encontrou resposta. Guarda pergunta, resposta e trechos.

Gravado pelo atendimento (services/chat/feedback_service, queue_service) e
revisado no painel (/admin/quality). Purgado após QA_CASE_RETENTION_DAYS.
"""

import re
import unicodedata
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select

import config
from utils.security import mask_chat_id
from models.database import AsyncSessionLocal, QaCase
from services.shared import audit_service, logger

KINDS = ("up", "down", "no_answer")
STATUSES = ("new", "reviewed", "converted")
MAX_CHUNKS = 10
MAX_NOTE_LEN = 2000
# Similaridade mínima (Jaccard das palavras) para agrupar perguntas sem resposta
SIMILARITY = 0.5
_STOPWORDS = {"como", "qual", "quais", "onde", "quando", "para", "pelo", "pela", "sobre", "minha",
              "meus", "minhas", "esse", "essa", "este", "esta", "isso", "fazer", "posso", "tenho",
              "voce", "pode", "favor", "gostaria", "saber", "preciso", "queria"}


class QaCaseNotFound(LookupError):
    """Caso inexistente."""


def _to_dict(c: QaCase) -> dict:
    return {"id": c.id, "kind": c.kind, "chat_id": c.chat_id, "question": c.question,
            "answer": c.answer, "chunks": c.chunks or [], "status": c.status, "note": c.note,
            "created_at": c.created_at}


def _chunk_summary(chunks: list | None) -> list[dict]:
    """Só metadados identificadores dos trechos (sem texto), no máximo MAX_CHUNKS."""
    keep = ("fonte", "titulo", "doc_id", "source", "title", "chunk_index")
    return [{k: c[k] for k in keep if k in c} for c in (chunks or [])[:MAX_CHUNKS] if isinstance(c, dict)]


# ── Persistência (isolada para facilitar testes) ─────────────────────────────

async def _db_insert(row: dict) -> None:
    async with AsyncSessionLocal() as s:
        s.add(QaCase(**row))
        await s.commit()


async def _db_list(kind: str, limit: int) -> list[dict]:
    stmt = select(QaCase).where(QaCase.kind == kind).order_by(QaCase.id.desc()).limit(limit)
    async with AsyncSessionLocal() as s:
        return [_to_dict(c) for c in (await s.execute(stmt)).scalars().all()]


async def _db_get(case_id: int) -> dict | None:
    async with AsyncSessionLocal() as s:
        c = await s.get(QaCase, case_id)
        return _to_dict(c) if c else None


async def _db_update(case_id: int, values: dict) -> dict:
    async with AsyncSessionLocal() as s:
        c = await s.get(QaCase, case_id)
        if c is None:
            raise QaCaseNotFound(case_id)
        for k, v in values.items():
            setattr(c, k, v)
        await s.commit()
        await s.refresh(c)
        return _to_dict(c)


async def _db_counts(since: datetime) -> dict[str, int]:
    stmt = (select(QaCase.kind, func.count()).where(QaCase.created_at >= since)
            .group_by(QaCase.kind))
    async with AsyncSessionLocal() as s:
        return {k: n for k, n in (await s.execute(stmt)).all()}


async def _db_purge(before: datetime) -> int:
    async with AsyncSessionLocal() as s:
        res = await s.execute(delete(QaCase).where(QaCase.created_at < before))
        await s.commit()
        return res.rowcount or 0


# ── Gravação (atendimento) ───────────────────────────────────────────────────

async def record(kind: str, chat_id: str, question: str | None = None,
                 answer: str | None = None, chunks: list | None = None) -> None:
    """Grava um caso. Em `up` o conteúdo é descartado. Falha de banco só gera aviso."""
    if kind not in KINDS:
        raise ValueError(f"kind inválido: {kind}")
    if kind == "up":
        question = answer = chunks = None
    row = {"kind": kind, "chat_id": chat_id, "question": question, "answer": answer,
           "chunks": None if chunks is None else _chunk_summary(chunks)}
    try:
        await _db_insert(row)
    except Exception as e:
        logger.warn("QUALIDADE", f"Falha ao gravar caso ({kind}): {e}")


# ── Painel ───────────────────────────────────────────────────────────────────

async def list_cases(kind: str, limit: int = 200) -> list[dict]:
    if kind not in KINDS:
        raise ValueError(f"kind inválido: {kind}")
    rows = await _db_list(kind, limit)
    for r in rows:
        r["chat_id_masked"] = mask_chat_id(r.pop("chat_id"))
    return rows


async def satisfaction(days: int = 30) -> dict:
    """Contagem por tipo no período e % de respostas úteis entre as avaliadas."""
    counts = await _db_counts(datetime.now(timezone.utc) - timedelta(days=days))
    up, down = counts.get("up", 0), counts.get("down", 0)
    rated = up + down
    return {"days": days, "up": up, "down": down, "no_answer": counts.get("no_answer", 0),
            "rate": round(100 * up / rated) if rated else None}


async def update_case(case_id: int, status: str, note: str | None) -> dict:
    """Muda status e nota do caso (auditado)."""
    if status not in STATUSES:
        raise ValueError("Status inválido.")
    note = (note or "").strip() or None
    if note and len(note) > MAX_NOTE_LEN:
        raise ValueError(f"Nota longa demais (máx. {MAX_NOTE_LEN} caracteres).")
    before = await _db_get(case_id)
    if before is None:
        raise QaCaseNotFound(case_id)
    row = await _db_update(case_id, {"status": status, "note": note})
    await audit_service.record("update", "qa_case", case_id,
                               {"status": before["status"], "note": before["note"]},
                               {"status": row["status"], "note": row["note"]})
    return row


async def get_case(case_id: int) -> dict:
    row = await _db_get(case_id)
    if row is None:
        raise QaCaseNotFound(case_id)
    return row


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", (text or "").lower())
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return re.sub(r"[^a-z0-9 ]+", " ", text)


def _words(text: str) -> frozenset[str]:
    return frozenset(w for w in _normalize(text).split() if len(w) >= 4 and w not in _STOPWORDS)


def group_similar(cases: list[dict]) -> list[dict]:
    """
    Agrupa perguntas parecidas (Jaccard das palavras significativas >= SIMILARITY).
    Devolve [{question, count, ids}] do grupo maior para o menor; a pergunta exibida
    é a primeira (mais recente) do grupo.
    """
    groups: list[dict] = []
    for c in cases:
        words = _words(c.get("question") or "")
        for g in groups:
            union = words | g["words"]
            if union and len(words & g["words"]) / len(union) >= SIMILARITY:
                g["count"] += 1
                g["ids"].append(c["id"])
                break
        else:
            groups.append({"question": c.get("question") or "", "words": words, "count": 1, "ids": [c["id"]]})
    groups.sort(key=lambda g: g["count"], reverse=True)
    return [{k: g[k] for k in ("question", "count", "ids")} for g in groups]


async def purge() -> int:
    """Remove casos mais antigos que QA_CASE_RETENTION_DAYS. Retorna quantos."""
    before = datetime.now(timezone.utc) - timedelta(days=config.QA_CASE_RETENTION_DAYS)
    n = await _db_purge(before)
    if n:
        logger.info("QUALIDADE", f"Purga: {n} caso(s) removidos")
    return n
