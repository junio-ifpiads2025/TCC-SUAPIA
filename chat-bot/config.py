import os
from dotenv import load_dotenv

load_dotenv()

# --- VARIÁVEIS DE AMBIENTE ---

WAHA_URL = os.getenv("WAHA_URL", "http://localhost:3000/api/sendText")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sua-chave-openai")
PGVECTOR_CONNECTION_STRING = os.getenv(
    "PGVECTOR_CONNECTION_STRING",
    "postgresql+psycopg://admin:adminpassword@localhost:5432/vetordatabase"
)
PGVECTOR_COLLECTION = os.getenv("PGVECTOR_COLLECTION", "manuais_suap_ifpi")

# --- SUAP ---
SUAP_BASE_URL = os.getenv("SUAP_BASE_URL", "https://suap.ifpi.edu.br")
SUAP_TOKEN = os.getenv("SUAP_TOKEN", "")

# --- AUTENTICAÇÃO / SESSÃO ---
REDIS_URL = os.getenv("REDIS_URL", "redis://localhost:6379")
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "28800"))  # fallback 8h (RN02)
MAX_DAILY_MESSAGES = int(os.getenv("MAX_DAILY_MESSAGES", "25"))        # RN06

# --- CONTROLE DE ACESSO ---
RESPONDER_QUALQUER_NUMERO = os.getenv("RESPONDER_QUALQUER_NUMERO", "False").lower() in ("true", "1", "t")

_numeros_str = os.getenv("NUMEROS_PERMITIDOS", "")
NUMEROS_PERMITIDOS = [num.strip() for num in _numeros_str.split(",") if num.strip()]