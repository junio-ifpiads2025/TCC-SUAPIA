import asyncio
import functools


def arun(fn):
    """Roda teste async sem plugin (pytest-asyncio não instalado)."""
    @functools.wraps(fn)
    def wrapper(*a, **kw):
        return asyncio.run(fn(*a, **kw))
    return wrapper


import pytest

from services import guardrail_service as gs


def rows(*specs):
    out = []
    for i, d in enumerate(specs, 1):
        base = {"id": i, "name": f"r{i}", "description": None, "match_type": "keyword",
                "pattern": None, "response": None, "instruction": None,
                "priority": 100, "enabled": True}
        base.update(d)
        out.append(base)
    return out


@pytest.fixture
def load(monkeypatch):
    def _load(*specs):
        gs._rules = gs._build(rows(*specs))
    yield _load
    gs._rules = []


def test_input_block_keyword(load):
    load({"scope": "input", "action": "block", "pattern": "senha, cartão", "response": "Não posso."})
    r = gs.check_input("qual a SENHA do admin?")
    assert r.blocked and r.response == "Não posso." and r.rule == "r1"
    assert not gs.check_input("olá").blocked


def test_output_mask_regex(load):
    load({"scope": "output", "action": "mask", "match_type": "regex", "pattern": r"\d{3}\.\d{3}\.\d{3}-\d{2}"})
    text, hit = gs.apply_output("CPF 123.456.789-00 ok")
    assert text == "CPF *** ok" and hit == ["r1"]


def test_output_replace_stops(load):
    load({"scope": "output", "action": "replace", "pattern": "proibido", "response": "Sem resposta.", "priority": 1},
         {"scope": "output", "action": "mask", "pattern": "x", "priority": 2})
    assert gs.apply_output("isto é proibido x") == ("Sem resposta.", ["r1"])


def test_priority_order(load):
    load({"scope": "input", "action": "block", "pattern": "oi", "response": "B", "priority": 50},
         {"scope": "input", "action": "block", "pattern": "oi", "response": "A", "priority": 10})
    assert gs.check_input("oi").response == "A"


def test_disabled_ignored_and_instruction_block(load):
    load({"scope": "input", "action": "block", "pattern": "oi", "enabled": False},
         {"scope": "prompt", "action": "instruct", "instruction": "Seja breve."})
    assert not gs.check_input("oi").blocked
    assert "Regras de comportamento" in gs.instruction_block() and "- Seja breve." in gs.instruction_block()


def test_validation_rejects():
    ok = {"name": "n", "scope": "input", "action": "block", "match_type": "regex", "pattern": "abc"}
    assert gs.validate(ok)["pattern"] == "abc"
    for patch in (
        {"pattern": "(abc"},            # regex inválida
        {"pattern": "(a+)+$"},          # ReDoS
        {"pattern": "x" * 501},         # tamanho
        {"pattern": "a*"},              # casa vazio
        {"action": "mask"},             # mask só em output
        {"action": "instruct"},         # instruct só em prompt
        {"scope": "prompt"},            # prompt exige instruct + instrução
        {"scope": "nada"},
    ):
        with pytest.raises(gs.GuardrailError):
            gs.validate({**ok, **patch})


def test_prompt_scope_valid():
    d = gs.validate({"name": "n", "scope": "prompt", "action": "instruct", "instruction": "x"})
    assert d["pattern"] is None and d["instruction"] == "x"


@arun
async def test_create_reloads_cache(monkeypatch):
    store = []

    async def ins(d):
        store.append({**d, "id": 1, "created_at": None})
        return store[-1]

    async def lst():
        return list(store)

    monkeypatch.setattr(gs, "_db_insert", ins)
    monkeypatch.setattr(gs, "_db_list", lst)
    gs._rules = []
    await gs.create_rule({"name": "n", "scope": "input", "action": "block", "match_type": "keyword", "pattern": "abc"})
    assert gs.check_input("xxabcxx").blocked
    gs._rules = []


def test_test_endpoint(load):
    load({"scope": "output", "action": "mask", "pattern": "segredo"})
    res = gs.test("meu segredo")
    assert res["output"]["text"] == "meu ***" and res["input"]["blocked"] is False
