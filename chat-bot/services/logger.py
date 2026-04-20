from datetime import datetime

# ANSI codes
R      = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"
CYAN   = "\033[96m"
GREEN  = "\033[92m"
YELLOW = "\033[93m"
RED    = "\033[91m"
BLUE   = "\033[94m"
MAGENTA = "\033[95m"
WHITE  = "\033[97m"


def _ts() -> str:
    return datetime.now().strftime("%H:%M:%S")


def _tag(label: str, color: str) -> str:
    return f"{DIM}[{_ts()}]{R} {BOLD}{color}[{label}]{R}"


# ── Public helpers ──────────────────────────────────────────────────────────

def info(tag: str, msg: str) -> None:
    print(f"{_tag(tag, WHITE)} {msg}")


def success(tag: str, msg: str) -> None:
    print(f"{_tag(tag, GREEN)} {msg}")


def warn(tag: str, msg: str) -> None:
    print(f"{_tag(tag, YELLOW)} {msg}")


def error(tag: str, msg: str) -> None:
    print(f"{_tag(tag, RED)} {msg}")


def phase(num: int, name: str) -> None:
    print(f"\n{BOLD}{MAGENTA}  ▶ Fase {num} — {name}{R}")


def incoming(chat_id: str, body: str) -> None:
    width = 62
    bar = f"{BOLD}{CYAN}{'━' * width}{R}"
    print(f"\n{bar}")
    print(f"{BOLD}{CYAN}  📨  NOVA MENSAGEM{R}")
    print(f"  {BOLD}De:{R}       {CYAN}{chat_id}{R}")
    print(f"  {BOLD}Texto:{R}    {WHITE}{body}{R}")
    print(f"{DIM}{'─' * width}{R}")


def response_log(text: str, max_len: int = 300) -> None:
    preview = text[:max_len] + ("…" if len(text) > max_len else "")
    bar = f"{BOLD}{GREEN}{'─' * 62}{R}"
    print(f"\n{bar}")
    print(f"{BOLD}{GREEN}  ✅  RESPOSTA GERADA{R}")
    for line in preview.splitlines():
        print(f"  {line}")
    print(f"{bar}\n")


def image_log(chat_id: str, url: str) -> None:
    print(f"{_tag('IMAGEM', BLUE)} → {CYAN}{chat_id}{R}  {DIM}{url}{R}")
