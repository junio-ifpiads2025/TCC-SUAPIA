import json

import httpx
import pytest

from services import mcp_client
from services.mcp_client import SUAPMCPClient

BASE = "https://suap.test"


@pytest.fixture
def client_with(monkeypatch):
    """Cria um SUAPMCPClient cujas chamadas HTTP são atendidas por `handler`."""

    def factory(handler):
        real_client = httpx.Client
        monkeypatch.setattr(
            mcp_client.httpx,
            "Client",
            lambda **kw: real_client(transport=httpx.MockTransport(handler), **kw),
        )
        return SUAPMCPClient(BASE, "tok")

    return factory


def test_schemas_generated():
    names = [t["function"]["name"] for t in SUAPMCPClient(BASE, "tok").list_tools()]
    assert "get_student_data" in names and "get_all_disciplines" in names
    assert len(names) == len(set(names))
    msg = next(t for t in SUAPMCPClient(BASE, "tok").list_tools() if t["function"]["name"] == "get_messages")
    assert msg["function"]["parameters"]["required"] == []


def test_bearer_and_path(client_with):
    seen = {}

    def handler(req):
        seen["url"], seen["auth"] = str(req.url), req.headers["authorization"]
        return httpx.Response(200, json={"curso": "ADS"})

    out = json.loads(client_with(handler).call_tool("get_student_data", {}))
    assert out == {"curso": "ADS"}
    assert seen == {"url": f"{BASE}/api/ensino/meus-dados-aluno/", "auth": "Bearer tok"}


def test_pagination_followed(client_with):
    def handler(req):
        if req.url.params.get("page") == "2":
            return httpx.Response(200, json={"results": [{"id": 2}], "next": None})
        return httpx.Response(200, json={"results": [{"id": 1}], "next": f"{BASE}/x/?page=2"})

    out = json.loads(client_with(handler).call_tool("get_periods", {}))
    assert [r["id"] for r in out] == [1, 2]


def test_message_status_default(client_with):
    urls = []

    def handler(req):
        urls.append(req.url.path)
        return httpx.Response(200, json={"results": []})

    client_with(handler).call_tool("get_messages", {})
    assert urls == ["/api/ensino/mensagens/entrada/nao-lidas/"]


@pytest.mark.parametrize("status,fragment", [(401, "Sessão expirada"), (403, "Acesso negado"), (404, "não encontrado")])
def test_http_errors(client_with, status, fragment):
    out = json.loads(client_with(lambda r: httpx.Response(status)).call_tool("get_my_diaries", {"ano_letivo": 2026, "periodo_letivo": 1}))
    assert fragment in out["error"]


def test_missing_arg(client_with):
    out = json.loads(client_with(lambda r: httpx.Response(200, json={})).call_tool("get_disciplines", {}))
    assert "semestre" in out["error"]


def test_empty_semester_warns(client_with):
    out = json.loads(client_with(lambda r: httpx.Response(200, json={"results": []})).call_tool("get_disciplines", {"semestre": "2026.1"}))
    assert "aviso" in out


def test_all_disciplines_composite(client_with):
    def handler(req):
        if req.url.path.endswith("meus-periodos-letivos/"):
            return httpx.Response(200, json={"results": [{"ano_letivo": 2025, "periodo_letivo": 2}, {"ano_letivo": 2026, "periodo_letivo": 1}]})
        return httpx.Response(200, json={"results": [{"id": 1}]})

    out = json.loads(client_with(handler).call_tool("get_all_disciplines", {}))
    assert [d["semestre"] for d in out] == ["2025.2", "2026.1"]


def test_unknown_tool(client_with):
    out = json.loads(client_with(lambda r: httpx.Response(200, json={})).call_tool("nope", {}))
    assert "indisponível" in out["error"]


def test_rh_endpoints_use_absolute_path(client_with):
    urls = []

    def handler(req):
        urls.append(req.url.path)
        return httpx.Response(200, json={"results": [{"tipo": "Servidor"}]})

    c = client_with(handler)
    out = json.loads(c.call_tool("get_my_vinculos", {}))
    c.call_tool("get_my_data", {})
    assert out == [{"tipo": "Servidor"}]
    assert urls == ["/api/rh/meus-vinculos/", "/api/rh/eu/"]
