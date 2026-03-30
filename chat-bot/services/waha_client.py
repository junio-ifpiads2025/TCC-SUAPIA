import requests
from config import WAHA_URL

def enviar_mensagem_waha(chat_id: str, texto: str):
    """Envia uma mensagem de texto para o WhatsApp via WAHA."""
    payload = {
        "chatId": chat_id,
        "text": texto,
        "session": "default"
    }
    try:
        response = requests.post(WAHA_URL, json=payload)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"Erro ao enviar mensagem para WAHA: {e}")
        return False