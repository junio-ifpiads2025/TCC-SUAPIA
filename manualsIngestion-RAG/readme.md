# Manuals Ingestion

Este projeto contém o script responsável por fazer a **ingestão de manuais** (previamente extraídos em formato JSON) para uma base de dados vetorial (Qdrant).

O script lê os dados locais, divide os textos em blocos menores (chunks) preservando os metadados (como links de imagens e títulos) e os envia para o banco de dados utilizando os embeddings da OpenAI.

## 📋 Pré-requisitos

* **Python 3.10+**
* **Docker** (para rodar o Qdrant localmente)
* Chave de API da **OpenAI**

## 🛠️ Configuração do Ambiente

**1. Instale as dependências:**
```bash
pip install langchain langchain-openai langchain-qdrant qdrant-client python-dotenv

https://waha.devlike.pro/blog/waha-on-docker/
docker compose run --no-deps -v "$(pwd)":/app/env waha init-waha /app/env