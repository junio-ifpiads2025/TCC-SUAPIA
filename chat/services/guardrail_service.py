"""
Guardrails do SUAP-IA: regras de entrada, saída e de comportamento (prompt).

- input : `check_input` avalia a mensagem do usuário antes do agente (block/replace).
- output: `apply_output` filtra a resposta do agente (mask/replace/block).
- prompt: regras `instruct` viram um bloco de texto anexado ao system prompt.

As regras ficam no Postgres (tabela `guardrail`) e são mantidas compiladas em
memória; cada escrita recarrega o cache (processo único, ver plano do painel).
Nunca registra o texto do usuário.
"""

import re
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field

from sqlalchemy import delete, select

from models.database import AsyncSessionLocal, Guardrail
from services import logger

MAX_PATTERN_LEN = 500
MAX_TEXT_LEN = 2000
TEST_TIMEOUT_S = 2.0
MASK = "***"
DEFAULT_RESPONSE = "Desculpe, não posso ajudar com isso."

SCOPES = ("input", "output", "prompt")
MATCH_TYPES = ("keyword", "regex")
ACTIONS = ("block", "mask", "replace", "instruct")

# Quantificador aplicado a grupo que já contém quantificador: (a+)+, (.*)*, (a|b*){2,}
_NESTED_QUANT = re.compile(r"\((?:[^()\\]|\\.)*[+*](?:[^()\\]|\\.)*\)\s*(?:[+*]|\{\d+,\d*\})")


class GuardrailError(ValueError):
    """Regra inválida (campos, regex ou combinação scope/action)."""


class GuardrailNotFound(LookupError):
    """Regra inexistente."""


@dataclass
class GuardrailResult:
    blocked: bool = False
    response: str | None = None
    rule: str | None = None


@dataclass
class _Rule:
    id: int
    name: str
    scope: str
    action: str
    response: str | None
    instruction: str | None
    priority: int
    regex: "re.Pattern | None" = field(default=None)


_rules: list[_Rule] = []


# ── Persistência (isolada para facilitar testes) ─────────────────────────────

def _to_dict(g: Guardrail) -> dict:
    return {
        "id": g.id, "name": g.name, "description": g.description, "scope": g.scope,
        "match_type": g.match_type, "pattern": g.pattern, "action": g.action,
        "response": g.response, "instruction": g.instruction,
        "priority": g.priority, "enabled": g.enabled, "created_at": g.created_at,
    }


async def _db_list() -> list[dict]:
    async with AsyncSessionLocal() as s:
        rows = (await s.execute(select(Guardrail).order_by(Guardrail.priority, Guardrail.id))).scalars().all()
        return [_to_dict(r) for r in rows]


async def _db_insert(data: dict) -> dict:
    async with AsyncSessionLocal() as s:
        g = Guardrail(**data)
        s.add(g)
        await s.commit()
        await s.refresh(g)
        return _to_dict(g)


async def _db_update(rule_id: int, data: dict) -> dict:
    async with AsyncSessionLocal() as s:
        g = await s.get(Guardrail, rule_id)
        if g is None:
            raise GuardrailNotFound(rule_id)
        for k, v in data.items():
            setattr(g, k, v)
        await s.commit()
        await s.refresh(g)
        return _to_dict(g)


async def _db_delete(rule_id: int) -> None:
    async with AsyncSessionLocal() as s:
        res = await s.execute(delete(Guardrail).where(Guardrail.id == rule_id))
        await s.commit()
        if res.rowcount == 0:
            raise GuardrailNotFound(rule_id)


# ── Validação e compilação ───────────────────────────────────────────────────

def _split_terms(pattern: str) -> list[str]:
    return [t.strip() for t in re.split(r"[\n,]", pattern) if t.strip()]


def _compile(match_type: str, pattern: str) -> "re.Pattern":
    if match_type == "keyword":
        terms = _split_terms(pattern)
        if not terms:
            raise GuardrailError("Informe ao menos um termo.")
        return re.compile("|".join(re.escape(t) for t in terms), re.IGNORECASE)
    if _NESTED_QUANT.search(pattern):
        raise GuardrailError("Regex rejeitada: quantificadores aninhados (risco de ReDoS).")
    try:
        rx = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        raise GuardrailError(f"Regex inválida: {e}") from e
    if rx.match(""):
        raise GuardrailError("Regex rejeitada: casa com texto vazio.")
    return rx


def validate(data: dict) -> dict:
    """Valida e normaliza os campos de uma regra; levanta GuardrailError."""
    name = (data.get("name") or "").strip()
    if not name or len(name) > 100:
        raise GuardrailError("Nome obrigatório (até 100 caracteres).")
    scope = (data.get("scope") or "").strip()
    action = (data.get("action") or "").strip()
    if scope not in SCOPES:
        raise GuardrailError("Escopo inválido.")
    if action not in ACTIONS:
        raise GuardrailError("Ação inválida.")
    if (action == "instruct") != (scope == "prompt"):
        raise GuardrailError("A ação 'instruct' é exclusiva do escopo 'prompt' e vice-versa.")
    if action == "mask" and scope != "output":
        raise GuardrailError("A ação 'mask' só vale para o escopo 'output'.")

    try:
        priority = int(data.get("priority", 100))
    except (TypeError, ValueError) as e:
        raise GuardrailError("Prioridade deve ser inteira.") from e

    out = {
        "name": name,
        "description": (data.get("description") or "").strip() or None,
        "scope": scope, "action": action, "priority": priority,
        "enabled": bool(data.get("enabled", True)),
        "match_type": None, "pattern": None, "response": None, "instruction": None,
    }
    if scope == "prompt":
        instruction = (data.get("instruction") or "").strip()
        if not instruction or len(instruction) > 2000:
            raise GuardrailError("Instrução obrigatória (até 2000 caracteres).")
        out["instruction"] = instruction
        return out

    match_type = (data.get("match_type") or "").strip()
    pattern = (data.get("pattern") or "").strip()
    if match_type not in MATCH_TYPES:
        raise GuardrailError("Tipo de correspondência inválido.")
    if not pattern or len(pattern) > MAX_PATTERN_LEN:
        raise GuardrailError(f"Padrão obrigatório (até {MAX_PATTERN_LEN} caracteres).")
    _compile(match_type, pattern)
    out.update(match_type=match_type, pattern=pattern)
    if action != "mask":
        response = (data.get("response") or "").strip()
        if len(response) > 2000:
            raise GuardrailError("Resposta longa demais (máx. 2000).")
        out["response"] = response or None
    return out


def _build(rows: list[dict]) -> list[_Rule]:
    rules: list[_Rule] = []
    for r in rows:
        if not r["enabled"]:
            continue
        rx = None
        if r["scope"] != "prompt":
            try:
                rx = _compile(r["match_type"], r["pattern"])
            except GuardrailError as e:
                logger.warn("GUARDRAIL", f"regra id={r['id']} ignorada: {e}")
                continue
        rules.append(_Rule(r["id"], r["name"], r["scope"], r["action"],
                           r["response"], r["instruction"], r["priority"], rx))
    rules.sort(key=lambda x: (x.priority, x.id))
    return rules


async def reload() -> None:
    """Recarrega o cache compilado a partir do Postgres."""
    global _rules
    _rules = _build(await _db_list())


async def startup() -> None:
    await reload()
    logger.success("GUARDRAIL", f"{len(_rules)} regra(s) ativa(s) carregada(s).")


# ── CRUD ─────────────────────────────────────────────────────────────────────

async def list_rules() -> list[dict]:
    return await _db_list()


async def create_rule(data: dict) -> dict:
    row = await _db_insert(validate(data))
    await reload()
    return row


async def update_rule(rule_id: int, data: dict) -> dict:
    row = await _db_update(rule_id, validate(data))
    await reload()
    return row


async def delete_rule(rule_id: int) -> None:
    await _db_delete(rule_id)
    await reload()


# ── Avaliação (síncrona, sem I/O) ────────────────────────────────────────────

def check_input(text: str) -> GuardrailResult:
    """Primeira regra de entrada que casar bloqueia a mensagem (ordem por priority)."""
    text = text or ""
    for r in _rules:
        if r.scope == "input" and r.regex.search(text):
            return GuardrailResult(True, r.response or DEFAULT_RESPONSE, r.name)
    return GuardrailResult()


def apply_output(text: str) -> tuple[str, list[str]]:
    """Aplica as regras de saída; replace/block substitui tudo e encerra."""
    hit: list[str] = []
    for r in _rules:
        if r.scope != "output" or not r.regex.search(text):
            continue
        hit.append(r.name)
        if r.action == "mask":
            text = r.regex.sub(MASK, text)
        else:
            return r.response or DEFAULT_RESPONSE, hit
    return text, hit


def instruction_block() -> str:
    """Bloco 'Regras de comportamento' com as instruções ativas (ou vazio)."""
    items = [r.instruction for r in _rules if r.scope == "prompt" and r.instruction]
    if not items:
        return ""
    return "Regras de comportamento:\n" + "\n".join(f"- {i}" for i in items)


def _run_test(text: str) -> dict:
    t0 = time.perf_counter()
    inp = check_input(text)
    out_text, out_rules = apply_output(text)
    return {
        "input": {"blocked": inp.blocked, "response": inp.response, "rule": inp.rule},
        "output": {"text": out_text, "rules": out_rules},
        "elapsed_ms": int((time.perf_counter() - t0) * 1000),
    }


def test(text: str) -> dict:
    """Aplica todas as regras a um texto de exemplo, com tempo limite; nada é enviado."""
    text = (text or "")[:MAX_TEXT_LEN]
    ex = ThreadPoolExecutor(max_workers=1)
    try:
        return ex.submit(_run_test, text).result(timeout=TEST_TIMEOUT_S)
    except FutureTimeout:
        return {"error": "Tempo limite excedido ao avaliar as regras."}
    finally:
        ex.shutdown(wait=False)
