"""
Cliente SUAP para tool-calling do agente ReAct.

Fala direto com a API REST do SUAP (https://suap.ifpi.edu.br/api/openapi.json),
usando as tags "Ensino" e "token" (mais /api/rh/eu e /api/rh/meus-vinculos para
identificar o perfil, ex.: professor). Cada ferramenta é uma entrada em
ENDPOINTS: adicionar uma tool nova = adicionar uma linha na tabela.

Conformidade com RN13:
- O token nunca aparece em logs (sanitize_log cobre 'authorization').
- Argumentos das ferramentas são logados normalmente (não contêm token).
- Erros da API retornam JSON estruturado em vez de lançar exceção,
  para que o LLM possa formular uma resposta amigável ao usuário.
"""

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from services import logger
from utils.security import sanitize_log

TIMEOUT = 10.0
MAX_PAGES = 5  # limite de páginas seguidas em endpoints paginados

_JSON_TYPES = {int: "integer", str: "string"}


@dataclass(frozen=True)
class Param:
    type: type
    description: str
    enum: tuple[str, ...] | None = None
    required: bool = True


@dataclass(frozen=True)
class Endpoint:
    path: str  # relativo a /api/ensino/ (ou absoluto, se começar com "/"); {nome} vira argumento de path
    description: str
    params: dict[str, Param] = field(default_factory=dict)


_SEMESTRE = Param(str, "Semestre no formato 'YYYY.N'. Exemplos: '2024.1', '2024.2'.")
_ANO = Param(int, "Ano letivo. Exemplo: 2024.")
_PERIODO = Param(int, "Período letivo numérico (1 ou 2).")
_ID_DIARIO = Param(int, "ID numérico do diário (obtido via get_diaries ou get_my_diaries).")

# ---------------------------------------------------------------------------
# Tabela de ferramentas (tag "Ensino" do OpenAPI)
# ---------------------------------------------------------------------------

ENDPOINTS: dict[str, Endpoint] = {
    # Identificação (tag "Gestão de Pessoas"): necessária para saber se o usuário é professor.
    "get_my_data": Endpoint(
        "/api/rh/eu/",
        "Retorna os dados pessoais do usuário autenticado (nome, e-mail, campus, foto e tipo_usuario: Aluno ou Servidor).",
    ),
    "get_my_vinculos": Endpoint(
        "/api/rh/meus-vinculos/",
        "Retorna os vínculos institucionais do usuário autenticado (Aluno e/ou Servidor/professor). Chame antes de get_my_diaries ou get_my_open_diaries para confirmar que o usuário é professor.",
    ),
    "get_student_data": Endpoint(
        "meus-dados-aluno/",
        "Retorna dados acadêmicos do aluno autenticado (curso, matriz, IRA, período de referência, situação, ingresso).",
    ),
    "get_graduation_requirements": Endpoint(
        "requisitos-conclusao/",
        "Retorna os requisitos para conclusão do curso: carga horária total, cumprida e pendências.",
    ),
    "get_my_periods": Endpoint(
        "meus-periodos-letivos/",
        "Lista os períodos letivos (ano e período) em que o usuário autenticado tem vínculo.",
    ),
    "get_periods": Endpoint(
        "periodos/",
        "Lista todos os períodos letivos existentes no SUAP, com data de início e fim.",
    ),
    "get_disciplines": Endpoint(
        "disciplinas/{semestre}/",
        "Lista as disciplinas do aluno em um semestre com notas, frequência, faltas e situação.",
        {"semestre": _SEMESTRE},
    ),
    "get_discipline_stages": Endpoint(
        "disciplinas/{disciplina}/etapas/",
        "Lista as etapas e avaliações (notas) de uma disciplina. O id vem de get_disciplines.",
        {"disciplina": Param(int, "ID numérico da disciplina (campo 'id' de get_disciplines).")},
    ),
    "get_report_card": Endpoint(
        "meu-boletim/{ano_letivo}/{periodo_letivo}/",
        "Retorna o boletim do aluno em um ano e período letivo: carga horária, faltas, frequência e situação por disciplina.",
        {"ano_letivo": _ANO, "periodo_letivo": _PERIODO},
    ),
    "get_upcoming_assessments": Endpoint(
        "minhas-proximas-avaliacoes/",
        "Lista as próximas avaliações do aluno com tipo, descrição, data, peso e diário.",
    ),
    "get_messages": Endpoint(
        "mensagens/entrada/{status}/",
        "Lista as mensagens da caixa de entrada do usuário no SUAP.",
        {
            "status": Param(
                str,
                "Filtro: 'nao-lidas' (padrão), 'lidas', 'todas' ou 'lixeira'.",
                enum=("nao-lidas", "lidas", "todas", "lixeira"),
                required=False,
            )
        },
    ),
    "get_diaries": Endpoint(
        "diarios/{semestre}/",
        "Lista os diários do usuário em um semestre: disciplina, professores, horários e local.",
        {"semestre": _SEMESTRE},
    ),
    "get_my_diaries": Endpoint(
        "meus-diarios/{ano_letivo}/{periodo_letivo}/",
        "Lista os diários do professor autenticado em um ano e período letivo. Exclusivo para Servidores (professores); confirme o vínculo com get_my_vinculos antes.",
        {"ano_letivo": _ANO, "periodo_letivo": _PERIODO},
    ),
    "get_my_open_diaries": Endpoint(
        "meus-diarios/",
        "Lista os diários abertos do professor autenticado. Exclusivo para Servidores (professores).",
    ),
    "get_diary_professors": Endpoint(
        "diarios/{id_diario}/professores/",
        "Lista os professores vinculados a um diário de classe.",
        {"id_diario": _ID_DIARIO},
    ),
    "get_diary_students": Endpoint(
        "diarios/{id_diario}/alunos/",
        "Lista os alunos matriculados em um diário de classe.",
        {"id_diario": _ID_DIARIO},
    ),
    "get_diary_classes": Endpoint(
        "diarios/{id_diario}/aulas/",
        "Lista as aulas registradas em um diário: etapa, data, conteúdo ministrado e faltas.",
        {"id_diario": _ID_DIARIO},
    ),
    "get_diary_assignments": Endpoint(
        "diarios/{id_diario}/trabalhos/",
        "Lista os trabalhos de um diário com título, etapa, data de solicitação e data limite.",
        {"id_diario": _ID_DIARIO},
    ),
    "get_diary_materials": Endpoint(
        "diarios/{id_diario}/materiais/",
        "Lista os materiais de aula de um diário.",
        {"id_diario": _ID_DIARIO},
    ),
    "get_diary_topics": Endpoint(
        "diarios/{id_diario}/topicos/",
        "Lista os tópicos do fórum de um diário.",
        {"id_diario": _ID_DIARIO},
    ),
    "get_assignment": Endpoint(
        "trabalhos/{id_trabalho}/",
        "Retorna os detalhes de um trabalho (descrição, datas, etapa).",
        {"id_trabalho": Param(int, "ID numérico do trabalho (obtido via get_diary_assignments).")},
    ),
    "get_material": Endpoint(
        "materiais/{id_material}/",
        "Retorna os detalhes de um material de aula.",
        {"id_material": Param(int, "ID numérico do material (obtido via get_diary_materials).")},
    ),
    "get_virtual_classes": Endpoint(
        "minhas-turmas-virtuais/{ano_letivo}/{periodo_letivo}/",
        "Lista as turmas virtuais do usuário em um ano e período letivo.",
        {"ano_letivo": _ANO, "periodo_letivo": _PERIODO},
    ),
    "get_virtual_class": Endpoint(
        "minha-turma-virtual/{pk}/",
        "Retorna os detalhes de uma turma virtual: professores, participantes, aulas e materiais.",
        {"pk": Param(int, "ID numérico da turma virtual (obtido via get_virtual_classes).")},
    ),
}

# Ferramentas que combinam mais de uma chamada (não cabem na tabela).
_COMPOSITE: dict[str, Endpoint] = {
    "get_all_disciplines": Endpoint(
        "",
        "Retorna as disciplinas cursadas pelo aluno em todos os períodos, sem precisar informar semestre. Prefira quando o usuário quiser histórico completo ou perguntar sobre uma disciplina sem especificar o período.",
    ),
}


def _build_schema(name: str, ep: Endpoint) -> dict:
    properties = {}
    for pname, p in ep.params.items():
        prop: dict[str, Any] = {"type": _JSON_TYPES[p.type], "description": p.description}
        if p.enum:
            prop["enum"] = list(p.enum)
        properties[pname] = prop
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": ep.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": [n for n, p in ep.params.items() if p.required],
            },
        },
    }


_TOOL_SCHEMAS: list[dict] = [
    _build_schema(n, ep) for n, ep in {**ENDPOINTS, **_COMPOSITE}.items()
]


class SuapAPIError(Exception):
    """Erro da API do SUAP com mensagem segura para o usuário final."""


def normalize_base_url(url: str) -> str:
    """Remove barra final e o sufixo '/api/v2' caso o administrador o tenha incluído."""
    url = url.rstrip("/")
    return url.removesuffix("/api/v2")


class SUAPMCPClient:
    """
    Cliente da API do SUAP (Ensino) que expõe as ferramentas no formato OpenAI tool_calling.

    Uma instância é criada por requisição do usuário, com o token individual do aluno
    recuperado do Redis (RF17). Nunca reutiliza token de outro usuário.
    """

    def __init__(self, base_url: str, token: str):
        if not token:
            logger.warn("MCP_CLIENT", "Token ausente — ferramentas SUAP retornarão erro.")
        self._base_url = normalize_base_url(base_url)
        # O token fica só no header HTTP e nunca é logado (RN13).
        self._token = token
        logger.success("MCP_CLIENT", f"SUAPMCPClient inicializado → {self._base_url}")

    # ------------------------------------------------------------------
    # Interface usada pelo AgentOrchestrator
    # ------------------------------------------------------------------

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
        except SuapAPIError as e:
            logger.error("MCP_CLIENT", f"Erro SUAP em {name}: {e}")
            return json.dumps({"error": str(e)}, ensure_ascii=False)
        except Exception as e:
            logger.error("MCP_CLIENT", f"Erro inesperado em {name}: {e}")
            return json.dumps({"error": f"Ferramenta '{name}' temporariamente indisponível."}, ensure_ascii=False)

    # ------------------------------------------------------------------
    # Tag "token" (não expostos ao LLM)
    # ------------------------------------------------------------------

    def verify_token(self) -> bool:
        """POST /api/token/verify — True se o access token ainda é válido."""
        try:
            resp = httpx.post(
                f"{self._base_url}/api/token/verify",
                json={"token": self._token},
                timeout=TIMEOUT,
            )
        except httpx.HTTPError:
            return False
        return resp.status_code == 200

    def refresh_token(self, refresh: str) -> str | None:
        """POST /api/token/refresh — retorna o novo access token ou None se o refresh expirou."""
        try:
            resp = httpx.post(
                f"{self._base_url}/api/token/refresh",
                json={"refresh": refresh},
                timeout=TIMEOUT,
            )
        except httpx.HTTPError:
            return None
        if resp.status_code != 200:
            return None
        self._token = resp.json().get("access", self._token)
        return self._token

    # ------------------------------------------------------------------
    # Internos
    # ------------------------------------------------------------------

    def _dispatch(self, name: str, args: dict) -> Any:
        if name == "get_all_disciplines":
            return self._get_all_disciplines()
        ep = ENDPOINTS.get(name)
        if ep is None:
            raise ValueError(f"Ferramenta desconhecida: '{name}'")

        path_args = {}
        for pname, p in ep.params.items():
            if pname in args and args[pname] not in (None, ""):
                path_args[pname] = p.type(args[pname])
            elif p.required:
                raise SuapAPIError(f"Argumento obrigatório ausente: '{pname}'.")
            elif p.enum:
                path_args[pname] = p.enum[0]

        path = ep.path.format(**path_args)
        result = self._get(path if path.startswith("/") else f"/api/ensino/{path}")

        # RF20: matrícula inativa — nenhuma disciplina no semestre informado
        if name == "get_disciplines" and not result:
            return {
                "aviso": (
                    "Nenhuma disciplina encontrada para o semestre informado. "
                    "O aluno pode não ter matrícula ativa neste período. "
                    "Oriente-o a verificar períodos anteriores ou contatar a coordenação."
                )
            }
        return result

    def _get_all_disciplines(self) -> list:
        periodos = self._get("/api/ensino/meus-periodos-letivos/")
        disciplinas: list = []
        for p in periodos:
            semestre = f"{p['ano_letivo']}.{p['periodo_letivo']}"
            for d in self._get(f"/api/ensino/disciplinas/{semestre}/"):
                disciplinas.append({"semestre": semestre, **d})
        return disciplinas

    def _get(self, path: str) -> Any:
        """GET autenticado. Em endpoints paginados segue 'next' até MAX_PAGES e devolve a lista."""
        url: str | None = f"{self._base_url}{path}"
        headers = {"Authorization": f"Bearer {self._token}"}
        items: list = []
        pages = 0
        try:
            with httpx.Client(timeout=TIMEOUT, headers=headers) as client:
                while url and pages < MAX_PAGES:
                    resp = client.get(url)
                    self._raise_for_status(resp)
                    data = resp.json()
                    if not (isinstance(data, dict) and "results" in data):
                        return data  # recurso único, não paginado
                    items.extend(data["results"])
                    url = data.get("next")
                    pages += 1
        except httpx.TimeoutException:
            raise SuapAPIError("O SUAP demorou demais para responder. Tente novamente em instantes.")
        except httpx.HTTPError:
            raise SuapAPIError("Não foi possível conectar ao SUAP no momento.")
        return items

    @staticmethod
    def _raise_for_status(resp: httpx.Response) -> None:
        if resp.status_code < 400:
            return
        messages = {
            401: "Sessão expirada. O usuário precisa fazer login novamente.",
            403: "Acesso negado: o perfil do usuário não tem permissão para este recurso.",
            404: "Recurso não encontrado no SUAP.",
        }
        raise SuapAPIError(messages.get(resp.status_code, f"O SUAP retornou erro {resp.status_code}."))
