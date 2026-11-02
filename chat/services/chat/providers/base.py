"""
Contrato de provider de mensageria do SUAP-IA.

Um provider é o adaptador entre o SUAP-IA e uma plataforma de chat (WhatsApp via
WAHA, Telegram, etc.). O resto da aplicação só conhece esta interface: fila,
router, agente e rotas nunca importam código de plataforma.

Para criar um provider novo:
  1. Crie services/providers/<nome>.py com uma subclasse de MessagingProvider.
  2. Registre-a em services/providers/__init__.py (_BUILTIN).
  3. Habilite via MESSAGING_PROVIDERS=<nome> no .env e aponte o webhook da
     plataforma para POST /webhook/<nome>.

Métodos abstratos são obrigatórios; os demais têm no-op como padrão porque nem toda
plataforma tem o conceito (ex: Telegram não tem "lida" para bots).

Todos os métodos recebem o chat_id NATIVO da plataforma (sem prefixo de namespace).
O prefixo é aplicado/removido pelo registry.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import ClassVar

from fastapi import Request


class InvalidPayload(Exception):
    """Payload do webhook malformado (resulta em HTTP 400, RF09)."""


@dataclass(frozen=True)
class IncomingMessage:
    """Mensagem de texto recebida de um usuário, normalizada entre providers."""

    chat_id: str                    # identificador nativo do contato/conversa na plataforma
    text: str
    message_id: str | None = None   # usado por providers que suportam marcar como lida


class MessagingProvider(ABC):
    # Nome único do provider: usado na rota /webhook/<name>, em MESSAGING_PROVIDERS
    # e como prefixo do chat_id (<name>:<id_nativo>).
    name: ClassVar[str]

    # ── Obrigatórios ─────────────────────────────────────────────────────────

    @abstractmethod
    async def parse_webhook(self, request: Request) -> IncomingMessage | None:
        """
        Converte o request do webhook da plataforma em IncomingMessage.

        Retorna None para eventos que não são mensagem de texto de um usuário
        (ACKs, status, mensagens do próprio bot, mídia sem texto...).
        Levanta InvalidPayload se o payload estiver malformado ou a autenticação
        do webhook (secret/assinatura) falhar.
        """

    @abstractmethod
    async def enviar_texto(self, chat_id: str, texto: str) -> None:
        """Envia texto ao chat. Não deve levantar exceção: logue e retorne."""

    @abstractmethod
    async def enviar_imagem(self, chat_id: str, url: str) -> None:
        """Envia imagem a partir de uma URL pública. Não deve levantar exceção."""

    # ── Opcionais (padrão: no-op) ────────────────────────────────────────────

    async def startup(self) -> None:
        """Chamado na subida da aplicação (ex: registrar o webhook na plataforma)."""

    async def marcar_lida(self, chat_id: str, message_id: str | None = None) -> None:
        """Marca a mensagem do usuário como lida, se a plataforma suportar."""

    async def iniciar_digitacao(self, chat_id: str) -> None:
        """Mostra o indicador 'digitando...' durante o processamento do LLM."""
