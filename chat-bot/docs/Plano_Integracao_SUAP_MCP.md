# Plano de Integração: SUAP MCP no Chatbot

Este documento descreve a estratégia para integrar o servidor **SUAP MCP** ao chatbot existente, transformando-o de um sistema puramente de Recuperação Aumentada por Geração (RAG) em um **Agente Inteligente** capaz de executar ações e consultar dados em tempo real no SUAP.

## 1. Objetivos
- Permitir que o usuário consulte dados pessoais (notas, diários, mensagens) via WhatsApp.
- Integrar ferramentas do SUAP MCP ao pipeline de IA atual.
- Manter a capacidade de RAG para dúvidas sobre manuais e normas.

## 2. Arquitetura Proposta

Atualmente, o chatbot opera com pipelines lineares (Transformação -> Recuperação -> Reranking -> Geração). A integração do MCP exige uma mudança para uma arquitetura de **Agente (ReAct)** ou um **Roteamento Inteligente**.

### Novo Fluxo de Processamento:
1. **Entrada do Usuário:** Mensagem recebida via WAHA.
2. **Classificação/Roteamento:** O LLM decide se a intenção requer:
   - **RAG:** Dúvidas sobre manuais (ex: "Como trancar matrícula?").
   - **Ferramentas SUAP:** Consulta de dados dinâmicos (ex: "Quais são minhas notas?").
   - **Ambos:** Integração de dados dinâmicos com normas.
3. **Execução:**
   - Se MCP: Aciona o `MCPClient` para executar a ferramenta solicitada.
   - Se RAG: Segue o pipeline de `AdvancedRAG`.
4. **Síntese:** O LLM gera a resposta final combinando os resultados das ferramentas ou da busca vetorial.

## 3. Alterações e Implementações

### 3.1. Novos Arquivos
- `services/mcp_client.py`: Gerenciador de conexão com o servidor SUAP MCP. Responsável por iniciar o processo do servidor e expor as ferramentas para o agente.
- `services/agent_orchestrator.py`: Novo orquestrador que substituirá o fluxo linear quando o modo Agente estiver ativo.

### 3.2. Alterações em Arquivos Existentes
- `.env` & `config.py`: Adicionar configurações para o MCP (`SUAP_BASE_URL`, `SUAP_TOKEN`).
- `main.py`: Adicionar suporte para um novo modo de operação `USE_AGENT=true`.
- `requirements.txt`: Adicionar a biblioteca `mcp`.

## 4. Plano de Implementação

### Passo 1: Configuração do Ambiente
- Instalar a biblioteca cliente do MCP: `pip install mcp`.
- Garantir que o `suap-mcp` está acessível no ambiente.

### Passo 2: Implementação do Cliente MCP
Criar uma classe `SUAPMCPClient` que:
- Inicia o servidor SUAP MCP via subprocesso (stdio).
- Lista ferramentas disponíveis.
- Executa ferramentas e retorna resultados formatados.

### Passo 3: Criação do Agente com Tools
Integrar as ferramentas do MCP ao `OpenAI Assistant` ou usar o padrão `Tool Calling` da OpenAI:
- Definir schemas das ferramentas do SUAP para o LLM.
- Implementar o loop de execução de ferramentas.

### Passo 4: Integração RAG + Tools
O Agente terá uma ferramenta chamada `search_manuals` que encapsula o pipeline de RAG existente. Assim, o LLM pode decidir buscar nos manuais se a pergunta for sobre procedimentos.

## 5. Exemplo de Ferramentas que serão Expostas
- `get_my_data`: Dados do perfil.
- `get_disciplines`: Notas e frequências.
- `get_messages`: Mensagens da caixa de entrada.
- `get_diaries`: Aulas e conteúdos.

## 6. Próximos Passos
1. Validar a conexão com o servidor `suap-mcp` via script de teste.
2. Implementar `services/mcp_client.py`.
3. Refatorar `main.py` para suportar o orquestrador de agente.
