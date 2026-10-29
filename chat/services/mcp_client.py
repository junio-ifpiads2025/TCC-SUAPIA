"""
Cliente SUAP para tool-calling do agente ReAct.

Encapsula a biblioteca suap_api e expõe as ferramentas no formato
OpenAI tool-calling (lista de schemas + método call_tool).

Conformidade com RN13:
- O token nunca aparece em logs (sanitize_log cobre 'authorization').
- Argumentos das ferramentas são logados normalmente (não contêm token).
- Erros da API retornam JSON estruturado em vez de lançar exceção,
  para que o LLM possa formular uma resposta amigável ao usuário.
"""

import json
from typing import Any

from suap_api import SuapClient
from suap_api.exceptions import SuapError

from services import logger
from utils.security import sanitize_log

# ---------------------------------------------------------------------------
# Schemas das ferramentas no formato OpenAI tool_calling
# ---------------------------------------------------------------------------

_TOOL_SCHEMAS: list[dict] = [
    {
        "type": "function",
        "function": {
            "name": "get_my_data",
            "description": "Retorna dados pessoais do usuário autenticado no SUAP (nome, CPF, e-mail, matrícula, foto).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_student_data",
            "description": "Retorna dados acadêmicos do aluno autenticado (curso, IRA, período de referência, situação e matrícula).",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_periods",
            "description": "Lista todos os semestres letivos disponíveis no SUAP.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_disciplines",
            "description": "Lista as disciplinas de um semestre com notas, frequência e situação de aprovação.",
            "parameters": {
                "type": "object",
                "properties": {
                    "semestre": {
                        "type": "string",
                        "description": "Semestre no formato 'YYYY.N'. Exemplos: '2024.1', '2024.2'.",
                    }
                },
                "required": ["semestre"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_vinculo",
            "description": "Retorna o vínculo institucional do usuário autenticado: indica se é Aluno e/ou Servidor (professor). Use antes de get_my_diaries para verificar se o usuário tem perfil de professor.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_all_disciplines",
            "description": "Retorna todas as disciplinas cursadas pelo aluno em todos os semestres sem precisar informar um semestre específico. Prefira quando o usuário quiser histórico completo ou perguntar sobre uma disciplina sem especificar o período.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_my_diaries",
            "description": "Lista os diários do professor autenticado em um ano e período letivo. Exclusivo para Servidores (professores). Retorna erro se o usuário for Aluno. Use get_my_vinculo() para verificar o vínculo antes de chamar esta ferramenta.",
            "parameters": {
                "type": "object",
                "properties": {
                    "ano_letivo": {
                        "type": "integer",
                        "description": "Ano letivo. Exemplo: 2024.",
                    },
                    "periodo_letivo": {
                        "type": "integer",
                        "description": "Período letivo numérico (1 ou 2).",
                    },
                },
                "required": ["ano_letivo", "periodo_letivo"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_diary_classes",
            "description": "Lista as aulas registradas em um diário de classe: data, conteúdo ministrado e faltas.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_diario": {
                        "type": "integer",
                        "description": "ID numérico do diário (obtido via get_diaries).",
                    }
                },
                "required": ["id_diario"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_diary_professors",
            "description": "Lista os professores vinculados a um diário de classe.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_diario": {
                        "type": "integer",
                        "description": "ID numérico do diário (obtido via get_diaries).",
                    }
                },
                "required": ["id_diario"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_diary_assignments",
            "description": "Lista os trabalhos e avaliações de um diário com título e data de entrega.",
            "parameters": {
                "type": "object",
                "properties": {
                    "id_diario": {
                        "type": "integer",
                        "description": "ID numérico do diário (obtido via get_diaries).",
                    }
                },
                "required": ["id_diario"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_messages",
            "description": "Lista as mensagens da caixa de entrada do usuário no SUAP.",
            "parameters": {
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "enum": ["nao_lidas", "lidas", "todas"],
                        "description": "Filtro de leitura: 'nao_lidas' (padrão), 'lidas' ou 'todas'.",
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_graduation_requirements",
            "description": "Retorna os requisitos para conclusão do curso: carga horária total, cumprida e pendências.",
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
]


class SUAPMCPClient:
    """
    Wrapper sobre suap_api que expõe as ferramentas do SUAP no formato OpenAI tool_calling.

    Uma instância é criada por requisição do usuário, com o token individual do aluno
    recuperado do Redis (RF17). Nunca reutiliza token de outro usuário.
    """

    def __init__(self, base_url: str, token: str):
        if not token:
            logger.warn("MCP_CLIENT", "Token ausente — ferramentas SUAP retornarão erro.")
        # O token é armazenado internamente pelo SuapClient e usado nos headers HTTP.
        # Nunca é logado diretamente (RN13).
        self._client = SuapClient(base_url, token=token)
        logger.success("MCP_CLIENT", f"SUAPMCPClient inicializado → {base_url}")

    def list_tools(self) -> list[dict]:
        """Retorna os schemas de todas as ferramentas no formato OpenAI."""
        return _TOOL_SCHEMAS

    def call_tool(self, name: str, arguments: dict[str, Any]) -> str:
        """
        Executa uma ferramenta SUAP e retorna o resultado como string JSON.

        Erros são capturados e retornados como JSON estruturado para que o LLM
        possa formular uma resposta amigável sem expor detalhes técnicos ao aluno.
        Os argumentos são sanitizados antes de logar (RN13).
        """
        logger.info("MCP_CLIENT", f"Executando: {name}({sanitize_log(arguments)})")
        try:
            result = self._dispatch(name, arguments)
            logger.success("MCP_CLIENT", f"{name} concluído.")
            return json.dumps(result, ensure_ascii=False, indent=2)
        except SuapError as e:
            logger.error("MCP_CLIENT", f"Erro SUAP em {name}: {e}")
            return json.dumps({"error": str(e)})
        except Exception as e:
            logger.error("MCP_CLIENT", f"Erro inesperado em {name}: {e}")
            return json.dumps({"error": f"Ferramenta '{name}' temporariamente indisponível."})

    def _dispatch(self, name: str, args: dict) -> Any:
        """Roteia a chamada para o método correto da suap_api."""
        match name:
            case "get_my_data":
                return self._client.comum.get_my_data().raw
            case "get_student_data":
                return self._client.edu.get_student_data().raw
            case "get_periods":
                return [p.raw for p in self._client.edu.get_periods()]
            case "get_disciplines":
                result = [d.raw for d in self._client.edu.get_disciplines(args["semestre"])]
                # RF20: matrícula inativa — nenhuma disciplina no semestre informado
                if not result:
                    return {
                        "aviso": (
                            "Nenhuma disciplina encontrada para o semestre informado. "
                            "O aluno pode não ter matrícula ativa neste período. "
                            "Oriente-o a verificar períodos anteriores ou contatar a coordenação."
                        )
                    }
                return result
            case "get_my_vinculo":
                tipo_vinculo = self._client.comum.get_person_links()
                return {"tipo_vinculo": tipo_vinculo}
            case "get_all_disciplines":
                return [d.raw for d in self._client.edu.get_all_disciplines()]
            case "get_my_diaries":
                tipo_vinculo = self._client.comum.get_person_links()
                if tipo_vinculo != "Servidor":
                    return {"erro": "Acesso negado", "detalhe": "Este endpoint é exclusivo para Servidores (professores)."}
                return [d.raw for d in self._client.edu.get_my_diaries(args["ano_letivo"], args["periodo_letivo"])]
            case "get_diary_classes":
                return [c.raw for c in self._client.edu.get_diary_classes(args["id_diario"])]
            case "get_diary_professors":
                return [p.raw for p in self._client.edu.get_diary_professors(args["id_diario"])]
            case "get_diary_assignments":
                return [a.raw for a in self._client.edu.get_diary_assignments(args["id_diario"])]
            case "get_messages":
                status = args.get("status", "nao_lidas")
                return [m.raw for m in self._client.edu.get_messages(status)]
            case "get_graduation_requirements":
                return self._client.edu.get_graduation_requirements().raw
            case _:
                raise ValueError(f"Ferramenta desconhecida: '{name}'")
