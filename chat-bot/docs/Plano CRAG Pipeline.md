# Plano de Implementação: CRAG-Based Pipeline

## 1. Visão Geral

O **Corrective RAG (CRAG)** adiciona uma etapa de avaliação automática de relevância entre a recuperação e a geração. Se os documentos iniciais não forem suficientemente relevantes (score < 0.7), o pipeline aciona uma expansão multi-query antes de gerar a resposta. Se mesmo após a expansão a qualidade for insuficiente, retorna uma mensagem de fallback em vez de uma resposta inventada.

### Diferença em relação ao Advanced RAG atual

| Aspecto | Advanced RAG (atual) | CRAG (proposto) |
|---|---|---|
| Reescrita de query | Sim | Sim |
| Expansão multi-query | **Sempre** | **Só se necessário** |
| Avaliação de relevância | Nenhuma | BGE-Reranker max\_score ≥ 0.7 |
| Fallback explícito | Não | Sim (score < 0.7 após expansão) |
| Custo em tokens | Sempre alto | Baixo no caminho feliz |

---

## 2. Fluxo Completo

```
Pergunta Crua
      │
      ▼
[Fase 1] LLM Rápido: Query Rewriting
      │
      ▼
 Consulta Reformulada
      │
      ▼
[Fase 2A] Embeddings + pgvector → Top-5 Chunks Iniciais
      │
      ▼
[Fase 2B] BGE-Reranker: avalia Top-5 vs Consulta
      │
      ├── max_score ≥ 0.7 ──────────────────────────────────┐
      │   (✅ Relevante)                                      │
      │                                                       │
      └── max_score < 0.7                                     │
          (❌ Insuficiente)                                    │
                │                                             │
                ▼                                             │
[Fase 3A] LLM Rápido: Multi-Query Expansion (3 variações)    │
                │                                             │
                ▼                                             │
[Fase 3B] Busca Paralela no pgvector → ~15 Chunks            │
                │                                             │
                ▼                                             │
[Fase 3C] Deduplicação de Markdown                           │
                │                                             │
                ▼                                             │
[Fase 3D] BGE-Reranker: repontuação do pool                  │
                │                                             │
                ├── max_score ≥ 0.7 ──────────────────────┐  │
                │                                          │  │
                └── max_score < 0.7                        │  │
                    (⛔ Fallback)                           │  │
                          │                                │  │
                          ▼                                ▼  ▼
               "Informação não encontrada"    Top-K Documentos Finais
                     nos manuais                         │
                                                         ▼
                                          [Fase 4] Montagem do Prompt Final
                                          (System Prompt + Contexto + Pergunta)
                                                         │
                                                         ▼
                                          LLM Principal: gpt-4o (temp=0.1)
                                                         │
                                                         ▼
                                               Resposta Final ao Usuário
```

---

## 3. Mudanças no Código

### 3.1 Arquivo: `services/advanced_rag_agent.py`

#### A) Nova variável de ambiente

```python
CRAG_SCORE_THRESHOLD = float(os.getenv("CRAG_SCORE_THRESHOLD", "0.7"))
FALLBACK_MESSAGE = os.getenv(
    "FALLBACK_MESSAGE",
    "Desculpe, não encontrei informações suficientemente relevantes sobre isso nos manuais do SUAP.",
)
```

#### B) Modificar `QueryTransformer`

Separar `rewrite()` e `expand()` — já existem como métodos distintos, mas o método `transform()` atual sempre chama os dois. Adicionar um método `rewrite_only()` que o pipeline CRAG usará na fase 1.

```python
# Nenhuma mudança necessária na classe.
# O orquestrador CRAG chama transformer.rewrite() diretamente na fase 1
# e transformer.expand() somente se necessário na fase 3.
```

#### C) Modificar `ContextReranker.rerank()` → retornar max\_score

```python
# Assinatura atual:
def rerank(self, query: str, docs: List[Document]) -> List[Document]:

# Nova assinatura:
def rerank(self, query: str, docs: List[Document]) -> Tuple[List[Document], float]:
    """
    Retorna (top_docs, max_score).
    max_score é o maior score bruto do Cross-Encoder entre todos os docs avaliados.
    """
    if not docs:
        return docs, 0.0

    if self._reranker is None:
        logger.warn("RERANKER", "Usando fallback (sem reranking).")
        return docs[: self._top_k], 1.0  # sem reranker, não bloqueia

    pairs = [[query, doc.page_content] for doc in docs]
    scores = self._reranker.predict(pairs)
    max_score = float(max(scores))
    ranked = sorted(zip(scores, docs), key=lambda x: x[0], reverse=True)
    top_docs = [doc for _, doc in ranked[: self._top_k]]
    return top_docs, max_score
```

> **Nota:** O `CrossEncoder` da `sentence_transformers` retorna scores brutos (logits), não probabilidades. O threshold de 0.7 precisará ser calibrado empiricamente com o dataset de avaliação — pode ser necessário ajustar via `CRAG_SCORE_THRESHOLD`.

#### D) Nova classe orquestradora: `CRAGPipeline`

```python
class CRAGPipeline:
    """
    Pipeline CRAG (Corrective RAG):
      Fase 1  → Reescrita da query
      Fase 2A → Retrieval inicial (Top-5)
      Fase 2B → BGE-Reranker avalia relevância (threshold)
      Fase 3  → [Condicional] Multi-Query Expansion + Retrieval Paralelo + Dedup + Rerank
      Fase 4  → Geração ou Fallback
    """

    def __init__(self):
        self.transformer = QueryTransformer(_openai_client, MODELO_LLM_RAPIDO)
        self.retriever = MultiviewRetriever(_vector_store, RETRIEVAL_TOP_K)
        self.reranker = ContextReranker(RERANKER_MODEL, RERANKER_TOP_K)
        self.generator = AnswerGenerator(
            _openai_client, MODELO_LLM_AVANCADO, SYSTEM_PROMPT, TEMPERATURE_AVANCADO
        )

    def invoke(self, user_query: str) -> Tuple[str, List[dict]]:
        # ── Fase 1: Reescrita ──────────────────────────────────────────────
        logger.phase(1, "Reescrita da Consulta (Query Rewriting)")
        logger.info("QUERY", f"Original: {user_query}")
        rewritten = self.transformer.rewrite(user_query)
        logger.info("QUERY", f"Reescrita: {rewritten}")

        # ── Fase 2A: Retrieval Inicial ─────────────────────────────────────
        logger.phase(2, "Retrieval Inicial (Top-5)")
        initial_docs = self.retriever.retrieve([rewritten])
        logger.info("RETRIEVER", f"{len(initial_docs)} doc(s) recuperado(s)")

        if not initial_docs:
            logger.warn("RETRIEVER", "Nenhum documento encontrado. Retornando fallback.")
            return FALLBACK_MESSAGE, []

        # ── Fase 2B: Avaliação de Relevância ──────────────────────────────
        logger.phase(2, "Avaliação de Relevância (BGE-Reranker)")
        top_docs, max_score = self.reranker.rerank(rewritten, initial_docs)
        logger.info("RERANKER", f"max_score={max_score:.4f} | threshold={CRAG_SCORE_THRESHOLD}")

        if max_score >= CRAG_SCORE_THRESHOLD:
            logger.success("CRAG", f"Score ≥ {CRAG_SCORE_THRESHOLD}: caminho direto para geração.")
            final_docs = top_docs
        else:
            # ── Fase 3: Correção via Multi-Query Expansion ─────────────────
            logger.warn("CRAG", f"Score < {CRAG_SCORE_THRESHOLD}: acionando Multi-Query Expansion.")
            logger.phase(3, "Multi-Query Expansion + Retrieval Paralelo")

            variations = self.transformer.expand(rewritten)
            logger.info("QUERY", f"{len(variations)} variação(ões) gerada(s)")

            expanded_docs = self.retriever.retrieve(variations)
            logger.info("RETRIEVER", f"{len(expanded_docs)} doc(s) após expansão e deduplicação")

            if not expanded_docs:
                logger.warn("RETRIEVER", "Expansão não retornou documentos. Retornando fallback.")
                return FALLBACK_MESSAGE, []

            top_docs_expanded, max_score_expanded = self.reranker.rerank(rewritten, expanded_docs)
            logger.info("RERANKER", f"max_score pós-expansão={max_score_expanded:.4f}")

            if max_score_expanded < CRAG_SCORE_THRESHOLD:
                logger.warn("CRAG", "Score ainda insuficiente após expansão. Retornando fallback.")
                return FALLBACK_MESSAGE, []

            logger.success("CRAG", "Score suficiente após expansão. Prosseguindo para geração.")
            final_docs = top_docs_expanded

        # ── Fase 4: Geração ────────────────────────────────────────────────
        logger.phase(4, "Geração da Resposta")
        logger.info("LLM", f"Chamando {MODELO_LLM_AVANCADO}…")
        try:
            answer = self.generator.generate(rewritten, final_docs)
        except Exception as e:
            logger.error("LLM", f"Erro na geração: {e}")
            return "Desculpe, tive um erro ao processar sua pergunta.", []

        metadata = [doc.metadata for doc in final_docs]
        return answer, metadata
```

#### E) Nova função de entrada pública

```python
_crag_pipeline: CRAGPipeline | None = None

def gerar_resposta_crag(pergunta: str) -> Tuple[str, List[dict]]:
    """Ponto de entrada para o pipeline CRAG."""
    global _crag_pipeline
    if _crag_pipeline is None:
        _crag_pipeline = CRAGPipeline()
    return _crag_pipeline.invoke(pergunta)
```

---

### 3.2 Arquivo: `config.py`

Adicionar as novas variáveis ao `.env.example` e à documentação de configuração:

```env
# Pipeline CRAG
USE_CRAG=false
CRAG_SCORE_THRESHOLD=0.7
FALLBACK_MESSAGE=Desculpe, não encontrei informações suficientemente relevantes sobre isso nos manuais do SUAP.
```

---

### 3.3 Arquivo: `main.py`

Adicionar seleção do pipeline CRAG junto à lógica existente de `USE_ADVANCED_RAG`:

```python
USE_CRAG = os.getenv("USE_CRAG", "false").lower() == "true"

# Na função de processamento de mensagem:
if USE_CRAG:
    from services.advanced_rag_agent import gerar_resposta_crag
    resposta, metadados = gerar_resposta_crag(pergunta)
elif USE_ADVANCED_RAG:
    from services.advanced_rag_agent import gerar_resposta_avancada
    resposta, metadados = gerar_resposta_avancada(pergunta)
else:
    ...
```

---

### 3.4 Arquivo: `evaluation/interface/rag.py`

Adicionar o pipeline CRAG como opção de avaliação:

```python
elif pipeline == "crag":
    from services.advanced_rag_agent import gerar_resposta_crag
    resposta, _ = gerar_resposta_crag(pergunta)
```

---

## 4. Calibração do Threshold

O `CRAG_SCORE_THRESHOLD=0.7` é um valor inicial. O score bruto do `bge-reranker-v2-m3` não é probabilidade — pode variar de −∞ a +∞ dependendo do par (query, documento). Para calibrar:

1. Rodar a avaliação com o dataset existente em `/evaluation/dataset/`
2. Anotar o `max_score` dos pares em perguntas onde a resposta foi correta vs. incorreta
3. Ajustar via `CRAG_SCORE_THRESHOLD` no `.env`

Alternativamente, aplicar **sigmoid** nos scores brutos para normalizá-los em [0, 1]:

```python
import math
normalized = 1 / (1 + math.exp(-raw_score))
```

---

## 5. Logs Esperados

### Caminho feliz (score ≥ 0.7)

```
[FASE 1] Reescrita da Consulta (Query Rewriting)
[INFO] QUERY     | Original: como faço pra lançar nota?
[INFO] QUERY     | Reescrita: Como realizar o lançamento de notas no SUAP?
[FASE 2] Retrieval Inicial (Top-5)
[INFO] RETRIEVER | 5 doc(s) recuperado(s)
[FASE 2] Avaliação de Relevância (BGE-Reranker)
[INFO] RERANKER  | max_score=0.8342 | threshold=0.7
[OK]   CRAG      | Score ≥ 0.7: caminho direto para geração.
[FASE 4] Geração da Resposta
[INFO] LLM       | Chamando gpt-4o…
```

### Caminho corretivo (score < 0.7, expansão bem-sucedida)

```
[FASE 2] Avaliação de Relevância (BGE-Reranker)
[INFO] RERANKER  | max_score=0.4120 | threshold=0.7
[WARN] CRAG      | Score < 0.7: acionando Multi-Query Expansion.
[FASE 3] Multi-Query Expansion + Retrieval Paralelo
[INFO] QUERY     | 3 variação(ões) gerada(s)
[INFO] RETRIEVER | 13 doc(s) após expansão e deduplicação
[INFO] RERANKER  | max_score pós-expansão=0.7891
[OK]   CRAG      | Score suficiente após expansão. Prosseguindo para geração.
[FASE 4] Geração da Resposta
```

### Fallback (score < 0.7 mesmo após expansão)

```
[WARN] CRAG      | Score ainda insuficiente após expansão. Retornando fallback.
```

---

## 6. Ordem de Implementação

1. **Modificar `ContextReranker.rerank()`** para retornar `(docs, max_score)` — impacta o pipeline existente, ajustar `AdvancedRAGPipeline` para desempacotar a tupla.
2. **Adicionar variáveis de ambiente** (`CRAG_SCORE_THRESHOLD`, `FALLBACK_MESSAGE`, `USE_CRAG`) em `config.py` e `.env.example`.
3. **Implementar `CRAGPipeline`** e `gerar_resposta_crag()` em `advanced_rag_agent.py`.
4. **Atualizar `main.py`** com seleção do pipeline.
5. **Atualizar `evaluation/interface/rag.py`** com opção `"crag"`.
6. **Calibrar threshold** rodando avaliação com RAGAS.

---

## 7. Arquivos Modificados

| Arquivo | Tipo de mudança |
|---|---|
| `services/advanced_rag_agent.py` | Principal: nova classe `CRAGPipeline`, assinatura de `rerank()` |
| `config.py` / `.env.example` | Novas variáveis de ambiente |
| `main.py` | Seleção do pipeline CRAG |
| `evaluation/interface/rag.py` | Opção `"crag"` na avaliação |
