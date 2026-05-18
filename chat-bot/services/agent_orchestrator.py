import json
import os
from typing import Any

from openai import OpenAI
from dotenv import load_dotenv

from services import logger
from services.mcp_client import SUAPMCPClient

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODELO_LLM_AGENTE = os.getenv("MODELO_LLM_AVANCADO", "gpt-4o")
SUAP_BASE_URL = os.getenv("SUAP_BASE_URL", "https://suap.ifpi.edu.br")
SUAP_TOKEN = os.getenv("SUAP_TOKEN", "")
MAX_ITERATIONS = int(os.getenv("AGENT_MAX_ITERATIONS", "5"))

AGENT_SYSTEM_PROMPT = os.getenv(
    "AGENT_SYSTEM_PROMPT",
)

# Schema da ferramenta de busca nos manuais (encapsula o pipeline RAG)
_SEARCH_MANUALS_SCHEMA = {
    "type": "function",
    "function": {
        "name": "search_manuals",
        "description": (
            "Busca informações nos manuais oficiais do SUAP/IFPI. "
            "Use para responder dúvidas sobre procedimentos, funcionalidades e regras institucionais. "
            "Exemplos: 'como trancar matrícula', 'prazo para recurso de notas', 'como emitir declaração'."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Pergunta ou termo a buscar nos manuais do SUAP.",
                }
            },
            "required": ["query"],
        },
    },
}


class AgentOrchestrator:
    """
    Orquestrador de Agente ReAct (Reason + Act) com ferramentas SUAP + RAG.

    Usa o padrão tool_calling da OpenAI para decidir quando consultar o SUAP
    (dados dinâmicos) ou os manuais (RAG).
    """

    def __init__(self, mcp_client: SUAPMCPClient, rag_pipeline):
        self._mcp = mcp_client
        self._rag = rag_pipeline
        self._openai = OpenAI(api_key=OPENAI_API_KEY)
        self._tools = mcp_client.list_tools() + [_SEARCH_MANUALS_SCHEMA]
        logger.success("AGENTE", f"AgentOrchestrator pronto — {len(self._tools)} ferramenta(s) disponível(is).")

    def invoke(self, user_query: str) -> tuple[str, list[dict]]:
        """
        Executa o loop ReAct e retorna (resposta_final, metadados_rag).

        O loop continua até o LLM parar de solicitar ferramentas ou
        MAX_ITERATIONS ser atingido.
        """
        logger.phase(1, "Agente: Iniciando loop ReAct")
        logger.info("AGENTE", f"Pergunta: {user_query}")

        messages: list[dict[str, Any]] = [
            {"role": "system", "content": AGENT_SYSTEM_PROMPT},
            {"role": "user", "content": user_query},
        ]
        rag_metadata: list[dict] = []

        for iteration in range(1, MAX_ITERATIONS + 1):
            logger.info("AGENTE", f"Iteração {iteration}/{MAX_ITERATIONS}")

            response = self._openai.chat.completions.create(
                model=MODELO_LLM_AGENTE,
                messages=messages,
                tools=self._tools,
                tool_choice="auto",
            )

            msg = response.choices[0].message

            # Adiciona a mensagem do assistente ao histórico
            assistant_entry: dict[str, Any] = {
                "role": "assistant",
                "content": msg.content,
            }
            if msg.tool_calls:
                assistant_entry["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in msg.tool_calls
                ]
            messages.append(assistant_entry)

            # Sem chamadas de ferramentas → resposta final pronta
            if not msg.tool_calls:
                logger.success("AGENTE", "Loop encerrado — resposta final gerada.")
                return msg.content or "", rag_metadata

            # Executa cada ferramenta solicitada
            for tool_call in msg.tool_calls:
                tool_name = tool_call.function.name
                tool_args = json.loads(tool_call.function.arguments)
                logger.info("AGENTE", f"→ {tool_name}({tool_args})")

                if tool_name == "search_manuals":
                    tool_result = self._run_rag(tool_args["query"], rag_metadata)
                else:
                    tool_result = self._mcp.call_tool(tool_name, tool_args)

                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": tool_result,
                })

        # Limite de iterações atingido — força síntese sem ferramentas
        logger.warn("AGENTE", f"Limite de {MAX_ITERATIONS} iterações atingido. Forçando síntese final.")
        final = self._openai.chat.completions.create(
            model=MODELO_LLM_AGENTE,
            messages=messages,
        )
        return final.choices[0].message.content or "", rag_metadata

    def _run_rag(self, query: str, rag_metadata: list[dict]) -> str:
        """Executa o pipeline RAG e retorna o contexto recuperado como string."""
        logger.info("AGENTE", f"Buscando nos manuais: '{query}'")
        try:
            answer, context_str, metadata = self._rag.invoke(query)
            rag_metadata.extend(metadata)
            # Retorna o contexto bruto para o agente sintetizar a resposta final
            return context_str if context_str else answer
        except Exception as e:
            logger.error("AGENTE", f"Erro no pipeline RAG: {e}")
            return "Erro ao buscar nos manuais."


# ---------------------------------------------------------------------------
# Instância global (lazy)
# ---------------------------------------------------------------------------
_orchestrator: AgentOrchestrator | None = None


def get_orchestrator() -> AgentOrchestrator:
    global _orchestrator
    if _orchestrator is None:
        from services.advanced_rag_agent import get_pipeline_avancado
        mcp_client = SUAPMCPClient(SUAP_BASE_URL, SUAP_TOKEN)
        _orchestrator = AgentOrchestrator(mcp_client, get_pipeline_avancado())
    return _orchestrator


def gerar_resposta_agente(pergunta: str) -> tuple[str, list[dict]]:
    """Ponto de entrada compatível com a interface dos outros pipelines."""
    return get_orchestrator().invoke(pergunta)
