"""
Utilitários de segurança para logging.

Garante que dados sensíveis (tokens, senhas, CPFs) nunca apareçam
em logs de forma legível, substituindo os valores por '***'.
"""

# Campos cujos valores devem ser ocultados nos logs
_SENSITIVE_KEYS = {"token", "senha", "password", "cpf", "access", "refresh"}


def sanitize_log(data: dict) -> dict:
    """
    Retorna uma cópia do dicionário com valores sensíveis mascarados.
    A comparação é case-insensitive para cobrir variações como 'Token' ou 'TOKEN'.
    """
    return {
        k: "***" if k.lower() in _SENSITIVE_KEYS else v
        for k, v in data.items()
    }
