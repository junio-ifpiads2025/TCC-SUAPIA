# Especificação Técnica: Arquitetura Advanced RAG (SUAP-IA)

Este documento define a arquitetura e os requisitos de implementação para o pipeline de Retrieval-Augmented Generation (RAG) Avançado. O objetivo é processar consultas informais de alunos, transformar as requisições, realizar buscas vetoriais abrangentes e aplicar re-ranqueamento antes da geração da resposta final.

## Stack Tecnológica Sugerida
- **Orquestração:** LangChain ou LlamaIndex
- **LLM Rápido (Roteamento/Transformação):** `gpt-4o-mini` ou `gemini-1.5-flash`
- **LLM Principal (Geração):** Modelo de alta capacidade (ex: `gpt-4o` ou equivalente)
- **Vector DB:** Qdrant ou pgvector
- **Embeddings:** OpenAI (`text-embedding-3-small` / `large`) ou HuggingFace
- **Reranker:** BGE-Reranker (`BAAI/bge-reranker-v2-m3`) via `FlagEmbedding` ou Cross-Encoder HuggingFace.

---

## Pipeline de Execução

O sistema deve ser implementado como uma pipeline linear de 4 fases principais.

### Fase 1: Transformação da Consulta (Query Transformation)
**Objetivo:** Limpar a entrada crua do usuário e expandi-la para maximizar o *Context Recall*.

1. **Entrada:** String crua do usuário (ex: *"tô perdido, como vejo minhas nota?"*).
2. **Query Rewriting (Reescrita):**
   - Utilizar um LLM rápido e barato.
   - **Prompt:** Traduzir linguagem informal/gírias para o vocabulário oficial do sistema SUAP.
   - **Saída Esperada:** Consulta Reformulada (ex: *"Como o aluno visualiza o boletim de notas?"*).
3. **Multi-Query Expansion (Expansão):**
   - Utilizar o LLM rápido para gerar variações semânticas da Consulta Reformulada.
   - **Saída Esperada:** Lista contendo a consulta reformulada + 3 variações.
   - *Exemplo de variações:*
     - "Passo a passo para acessar o boletim no sistema"
     - "Onde encontrar o diário e notas do período letivo"
     - "Consulta de rendimento acadêmico"

### Fase 2: Busca Vetorial Multivias (Retrieval)
**Objetivo:** Buscar os trechos dos manuais para todas as variações geradas na Fase 1.

1. **Geração de Embeddings:** Converter as 4 queries (1 reformulada + 3 variações) em vetores.
2. **Busca no Vector DB:**
   - Realizar uma busca de similaridade (Top-K = 5) no banco de dados vetorial para **cada** uma das consultas.
   - **Saída Esperada:** Uma lista concatenada contendo aproximadamente 20 documentos/chunks recuperados.

### Fase 3: Filtragem e Re-ranqueamento (Reranking)
**Objetivo:** Refinar os resultados da busca multivias, eliminando ruído e garantindo alta *Context Precision*.

1. **Remoção de Duplicatas:** Função para unificar chunks idênticos (merge) retornados por queries diferentes, baseando-se no ID ou hash do chunk.
2. **Cross-Encoder Reranking:**
   - Instanciar o modelo `bge-reranker`.
   - Passar a **Consulta Reformulada** (da Fase 1) e a lista de chunks únicos pelo Reranker.
   - O Reranker deve atribuir um *score* de relevância de 0 a 1 para cada par (consulta, chunk).
3. **Top-K Final:** - Ordenar os chunks pelo score decrescente.
   - Cortar a lista para manter apenas os **Top 3 a Top 5** documentos com as notas mais altas.

### Fase 4: Geração da Resposta
**Objetivo:** Sintetizar a resposta final de forma segura e fundamentada.

1. **Montagem do Prompt Final:**
   - **System Prompt:** Regras estritas de comportamento e tom de voz institucional.
   - **Contexto:** Inserir exclusivamente o texto dos Top-K Documentos Finais vindos da Fase 3.
   - **Pergunta:** Utilizar a Consulta Reformulada.
2. **Invocação do LLM Principal:**
   - Executar a geração utilizando **Temperatura Baixa (ex: 0.1)** para mitigar alucinações.
3. **Saída:** Resposta clara, fundamentada (citando os manuais) e formatada em Markdown.

---

## Estrutura de Código Recomendada (Orientação para a IA)

Por favor, implemente o design pattern de **Chain** ou abstrações de **Classes** para este pipeline. Crie funções/métodos claros para cada etapa:

1. `class QueryTransformer`: Lida com reescrita e expansão.
2. `class MultiviewRetriever`: Executa buscas assíncronas no VectorDB e faz o merge de resultados.
3. `class ContextReranker`: Inicializa o Cross-Encoder e reordena os chunks.
4. `class AnswerGenerator`: Monta os templates de prompt e aciona o LLM final.
5. `class AdvancedRAGPipeline`: Classe orquestradora que une os 4 componentes acima em um método `invoke(user_query: str)`.