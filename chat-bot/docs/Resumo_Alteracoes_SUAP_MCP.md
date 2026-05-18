# Resumo de Alterações para Integração SUAP MCP

Este documento detalha as modificações técnicas e novas implementações necessárias para integrar o Agente SUAP MCP ao Chatbot.

## 🛠 Novas Implementações

### 1. `services/mcp_client.py` (Novo)
- Implementação de um cliente MCP para comunicação via STDIO com o servidor `suap-mcp`.
- Gerenciamento do ciclo de vida do servidor (start/stop).
- Método para descoberta dinâmica de ferramentas.
- Interface para execução de ferramentas com tratamento de erros.

### 2. `services/agent_orchestrator.py` (Novo)
- Orquestrador baseado em Agente (ReAct/Tool Calling).
- Lógica de decisão entre consulta ao Banco Vetorial (RAG) e ferramentas SUAP.
- Gerenciamento de histórico de conversas para manter contexto entre chamadas de ferramentas.

## 📝 Alterações em Arquivos Existentes

### 1. `main.py`
- Adição da variável `USE_AGENT` para ativar o novo fluxo.
- Refatoração de `processar_fluxo_mensagem` para delegar ao `AgentOrchestrator` quando o modo agente estiver ativo.

### 2. `config.py`
- Inclusão das variáveis de ambiente:
    - `SUAP_TOKEN`: Token JWT para autenticação na API do SUAP.
    - `SUAP_BASE_URL`: URL base da instância do SUAP.
    - `USE_AGENT`: Booleano para alternar entre pipelines RAG e Agente.

### 3. `.env` e `.env.example`
- Adição das chaves de configuração citadas acima.

### 4. `requirements.txt`
- Inclusão da dependência `mcp`.

## 🔄 Fluxo de Trabalho (Workflow)

1. **Recepção:** Webhook do WAHA recebe a mensagem.
2. **Orquestração:** O Agente avalia se precisa de informações dos manuais ou dados do aluno.
3. **Execução de Ferramentas:**
    - Se "Manuais": Chama a ferramenta de busca vetorial (Advanced RAG).
    - Se "Dados Aluno": Chama a ferramenta correspondente no SUAP MCP (ex: `get_disciplines`).
4. **Geração:** O LLM sintetiza a resposta final com base em todos os dados coletados.
5. **Resposta:** Envio da mensagem formatada via WAHA.
