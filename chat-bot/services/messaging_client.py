"""
Contrato de mensageria do SUAP-IA.

Qualquer provider (WAHA, Meta, Twilio, etc.) deve implementar as 3 funções abaixo
com exatamente esta assinatura. As rotas importam daqui — nunca do provider diretamente.

Contrato:
  enviar_texto(chat_id: str, texto: str) -> None
  enviar_imagem(chat_id: str, url: str) -> None
  enviar_texto_async(chat_id: str, texto: str) -> Awaitable[None]

Para trocar de provider: implemente as 3 funções em services/<provider>_client.py
e atualize os imports abaixo. Nenhuma rota precisa ser alterada.
"""
from services.waha_client import (
    enviar_mensagem_waha as enviar_texto,
    enviar_imagem_waha as enviar_imagem,
    enviar_mensagem_waha_async as enviar_texto_async,
)
