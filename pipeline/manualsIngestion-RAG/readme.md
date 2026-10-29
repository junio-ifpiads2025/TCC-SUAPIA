# Manuals Ingestion RAG

CLI responsável por **vetorizar e armazenar manuais** no banco pgvector, integrando ao pipeline RAG do SUAPIA.

Lê os `.md` gerados pela extração (`manualsExtraction`), divide os textos em chunks, gera embeddings via OpenAI e persiste os vetores no PostgreSQL com extensão pgvector.

## Arquitetura

```
cli.py / __main__.py      # Entrada da CLI (argparse)
app/
├── controller/           # Orquestração da ingestão
├── services/loader.py    # Leitura dos .md (ou .json legado) -> modelos
├── services/service.py   # Lógica de vetorização (chunking + pgvector)
└── schemas/schema.py     # Modelos Pydantic
```

## Entrada

Pasta gerada pela extração: `output/<AAAAMMDD_HHMMSS>/<manual>/[<capitulo>/]<pagina>.md`.

Do front matter de cada `.md` saem `manual` e `titulo`/`capitulo`; o tópico vira `Capítulo > Título` (ou só o título). As imagens (`![..](url)`) do corpo viram `links_imagens`. Também é aceito o `.json` legado (`[{"nome": ..., "resultados": [...]}]`).

## Pré-requisitos

- Python 3.10+
- Docker
- Chave de API da OpenAI

## Configuração

**1. Instale as dependências (venv próprio em `.venv`):**

```bash
make install-ingestion
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
make db-up
```

## Execução

A partir da raiz do repositório:

```bash
# execução mais recente em pipeline/manualsExtraction/output
python pipeline/manualsIngestion-RAG

# pasta ou arquivo específico
python pipeline/manualsIngestion-RAG pipeline/manualsExtraction/output/20261029_145628
python pipeline/manualsIngestion-RAG saida.json
```

Atalho: `make ingest` (ou `make ingest SRC=caminho`). Código de saída: `0` ok, `1` falha na ingestão, `2` caminho inválido.

## Parâmetros de Chunking

| Parâmetro | Valor |
|-----------|-------|
| `chunk_size` | 800 caracteres (`INGESTAO_CHUNK_SIZE`) |
| `chunk_overlap` | 150 caracteres (`INGESTAO_CHUNK_OVERLAP`) |
| Lote de embeddings | 100 chunks (`INGESTAO_TAMANHO_LOTE`) |
| Separadores | `\n\n`, `\n`, `. `, `; `, ` ` |

## Idempotência

Cada chunk recebe ID determinístico (`manual + versão + tópico + índice`). Reenviar um manual
**substitui** seus chunks antigos (sem duplicar nem deixar órfãos). Tópicos vazios ou repetidos
são descartados e contados em `topicos_ignorados`.

## Metadados Armazenados por Chunk

Cada bloco vetorizado preserva os seguintes metadados:

- `manual` — nome do manual de origem
- `versao` — versão do manual
- `topico` — título do tópico
- `links_imagens` — lista de URLs de imagens relacionadas
- `chunk_index` / `total_chunks` — posição do bloco dentro do tópico
