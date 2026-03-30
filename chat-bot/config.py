import os

# Idealmente, carregue isso de um arquivo .env usando a biblioteca python-dotenv
WAHA_URL = os.getenv("WAHA_URL", "http://localhost:3000/api/sendText")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "sua-chave-openai")
QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
QDRANT_COLLECTION = os.getenv("QDRANT_COLLECTION", "minha_base_de_conhecimento")