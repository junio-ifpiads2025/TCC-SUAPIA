"""
Configurações centralizadas da aplicação SUAP-IA.

Todas as variáveis de ambiente são lidas aqui e exportadas como constantes.
Nenhum outro módulo deve chamar os.getenv() diretamente — importam daqui.
Os valores padrão permitem executar localmente sem .env configurado.
"""

import os
from dotenv import load_dotenv

load_dotenv()

# --- WAHA (WhatsApp HTTP API) ---
WAHA_URL = os.getenv("WAHA_URL", "http://localhost:3000/api/sendText")

# --- LLM / EMBEDDINGS ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sua-chave-openai")

# --- BANCO DE DADOS (PostgreSQL + pgvector) ---
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
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8002")
# Tempo de vida da sessão em segundos; fallback 8h caso o SUAP não retorne expires_in (RN02)
SESSION_TTL_SECONDS = int(os.getenv("SESSION_TTL_SECONDS", "28800"))
# Limite de mensagens por usuário por dia (RN06)
MAX_DAILY_MESSAGES = int(os.getenv("MAX_DAILY_MESSAGES", "25"))

# --- PAINEL ADMIN ---
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")

# --- HISTÓRICO DE CONVERSA ---
# Número de pares (user + assistant) injetados no contexto do agente
THREAD_HISTORY_PAIRS = int(os.getenv("THREAD_HISTORY_PAIRS", "3"))

# --- FILA DE MENSAGENS ---
# Tempo em minutos antes de uma mensagem 'processing' ser marcada como 'failed' (RN07)
QUEUE_TIMEOUT_MINUTES = int(os.getenv("QUEUE_TIMEOUT_MINUTES", "5"))

# --- CONTROLE DE ACESSO POR NÚMERO ---
# Se True, o bot responde a qualquer número; se False, apenas aos da lista abaixo
RESPONDER_QUALQUER_NUMERO = os.getenv("RESPONDER_QUALQUER_NUMERO", "False").lower() in ("true", "1", "t")

_numeros_str = os.getenv("NUMEROS_PERMITIDOS", "")
NUMEROS_PERMITIDOS = [num.strip() for num in _numeros_str.split(",") if num.strip()]

# --- IDENTIDADE DO AGENTE ---
AGENT_NAME = os.getenv("AGENT_NAME", "SUAP-IA")

# --- UX / MENSAGENS ESTÁTICAS (RF05, RF07, RN04) ---

MENU_TEXT = f"""Olá! Sou o {AGENT_NAME} 👋 Posso te ajudar com:

- Dúvidas sobre o SUAP e manuais institucionais
- Seus dados acadêmicos (notas, faltas, disciplinas)

Basta digitar sua pergunta diretamente! Por exemplo:
"Como trancar matrícula?"
"Quais são minhas notas?"

Comandos disponíveis:
/menu — exibir este menu
/sair — encerrar sessão"""

# Resposta genérica para falhas inesperadas do agente
FALLBACK_TEXT = "Desculpe, ocorreu uma instabilidade. Tente novamente em alguns instantes."

# Resposta para comandos não reconhecidos (RN04)
UNKNOWN_COMMAND_TEXT = "Comando não reconhecido. Comandos disponíveis: /menu, /sair"
