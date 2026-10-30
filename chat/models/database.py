"""
Modelos ORM e configuração do banco de dados PostgreSQL.

Utiliza SQLAlchemy com suporte assíncrono (asyncpg/psycopg) e a extensão
pgvector para busca vetorial (usada pelo pipeline RAG em módulo separado).

Tabelas gerenciadas aqui:
- user_auth     : vínculo entre chat_id do WhatsApp e matrícula SUAP.
- knowledge_document : documentos da base de conhecimento do agente (CRUD admin).
- access_rule   : allowlist/blocklist de chat_ids (painel admin).
- access_log    : log de acesso/atendimento (painel admin).
- prompt_version: versões do system prompt (painel admin).
- guardrail     : regras de entrada/saída/prompt (painel admin).
- admin_user    : matrículas SUAP com acesso ao painel admin.
- llm_usage     : consumo de tokens por chamada à API do LLM.
"""

from datetime import datetime, timezone
from sqlalchemy import Boolean, Integer, String, DateTime, Text, Index, text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from config import PGVECTOR_CONNECTION_STRING

# Engine assíncrona compartilhada por toda a aplicação
engine = create_async_engine(PGVECTOR_CONNECTION_STRING, echo=False)

# Fábrica de sessões: expire_on_commit=False evita lazy-load após commit
AsyncSessionLocal = async_sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


class UserAuth(Base):
    """
    Persiste o vínculo entre o número de WhatsApp (chat_id) e a matrícula SUAP.

    O token de acesso ao SUAP NÃO é armazenado aqui — fica apenas no Redis
    com TTL controlado (RN01, RN03). Esta tabela serve para:
    - Associar matrícula ao chat_id após login bem-sucedido.
    - Permitir auditoria de quem usou o sistema.
    - Registrar a data/hora do aceite do Termo de Uso (exigência LGPD Art. 8º §5º).
    """
    __tablename__ = "user_auth"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    matricula: Mapped[str] = mapped_column(String(50), nullable=False)
    # Registra quando o usuário aceitou o Termo de Uso (LGPD Art. 8º §5º)
    terms_accepted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class KnowledgeDocument(Base):
    """
    Documento da base de conhecimento do agente (fonte da verdade do CRUD).

    O texto completo fica aqui; os chunks vetorizados ficam na coleção pgvector
    `KNOWLEDGE_COLLECTION`, com ids determinísticos derivados de (id, índice).
    `chunk_count` permite remover/atualizar os chunks sem varrer o índice vetorial.
    """
    __tablename__ = "knowledge_document"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    chunk_count: Mapped[int] = mapped_column(default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AccessRule(Base):
    """Allowlist e blocklist numa tabela. `block` sempre vence `allow`."""
    __tablename__ = "access_rule"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(100), unique=True, nullable=False, index=True)
    kind: Mapped[str] = mapped_column(String(10), nullable=False)  # 'allow' | 'block'
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AccessLog(Base):
    """
    Log de acesso. Eventos: received, blocked, denied, rate_limited,
    guardrail_input, guardrail_output, answered, failed, e `admin_*` (ações do painel,
    com chat_id=`admin:<usuário>`).
    """
    __tablename__ = "access_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    provider: Mapped[str | None] = mapped_column(String(30), nullable=True)
    event: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


class PromptVersion(Base):
    """Versão do system prompt; exatamente uma tem active=True."""
    __tablename__ = "prompt_version"

    id: Mapped[int] = mapped_column(primary_key=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    author: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class Skill(Base):
    """Skill do agente (instruções em markdown), editável no painel."""
    __tablename__ = "skill"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, onupdate=_now)


class Guardrail(Base):
    """
    Regra de guardrail.
    scope: input | output | prompt
    match_type: keyword | regex (só input/output)
    action: block | mask | replace | instruct (instruct só para prompt)
    """
    __tablename__ = "guardrail"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    scope: Mapped[str] = mapped_column(String(10), nullable=False)
    match_type: Mapped[str | None] = mapped_column(String(10), nullable=True)
    pattern: Mapped[str | None] = mapped_column(Text, nullable=True)
    action: Mapped[str] = mapped_column(String(10), nullable=False)
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    instruction: Mapped[str | None] = mapped_column(Text, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class AdminUser(Base):
    """Matrícula SUAP autorizada a entrar no painel (além do login de bootstrap do .env)."""
    __tablename__ = "admin_user"

    id: Mapped[int] = mapped_column(primary_key=True)
    matricula: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    added_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now)


class LlmUsage(Base):
    """Uma chamada à API do LLM: tokens consumidos, modelo e origem (agent/rag)."""
    __tablename__ = "llm_usage"

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[str] = mapped_column(String(20), nullable=False)
    model: Mapped[str] = mapped_column(String(60), nullable=False, index=True)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_now, index=True)


async def init_db() -> None:
    """Cria todas as tabelas no banco se ainda não existirem (idempotente)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # Migração manual: adiciona colunas novas a tabelas já existentes.
        # IF NOT EXISTS garante idempotência — seguro rodar a qualquer subida.
        await conn.execute(text(
            "ALTER TABLE user_auth "
            "ADD COLUMN IF NOT EXISTS terms_accepted_at TIMESTAMPTZ"
        ))
