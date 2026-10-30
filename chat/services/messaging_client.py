"""
Fachada de mensageria do SUAP-IA.

Ponto único de envio de mensagens: rotas e serviços importam apenas daqui, sem
saber qual plataforma (WhatsApp, Telegram...) atende cada chat_id. O provider
é escolhido pelo chat_id (ver services/providers/__init__.py) e o contrato que
ele implementa está em services/providers/base.py.

Funções públicas (todas assíncronas):
  enviar_texto_async(chat_id, texto)
  enviar_imagem_async(chat_id, url)
  marcar_lida_async(chat_id, message_id=None)
  iniciar_digitacao_async(chat_id)
"""

from services.providers import resolve


async def enviar_texto_async(chat_id: str, texto: str) -> None:
    provider, native_id = resolve(chat_id)
    await provider.enviar_texto(native_id, texto)


async def enviar_imagem_async(chat_id: str, url: str) -> None:
    provider, native_id = resolve(chat_id)
    await provider.enviar_imagem(native_id, url)


async def marcar_lida_async(chat_id: str, message_id: str | None = None) -> None:
    provider, native_id = resolve(chat_id)
    await provider.marcar_lida(native_id, message_id)


async def iniciar_digitacao_async(chat_id: str) -> None:
    provider, native_id = resolve(chat_id)
    await provider.iniciar_digitacao(native_id)
