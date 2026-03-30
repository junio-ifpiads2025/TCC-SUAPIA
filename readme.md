# 📖 SUAPIA - Assistente Virtual RAG para o SUAP (IFPI)

Este projeto é um sistema baseado em Inteligência Artificial (RAG - *Retrieval-Augmented Generation*) desenvolvido para atuar como um assistente virtual integrado ao WhatsApp. O objetivo é tirar dúvidas e fornecer orientações sobre os manuais do sistema SUAP do IFPI.

A arquitetura é dividida em três microsserviços independentes construídos com **FastAPI**, além de serviços de infraestrutura rodando em **Docker**.

## 🏗️ Arquitetura do Projeto

1. **Infraestrutura (Docker):** Banco de dados vetorial (Qdrant) e API do WhatsApp (WAHA).
2. **`manualsExtraction`:** API para download de URLs e extração inteligente do HTML dos manuais do SUAP.
3. **`manualsIngestion-RAG`:** API para quebrar os textos extraídos em blocos (chunks), gerar embeddings via OpenAI e armazenar no Qdrant.
4. **`chat-bot`:** API que atua como Webhook para o WAHA, recebe as mensagens do WhatsApp, busca o contexto no Qdrant e gera a resposta usando a LLM da OpenAI.

---

## ⚙️ 1. Pré-requisitos e Infraestrutura Base

Antes de rodar os microsserviços em Python, você precisa ter o **Docker** e o **Docker Compose** instalados, além de uma chave de API da OpenAI.

### Subindo o Qdrant e o WAHA
Na raiz do projeto, utilize o arquivo `docker-compose.yml` para iniciar o banco vetorial e o motor do WhatsApp:

```bash
docker compose up -d
```

* **Qdrant:** Estará rodando em `http://localhost:6333`
* **WAHA (WhatsApp API):** Estará rodando em `http://localhost:3000`

### Configurando o WhatsApp (WAHA)
1. Acesse o painel do WAHA no navegador: `http://localhost:3000/dashboard`
2. Inicie uma nova sessão (ex: `default`).
3. Escaneie o QR Code com o WhatsApp que servirá como o número do bot.
4. **Configuração do Webhook:** No painel do WAHA ou no seu `docker-compose.yml`, certifique-se de que o Webhook está apontando para o microsserviço do Chatbot. Exemplo: `http://host.docker.internal:8002/webhook` (usamos `host.docker.internal` para o container enxergar a sua máquina local, e `8002` será a porta do chatbot).

---

## 📥 2. Extração dos Manuais (`manualsExtraction`)

Este microsserviço raspa o conteúdo HTML das páginas do SUAP, extrai os tópicos e imagens, e devolve um JSON estruturado.

### Como rodar:
Abra um terminal, acesse a pasta e instale as dependências:
```bash
cd manualsExtraction
python -m venv venv
# Windows: venv\Scripts\activate | Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
```

Inicie o servidor na **porta 8000**:
```bash
uvicorn app.main:app --reload --port 8000
```

### Como usar:
Faça uma requisição `POST` para `http://127.0.0.1:8000/api/v1/processar/lote` enviando um JSON com as URLs dos manuais:
```json
{
  "urls": [
    "https://suap.ifpi.edu.br/documentacao/manual/123/"
  ]
}
```
*O sistema retornará o conteúdo estruturado e também salvará um arquivo de backup localmente na pasta `output/`.*

---

## 🧠 3. Ingestão no Banco Vetorial (`manualsIngestion-RAG`)

Este microsserviço recebe os dados extraídos, converte em vetores (embeddings) usando LangChain e OpenAI, e salva no Qdrant.

### Como rodar:
Abra um novo terminal, acesse a pasta e instale as dependências:
```bash
cd manualsIngestion-RAG
python -m venv venv
# Windows: venv\Scripts\activate | Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
```

Crie um arquivo `.env` na raiz desta pasta:
```env
OPENAI_API_KEY=sk-sua-chave-aqui
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=manuais_suap_ifpi
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

Inicie o servidor na **porta 8001** (para não conflitar com a Extração):
```bash
uvicorn app.main:app --reload --port 8001
```

### Como usar:
Faça uma requisição `POST` para `http://127.0.0.1:8001/api/v1/ingestao/lote`. Você deve enviar no corpo (`body`) exatamente a lista JSON que foi gerada pelo microsserviço de Extração.

---

## 💬 4. Chatbot do WhatsApp (`chat-bot`)

O motor de RAG e integração com os usuários. Ele aguarda as mensagens via webhook, consulta o Qdrant e responde de forma inteligente.

### Como rodar:
Abra um terceiro terminal, acesse a pasta e instale as dependências:
```bash
cd chat-bot
python -m venv venv
# Windows: venv\Scripts\activate | Linux/Mac: source venv/bin/activate
pip install -r requirements.txt
```

Crie um arquivo `.env` na raiz desta pasta:
```env
WAHA_URL=http://localhost:3000/api/sendText
OPENAI_API_KEY=sk-sua-chave-aqui
QDRANT_URL=http://localhost:6333
QDRANT_COLLECTION=manuais_suap_ifpi
```

Inicie o servidor na **porta 8002** (a mesma configurada no Webhook do WAHA):
```bash
uvicorn main:app --reload --port 8002
```

### Como usar:
Com os 3 terminais rodando (WAHA no Docker + Qdrant no Docker + `chat-bot` na porta 8002), basta enviar uma mensagem no WhatsApp para o número que você escaneou o QR Code. O WAHA enviará o evento para o webhook, o bot fará a busca no Qdrant, a OpenAI formulará a resposta, e o usuário receberá o texto no celular!
