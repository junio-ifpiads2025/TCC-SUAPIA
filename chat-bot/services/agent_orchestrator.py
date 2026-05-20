"""
Orquestrador do Agente ReAct (Reason + Act) do SUAP-IA.

Combina duas fontes de conhecimento:
  1. SUAP API (via SUAPMCPClient) — dados acadêmicos pessoais do aluno (RF17, RF18).
  2. Pipeline RAG (manuais institucionais) — dúvidas sobre procedimentos do SUAP.

O loop ReAct permite que o LLM decida quantas ferramentas chamar e em qual ordem
antes de gerar a resposta final. O número máximo de iterações é configurável
via AGENT_MAX_ITERATIONS para evitar loops infinitos.

Conformidade com RN13:
  - O token do aluno nunca é logado.
  - O token é recuperado do Redis no momento da execução (não cacheado localmente).
  - Token ausente ou expirado encerra o fluxo com mensagem de relogin.
"""

import json
import os
from datetime import datetime, timezone, timedelta
from typing import Any

from openai import OpenAI
from dotenv import load_dotenv

from services import logger
from services.mcp_client import SUAPMCPClient
from config import AGENT_NAME

load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
MODELO_LLM_AGENTE = os.getenv("MODELO_LLM_AVANCADO", "gpt-4o")
SUAP_BASE_URL = os.getenv("SUAP_BASE_URL", "https://suap.ifpi.edu.br")
SUAP_TOKEN = os.getenv("SUAP_TOKEN", "")
MAX_ITERATIONS = int(os.getenv("AGENT_MAX_ITERATIONS", "5"))

AGENT_SYSTEM_PROMPT = os.getenv("SYSTEM_PROMPT", "").replace("{AGENT_NAME}", AGENT_NAME) or None

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
    Orquestrador de Agente ReAct com ferramentas SUAP + RAG.

    Usa o padrão tool_calling da OpenAI para decidir quando consultar o SUAP
    (dados dinâmicos do aluno) ou os manuais (RAG estático).
    """

    def __init__(self, mcp_client: SUAPMCPClient, rag_pipeline):
        self._mcp = mcp_client
        self._rag = rag_pipeline
        self._openai = OpenAI(api_key=OPENAI_API_KEY)
        self._tools = mcp_client.list_tools() + [_SEARCH_MANUALS_SCHEMA]
        logger.success("AGENTE", f"AgentOrchestrator pronto — {len(self._tools)} ferramenta(s) disponível(is).")

    def invoke(self, user_query: str, token: str = "", history: list[dict] | None = None) -> tuple[str, list[dict]]:
        """
        Executa o loop ReAct e retorna (resposta_final, metadados_rag).

        Valida o token antes de iniciar — se ausente, retorna mensagem de relogin
        sem acionar o LLM (RN13, RF17).

        O histórico de conversa (pares anteriores user/assistant) é injetado antes
        da mensagem atual, permitindo perguntas de acompanhamento sem novas chamadas
        ao SUAP. Ex: "quantas faltas posso ter em dev de jogos?" após listar disciplinas.

        O loop continua até o LLM parar de solicitar ferramentas ou
        MAX_ITERATIONS ser atingido. Ao atingir o limite, força uma síntese
        final com o contexto acumulado.
        """
        # RN13/RF17: token obrigatório para acionar ferramentas do SUAP
        if not token:
            logger.warn("AGENTE", "Token ausente — solicitando relogin ao usuário.")
            return "Sua sessão expirou. Envie qualquer mensagem para receber o link de login.", []

        logger.phase(1, "Agente: Iniciando loop ReAct")
        logger.info("AGENTE", f"Pergunta: {user_query}")

        # Data atual em BRT para que o agente saiba o ano/semestre correto
        brt = timezone(timedelta(hours=-3))
        now = datetime.now(brt)
        semestre_atual = f"{now.year}.{'1' if now.month <= 6 else '2'}"
        data_contexto = (
            f"Data atual: {now.strftime('%d/%m/%Y')} (horário de Brasília). "
            f"Semestre letivo atual: {semestre_atual}. "
            f"Use sempre esses valores quando o aluno se referir a 'esse ano', 'agora', 'atual' ou 'hoje'."
        )

        messages: list[dict[str, Any]] = []
        if AGENT_SYSTEM_PROMPT:
            messages.append({"role": "system", "content": AGENT_SYSTEM_PROMPT})

        # Contexto de data como mensagem de sistema separada — sempre atualizado
        messages.append({"role": "system", "content": data_contexto})

        # Injeta histórico da conversa antes da mensagem atual
        if history:
            messages.extend(history)
            logger.info("AGENTE", f"Histórico injetado: {len(history)} mensagem(ns) anteriores.")

        messages.append({"role": "user", "content": user_query})
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

            # Registra a mensagem do assistente no histórico da conversa
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

            # Sem chamadas de ferramentas → LLM gerou a resposta final
            if not msg.tool_calls:
                logger.success("AGENTE", "Loop encerrado — resposta final gerada.")
                return msg.content or "", rag_metadata

            # Executa cada ferramenta solicitada pelo LLM
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

        # Limite de iterações atingido — força síntese com o contexto acumulado
        logger.warn("AGENTE", f"Limite de {MAX_ITERATIONS} iterações atingido. Forçando síntese final.")
        final = self._openai.chat.completions.create(
            model=MODELO_LLM_AGENTE,
            messages=messages,
        )
        return final.choices[0].message.content or "", rag_metadata

    def _run_rag(self, query: str, rag_metadata: list[dict]) -> str:
        """
        Executa o pipeline RAG e retorna o contexto recuperado como string.
        O contexto bruto (não a resposta sintetizada) é retornado para que o
        agente ReAct possa combiná-lo com dados do SUAP se necessário.
        """
        logger.info("AGENTE", f"Buscando nos manuais: '{query}'")
        try:
            answer, context_str, metadata = self._rag.invoke(query)
            rag_metadata.extend(metadata)
            return context_str if context_str else answer
        except Exception as e:
            logger.error("AGENTE", f"Erro no pipeline RAG: {e}")
            return "Erro ao buscar nos manuais."


# ---------------------------------------------------------------------------
# Instância global (lazy) para o token de serviço (testes/admin)
# ---------------------------------------------------------------------------
_orchestrator: AgentOrchestrator | None = None


def get_orchestrator() -> AgentOrchestrator:
    """
    Retorna o orquestrador global inicializado com o SUAP_TOKEN de serviço.
    Usado apenas para testes — em produção cada aluno tem seu próprio token.
    """
    global _orchestrator
    if _orchestrator is None:
        from services.advanced_rag_agent import get_pipeline_avancado
        mcp_client = SUAPMCPClient(SUAP_BASE_URL, SUAP_TOKEN)
        _orchestrator = AgentOrchestrator(mcp_client, get_pipeline_avancado())
    return _orchestrator


def gerar_resposta_agente(
    pergunta: str,
    token: str = "",
    history: list[dict] | None = None,
) -> tuple[str, list[dict]]:
    """
    Ponto de entrada compatível com a interface dos outros pipelines (message_router).

    Sempre cria um SUAPMCPClient com o token individual do aluno (RF17, RN13).
    O token vem do Redis via message_router → get_token(chat_id).
    O histórico vem do Redis via thread_service.get_thread(chat_id).

    Se token estiver vazio (sessão expirada), retorna mensagem de relogin
    sem acionar o LLM.
    """
    effective_token = token or SUAP_TOKEN

    # RN13: token ausente — não aciona o agente, solicita novo login
    if not effective_token:
        return "Sua sessão expirou. Envie qualquer mensagem para receber o link de login.", []

    from services.advanced_rag_agent import get_pipeline_avancado
    mcp = SUAPMCPClient(SUAP_BASE_URL, effective_token)
    return AgentOrchestrator(mcp, get_pipeline_avancado()).invoke(
        pergunta, token=effective_token, history=history
    )
