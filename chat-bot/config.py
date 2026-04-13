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

# --- CONTROLE DE ACESSO ---
# Converte a string "True" ou "False" do .env para um booleano real do Python
RESPONDER_QUALQUER_NUMERO = os.getenv("RESPONDER_QUALQUER_NUMERO", "False").lower() in ("true", "1", "t")

# Pega a string com os números e transforma em uma lista real, removendo espaços extras
_numeros_str = os.getenv("NUMEROS_PERMITIDOS", "")
NUMEROS_PERMITIDOS = [num.strip() for num in _numeros_str.split(",") if num.strip()]