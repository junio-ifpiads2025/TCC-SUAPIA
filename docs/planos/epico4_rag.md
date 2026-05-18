# Plano — Épico 4: Agente de IA — RAG (Manuais Institucionais)

> Requisitos cobertos: RF13 (classificação), RF14, RF15, RF16 | Regras: RN09, RN10

**Depende de:** Épico 0 (pgvector + `thread_history`), Épico 3 (chamado pelo processador de fila)

---

## Objetivo

Responder consultas institucionais buscando trechos relevantes dos manuais do SUAP via busca vetorial (pgvector) e gerando respostas fundamentadas exclusivamente nesse conteúdo.

---

## Arquivos a criar / modificar

| Arquivo | Ação |
|---------|------|
| `services/rag_agent.py` | Modificar — adaptar ao novo schema e RNs |
| `services/agent_orchestrator.py` | Modificar — integrar classificação RF13 |
| `models/database.py` | Atualizar — model `ThreadHistory` |
| `services/history_service.py` | Criar — gerenciar `thread_history` |

---

## Passos

### 4.1 — `services/history_service.py`

```python
async def get_history(chat_id: str) -> list[dict]
    # Busca últimas MAX_HISTORY_MESSAGES mensagens do chat_id (RN10)
    # Retorna no formato [{"role": "user"|"assistant", "content": "..."}]

async def save_turn(chat_id: str, user_msg: str, assistant_msg: str)
    # Insere dois registros em thread_history
```

- Limite: `MAX_HISTORY_MESSAGES` do `config.py` (default 10, RN10).
- Query: `ORDER BY created_at DESC LIMIT {MAX_HISTORY_MESSAGES}` → inverter para ordem cronológica.

### 4.2 — Classificação de consultas (RF13)

Em `agent_orchestrator.py`, antes de chamar RAG ou MCP:

```python
async def classify(message: str) -> Literal["rag", "mcp", "both"]
```

Implementar com chamada leve ao LLM (system prompt classificador) ou heurísticas por palavras-chave:
- Palavras como "nota", "falta", "horário", "matrícula" → `mcp`
- Palavras como "como funciona", "o que é", "manual", "regra" → `rag`
- Ambíguo / misto → `both`

Consultas `both`: RAG e MCP chamados em paralelo (`asyncio.gather`), resultados concatenados no contexto do LLM.

### 4.3 — `services/rag_agent.py` — Busca Vetorial (RF14)

```python
async def search(query: str) -> list[dict]:
```

1. Gerar embedding da query com `text-embedding-3-small`.
2. Query no pgvector:
   ```sql
   SELECT content, 1 - (embedding <=> $1) AS score
   FROM documents
   WHERE 1 - (embedding <=> $1) >= $2  -- RN09: SIMILARITY_THRESHOLD
   ORDER BY score DESC
   LIMIT 5
   ```
3. Retornar lista de `{"content": ..., "score": ...}`.

### 4.4 — Geração de resposta (RF15)

```python
async def generate(query: str, chunks: list[dict], history: list[dict]) -> str:
```

System prompt restritivo:
```
Você é um assistente do SUAP do IFPI. Responda APENAS com base nos trechos fornecidos.
Se não houver informação suficiente, diga que não encontrou nos manuais e sugira 
contato com a secretaria acadêmica.
```

- Se `chunks` vazio → retornar mensagem de encaminhamento sem chamar o LLM (RF15, RN09).
- Nunca gerar informação além do contexto fornecido (RF15).

### 4.5 — Fallback de timeout/rede (RF16)

```python
async def gerar_resposta_rag(query, chat_id) -> tuple[str, list]:
    try:
        async with asyncio.timeout(30):  # configurável
            chunks = await search(query)
            history = await history_service.get_history(chat_id)
            response = await generate(query, chunks, history)
            return response, chunks
    except (asyncio.TimeoutError, httpx.RequestError):
        return config.FALLBACK_TEXT, []
```

---

## Critérios de Aceite

- **RF13:** Consultas são classificadas corretamente; mistas ativam RAG + MCP em paralelo.
- **RF14:** Retorna trechos com maior similaridade; trechos abaixo do limiar são descartados.
- **RF15:** Resposta gerada exclusivamente a partir dos chunks; ausência de contexto resulta em encaminhamento, não alucinação.
- **RF16:** Timeout ou erro de rede → `FALLBACK_TEXT` ao usuário; mensagem marcada `failed`.
- **RN09:** `SIMILARITY_THRESHOLD` configurável; padrão 0,75.
- **RN10:** Histórico limitado a `MAX_HISTORY_MESSAGES`; mensagens mais antigas descartadas.
