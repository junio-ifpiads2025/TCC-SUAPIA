# Manuals Ingestion RAG

Microsserviço FastAPI responsável por **vetorizar e armazenar manuais** no banco de dados pgvector, integrando ao pipeline RAG do SUAPIA.

Recebe os manuais (extraídos em JSON), divide os textos em chunks, gera embeddings via OpenAI e persiste os vetores no PostgreSQL com extensão pgvector.

## Arquitetura

```
app/
├── main.py               # Entrada FastAPI
├── url/url.py            # Definição das rotas
├── controller/           # Orquestração das requisições
├── services/service.py   # Lógica de vetorização (chunking + pgvector)
└── schemas/schema.py     # Modelos Pydantic
```

## Endpoints

| Método | Rota | Descrição |
|--------|------|-----------|
| POST | `/api/v1/ingestao/lote` | Ingere lista de manuais diretamente |
| POST | `/api/v1/ingestao/arquivo-json` | Ingere a partir do formato de extração JSON |

### POST `/api/v1/ingestao/lote`

```json
{
  "manuais": [
    {
      "manual": "Manual do SUAP",
      "versao": "1.0",
      "topicos": [
        {
          "topico": "Título do tópico",
          "texto": "Conteúdo do tópico...",
          "links_imagens": ["https://..."]
        }
      ]
    }
  ]
}
```

### POST `/api/v1/ingestao/arquivo-json`

Aceita o formato de saída direto do serviço de extração:

```json
[
  {
    "nome": "nome-do-manual",
    "resultados": [ /* lista de ManualResponse */ ]
  }
]
```

### Resposta

```json
{
  "mensagem": "Ingestão concluída com sucesso!",
  "total_manuais": 3,
  "total_blocos_gerados": 47
}
```

## Pré-requisitos

- Python 3.10+
- Docker
- Chave de API da OpenAI

## Configuração

**1. Instale as dependências:**

```bash
pip install -r requirements.txt
```

**2. Crie o arquivo `.env`:**

```env
OPENAI_API_KEY=sk-...
PGVECTOR_CONNECTION_STRING=postgresql+psycopg://admin:adminpassword@localhost:5432/vetordatabase
PGVECTOR_COLLECTION=manuais_suap_ifpi
OPENAI_EMBEDDING_MODEL=text-embedding-3-small
```

**3. Suba o banco de dados (pgvector):**

```bash
docker compose up -d db
```

## Execução

```bash
uvicorn app.main:app --host 0.0.0.0 --port 8001 --reload
```

A documentação interativa estará disponível em `http://localhost:8001/docs`.

## Parâmetros de Chunking

| Parâmetro | Valor |
|-----------|-------|
| `chunk_size` | 800 tokens |
| `chunk_overlap` | 150 tokens |
| Separadores | `\n\n`, `\n`, `.`, ` ` |

## Metadados Armazenados por Chunk

Cada bloco vetorizado preserva os seguintes metadados:

- `manual` — nome do manual de origem
- `versao` — versão do manual
- `topico` — título do tópico
- `links_imagens` — lista de URLs de imagens relacionadas
