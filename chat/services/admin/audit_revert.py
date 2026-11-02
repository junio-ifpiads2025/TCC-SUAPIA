"""
Reversão de uma entrada da auditoria.

Cada entidade tem uma função que reaplica o estado `before` usando o próprio
serviço da entidade, então a reversão passa pelas mesmas validações e gera uma
nova entrada de auditoria. Regras gerais (CRUD):
- criação (before vazio)  → remove o que foi criado;
- remoção (after vazio)   → recria a partir do before (documento e guardrail ganham novo id);
- alteração               → reaplica o before.
O prompt é exceção: reverter reativa a versão que estava ativa antes.
"""

from services.admin import admin_user_service
from services.shared import (acl_service, audit_service, guardrail_service, knowledge_service,
                             prompt_service, qa_case_service, skill_service)


class RevertError(ValueError):
    """Entrada inexistente, já revertida ou sem estado anterior aplicável."""


async def _prompt(e: dict, admin: str) -> None:
    if not e["before"]:
        raise RevertError("Não há versão anterior do prompt para reativar.")
    await prompt_service.activate(int(e["before"]["id"]))


async def _skill(e: dict, admin: str) -> None:
    if e["before"] is None:
        await skill_service.delete_skill(e["entity_id"])
    elif e["after"] is None:
        await skill_service.create_skill(e["before"]["slug"], e["before"])
    else:
        await skill_service.update_skill(e["entity_id"], e["before"])


async def _guardrail(e: dict, admin: str) -> None:
    if e["before"] is None:
        await guardrail_service.delete_rule(int(e["entity_id"]))
    elif e["after"] is None:
        await guardrail_service.create_rule(e["before"])
    else:
        await guardrail_service.update_rule(int(e["entity_id"]), e["before"])


async def _access_rule(e: dict, admin: str) -> None:
    if e["before"] is None:
        await acl_service.remove_rule(e["entity_id"])
    else:
        b = e["before"]
        await acl_service.add_rule(b["chat_id"], b["kind"], b.get("reason"), created_by=admin)


async def _setting(e: dict, admin: str) -> None:
    if e["entity_id"] == acl_service.OPEN_KEY:
        await acl_service.set_open(bool(e["before"]["value"]))
    elif e["entity_id"] == acl_service.DAILY_LIMIT_KEY:
        await acl_service.set_default_limit(e["before"]["value"])
    else:
        raise RevertError("Configuração desconhecida.")


async def _daily_limit(e: dict, admin: str) -> None:
    await acl_service.set_user_limit(e["entity_id"], e["before"]["daily_limit"], created_by=admin)


async def _knowledge(e: dict, admin: str) -> None:
    if e["before"] is None:
        await knowledge_service.delete_document(e["entity_id"])
    elif e["after"] is None:
        await knowledge_service.create_document(e["before"]["title"], e["before"]["content"])
    else:
        await knowledge_service.update_document(e["entity_id"], e["before"]["title"], e["before"]["content"])


async def _admin_user(e: dict, admin: str) -> None:
    if e["entity_id"] == admin:
        raise RevertError("Você não pode alterar o próprio acesso.")
    if e["before"] is None:
        await admin_user_service.remove_admin(e["entity_id"])
    else:
        await admin_user_service.add_admin(e["entity_id"], added_by=admin)


async def _qa_case(e: dict, admin: str) -> None:
    await qa_case_service.update_case(int(e["entity_id"]), e["before"]["status"], e["before"]["note"])


REVERTERS = {
    "prompt": _prompt,
    "skill": _skill,
    "guardrail": _guardrail,
    "access_rule": _access_rule,
    "setting": _setting,
    "daily_limit": _daily_limit,
    "knowledge": _knowledge,
    "admin_user": _admin_user,
    "qa_case": _qa_case,
}


async def revert(entry_id: int, admin: str) -> None:
    """Desfaz a alteração `entry_id`. Levanta RevertError (ou o erro do serviço da entidade)."""
    entry = await audit_service.get_entry(entry_id)
    if entry is None:
        raise RevertError("Entrada de auditoria não encontrada.")
    if entry["reverted_by"]:
        raise RevertError("Essa alteração já foi revertida.")
    fn = REVERTERS.get(entry["entity"])
    if fn is None:
        raise RevertError("Essa alteração não pode ser revertida.")
    await fn(entry, admin)
    await audit_service.mark_reverted(entry_id, admin)
