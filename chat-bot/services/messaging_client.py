"""
Contrato de mensageria do SUAP-IA.

Define as funções públicas de envio de mensagens. Nenhuma rota ou serviço
deve importar diretamente do provider (waha_client, etc.) — sempre importam
deste módulo. Isso permite trocar o provider de mensageria alterando apenas
os imports abaixo, sem modificar nenhuma outra parte da aplicação.

Contrato público:
  enviar_texto(chat_id: str, texto: str) -> None          — síncrono
  enviar_imagem(chat_id: str, url: str) -> None           — síncrono
  enviar_texto_async(chat_id: str, texto: str) -> None    — assíncrono (await)

Para trocar de provider: implemente as 3 funções em services/<provider>_client.py
e atualize os imports abaixo.
"""

from services.waha_client import (
    enviar_mensagem_waha as enviar_texto,
    enviar_imagem_waha as enviar_imagem,
    enviar_mensagem_waha_async as enviar_texto_async,
)
