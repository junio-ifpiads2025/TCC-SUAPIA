_SENSITIVE_KEYS = {"token", "senha", "password", "cpf", "access", "refresh"}


def sanitize_log(data: dict) -> dict:
    return {
        k: "***" if k.lower() in _SENSITIVE_KEYS else v
        for k, v in data.items()
    }
