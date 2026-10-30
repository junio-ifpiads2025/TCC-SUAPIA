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

# --- MENSAGERIA ---
# Providers habilitados (separados por vírgula). Ver services/providers/.
MESSAGING_PROVIDERS = [p.strip() for p in os.getenv("MESSAGING_PROVIDERS", "waha").split(",") if p.strip()]
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_WEBHOOK_SECRET = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")

# --- LLM / EMBEDDINGS ---
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sua-chave-openai")

# --- BANCO DE DADOS (PostgreSQL + pgvector) ---
PGVECTOR_CONNECTION_STRING = os.getenv(
    "PGVECTOR_CONNECTION_STRING",
    "postgresql+psycopg://admin:adminpassword@localhost:5432/vetordatabase"
)
PGVECTOR_COLLECTION = os.getenv("PGVECTOR_COLLECTION", "manuais_suap_ifpi")

# --- BASE DE CONHECIMENTO DO AGENTE (RAG editável pelo admin) ---
# Coleção separada da dos manuais: o CRUD nunca toca nos manuais já indexados.
KNOWLEDGE_COLLECTION = os.getenv("KNOWLEDGE_COLLECTION", "conhecimento_agente")
KNOWLEDGE_EMBEDDING_MODEL = os.getenv("MODELO_EMBEDDING", "text-embedding-3-small")
KNOWLEDGE_CHUNK_SIZE = int(os.getenv("KNOWLEDGE_CHUNK_SIZE", "800"))
KNOWLEDGE_CHUNK_OVERLAP = int(os.getenv("KNOWLEDGE_CHUNK_OVERLAP", "150"))
KNOWLEDGE_TOP_K = int(os.getenv("KNOWLEDGE_TOP_K", "4"))
# Limite de tamanho por documento, em caracteres
KNOWLEDGE_MAX_CHARS = int(os.getenv("KNOWLEDGE_MAX_CHARS", "200000"))

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
# Segredo para assinar o cookie de sessão do painel (itsdangerous)
ADMIN_SESSION_SECRET = os.getenv("ADMIN_SESSION_SECRET", "")
ADMIN_SESSION_TTL_SECONDS = int(os.getenv("ADMIN_SESSION_TTL_SECONDS", "28800"))

# --- LOG DE ACESSO ---
# LGPD: por padrão grava só tamanho/hash da mensagem, não o texto
ACCESS_LOG_STORE_CONTENT = os.getenv("ACCESS_LOG_STORE_CONTENT", "False").lower() in ("true", "1", "t")
ACCESS_LOG_RETENTION_DAYS = int(os.getenv("ACCESS_LOG_RETENTION_DAYS", "90"))

# --- HISTÓRICO DE CONVERSA ---
# Número de pares (user + assistant) injetados no contexto do agente
THREAD_HISTORY_PAIRS = int(os.getenv("THREAD_HISTORY_PAIRS", "3"))

# --- FILA DE MENSAGENS ---
# Tempo em minutos antes de uma mensagem 'processing' ser marcada como 'failed' (RN07)
QUEUE_TIMEOUT_MINUTES = int(os.getenv("QUEUE_TIMEOUT_MINUTES", "5"))
# Tentativas antes de mover o item para suap:queue:failed
QUEUE_MAX_ATTEMPTS = int(os.getenv("QUEUE_MAX_ATTEMPTS", "2"))
# Consumidores asyncio da fila dentro do mesmo processo (um único worker uvicorn)
QUEUE_CONSUMERS = int(os.getenv("QUEUE_CONSUMERS", "1"))

# --- CONTROLE DE ACESSO POR NÚMERO ---
# Se True, o bot responde a qualquer número; se False, apenas aos da allowlist (tabela access_rule)
RESPONDER_QUALQUER_NUMERO = os.getenv("RESPONDER_QUALQUER_NUMERO", "False").lower() in ("true", "1", "t")

# --- IDENTIDADE DO AGENTE ---
AGENT_NAME = os.getenv("AGENT_NAME", "SUAP-IA")
AGENT_VERSION = os.getenv("AGENT_VERSION", "0.1.0")

# --- UX / MENSAGENS ESTÁTICAS (RF05, RF07, RN04) ---

MENU_TEXT = f"""Olá! Sou o {AGENT_NAME} 👋 Posso te ajudar com:

- Dúvidas sobre o SUAP e manuais institucionais
- Seus dados acadêmicos (notas, faltas, disciplinas)

Basta digitar sua pergunta diretamente! Por exemplo:
"Como trancar matrícula?"
"Quais são minhas notas?"

Comandos disponíveis:
/menu — exibir este menu
/about — informações sobre o agente
/sair — encerrar sessão"""

ABOUT_TEXT = f"""{AGENT_NAME} — versão {AGENT_VERSION}

Assistente virtual desenvolvido para o IFPI, integrado ao SUAP.

Capacidades:
- Consulta de dados acadêmicos (notas, faltas, disciplinas)
- Busca nos manuais institucionais do SUAP
- Autenticação segura via conta SUAP

Desenvolvido como Trabalho de Conclusão de Curso (TCC) — IFPI."""

# Resposta genérica para falhas inesperadas do agente
FALLBACK_TEXT = "Desculpe, ocorreu uma instabilidade. Tente novamente em alguns instantes."

# Resposta para comandos não reconhecidos (RN04)
UNKNOWN_COMMAND_TEXT = "Comando não reconhecido. Comandos disponíveis: /menu, /about, /sair"
