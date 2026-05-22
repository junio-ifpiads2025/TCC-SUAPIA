"""
Modelos ORM e configuração do banco de dados PostgreSQL.

Utiliza SQLAlchemy com suporte assíncrono (asyncpg/psycopg) e a extensão
pgvector para busca vetorial (usada pelo pipeline RAG em módulo separado).

Tabelas gerenciadas aqui:
- user_auth     : vínculo entre chat_id do WhatsApp e matrícula SUAP.
- message_queue : fila persistente de mensagens a processar (Épico 3).
"""

from datetime import datetime, timezone
from sqlalchemy import String, DateTime, Text, Index, text
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


class MessageQueue(Base):
    """
    Fila persistente de mensagens recebidas via WhatsApp.

    Ciclo de vida de uma mensagem:
      pending → processing → completed
                           ↘ failed  (erro ou timeout)

    O índice composto (status, created_at) otimiza a query principal de
    process_next(), que filtra por status e ordena por criação (FIFO).
    """
    __tablename__ = "message_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[str] = mapped_column(String(100), nullable=False, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    # Status possíveis: 'pending', 'processing', 'completed', 'failed'
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    # Preenchido apenas em caso de falha, com a descrição do erro ou 'timeout'
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    # Atualizado manualmente em cada transição de status para rastrear duração
    updated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
        onupdate=lambda: datetime.now(timezone.utc),
    )

    __table_args__ = (
        # Índice composto para acelerar a query de busca por status + ordem FIFO (RN07)
        Index("ix_message_queue_status_created_at", "status", "created_at"),
    )


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
