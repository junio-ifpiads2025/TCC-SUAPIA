"""
Registry de providers de mensageria.

Responsável por:
- instanciar os providers habilitados em MESSAGING_PROVIDERS (lazy, singleton);
- namespacing do chat_id, para que vários providers coexistam sem colisão;
- resolver, a partir de um chat_id, qual provider deve enviar a resposta.

Namespacing: o provider padrão (waha) mantém o chat_id nativo ("5586...@c.us"),
preservando sessões, histórico e filas já existentes. Os demais usam
"<provider>:<id_nativo>" (ex: "telegram:123456").
"""

from importlib import import_module

from config import MESSAGING_PROVIDERS
from services.providers.base import IncomingMessage, InvalidPayload, MessagingProvider

__all__ = [
    "IncomingMessage", "InvalidPayload", "MessagingProvider",
    "DEFAULT_PROVIDER", "get_provider", "qualify", "resolve", "register", "start_all",
]

DEFAULT_PROVIDER = "waha"

# nome -> "modulo:Classe" (import lazy: só carrega dependências dos providers usados)
_BUILTIN = {
    "waha": "services.providers.waha:WahaProvider",
    "telegram": "services.providers.telegram:TelegramProvider",
}

_instances: dict[str, MessagingProvider] = {}


def register(provider: MessagingProvider) -> None:
    """Registra uma instância diretamente (útil em testes e providers customizados)."""
    _instances[provider.name] = provider


def get_provider(name: str) -> MessagingProvider:
    """Retorna o provider habilitado `name`. Levanta KeyError se desconhecido/desabilitado."""
    if name not in _instances:
        if name not in MESSAGING_PROVIDERS or name not in _BUILTIN:
            raise KeyError(name)
        module_path, cls_name = _BUILTIN[name].split(":")
        _instances[name] = getattr(import_module(module_path), cls_name)()
    return _instances[name]


async def start_all() -> None:
    """Executa startup() de cada provider habilitado."""
    for name in MESSAGING_PROVIDERS:
        await get_provider(name).startup()


def qualify(provider_name: str, native_id: str) -> str:
    """chat_id nativo -> chat_id da aplicação."""
    if provider_name == DEFAULT_PROVIDER:
        return native_id
    return f"{provider_name}:{native_id}"


def resolve(chat_id: str) -> tuple[MessagingProvider, str]:
    """chat_id da aplicação -> (provider, chat_id nativo)."""
    prefix, sep, rest = chat_id.partition(":")
    if sep and (prefix in _BUILTIN or prefix in _instances) and prefix != DEFAULT_PROVIDER:
        return get_provider(prefix), rest
    return get_provider(DEFAULT_PROVIDER), chat_id
