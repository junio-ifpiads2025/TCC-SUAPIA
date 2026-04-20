import os
import requests
import time
from dotenv import load_dotenv
from services import logger

load_dotenv()

# Pegamos a URL base do WAHA (ex: http://localhost:3000)
# Para podermos usar endpoints diferentes (/api/sendText e /api/sendImage)
WAHA_BASE_URL = os.getenv("WAHA_BASE_URL", "http://localhost:3000")

def enviar_mensagem_waha(chat_id: str, texto: str):
    """Envia uma mensagem de texto simples via WAHA."""
    url = f"{WAHA_BASE_URL}/api/sendText"
    payload = {
        "chatId": chat_id,
        "text": texto,
        "session": "default"
    }
    try:
        response = requests.post(url, json=payload)
        logger.success("WAHA", f"Texto enviado para {chat_id}")
        return response.json()
    except Exception as e:
        logger.error("WAHA", f"Erro ao enviar texto: {e}")
        return None

def enviar_imagem_waha(chat_id: str, image_url: str):
    """Envia uma imagem usando o endpoint /api/sendImage do WAHA."""
    url = f"{WAHA_BASE_URL}/api/sendImage"
    
    # O WAHA consegue baixar e enviar imagens a partir de URLs públicas
    # (como são as imagens dos manuais do IFPI)
    payload = {
        "chatId": chat_id,
        "file": {
            "url": image_url # A URL direta da imagem
        },
        "session": "default"
    }
    
    try:
        logger.image_log(chat_id, image_url)
        response = requests.post(url, json=payload)
        time.sleep(1)
        return response.json()
    except Exception as e:
        logger.error("WAHA", f"Erro ao enviar imagem: {e}")
        return None