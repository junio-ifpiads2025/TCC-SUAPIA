import os
from dotenv import load_dotenv

load_dotenv()

# --- VARIÁVEIS DE AMBIENTE ---

WAHA_URL = os.getenv("WAHA_URL", "http://localhost:3000/api/sendText")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sua-chave-openai")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "minha_base_de_conhecimento")

# --- CONTROLE DE ACESSO ---
# Converte a string "True" ou "False" do .env para um booleano real do Python
RESPONDER_QUALQUER_NUMERO = os.getenv("RESPONDER_QUALQUER_NUMERO", "False").lower() in ("true", "1", "t")

# Pega a string com os números e transforma em uma lista real, removendo espaços extras
_numeros_str = os.getenv("NUMEROS_PERMITIDOS", "")
NUMEROS_PERMITIDOS = [num.strip() for num in _numeros_str.split(",") if num.strip()]