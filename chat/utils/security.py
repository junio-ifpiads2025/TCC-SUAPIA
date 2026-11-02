"""
Utilitários de segurança para logging.

Garante que dados sensíveis (tokens, senhas, CPFs) nunca apareçam
em logs de forma legível, substituindo os valores por '***'.
"""

# Campos cujos valores devem ser ocultados nos logs (RN13)
_SENSITIVE_KEYS = {"token", "senha", "password", "cpf", "access", "refresh", "authorization"}


def sanitize_log(data: dict) -> dict:
    """
    Retorna uma cópia do dicionário com valores sensíveis mascarados.
    A comparação é case-insensitive para cobrir variações como 'Token' ou 'TOKEN'.
    """
    return {
        k: "***" if k.lower() in _SENSITIVE_KEYS else v
        for k, v in data.items()
    }


def mask_chat_id(chat_id: str | None) -> str:
    """
    LGPD: identificador do usuário para telas e exportações, só com os 4 últimos
    dígitos (`•••1234`). Ids curtos não revelam nada; `admin:<usuário>` passa intacto.
    """
    chat_id = str(chat_id or "")
    if not chat_id:
        return ""
    if chat_id.startswith("admin:"):
        return chat_id
    digits = "".join(c for c in chat_id.split("@")[0] if c.isdigit())
    return "•••" + (digits[-4:] if len(digits) > 4 else "")
