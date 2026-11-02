"""
Alertas operacionais por Telegram e e-mail (SMTP).

- Canais: cada um só funciona se configurado (ALERT_TELEGRAM_CHAT_ID com o
  provider telegram habilitado; ALERT_SMTP_HOST + ALERT_SMTP_TO). Sem canal, o
  alerta só vai para o log da aplicação.
- `notify(rule, message)` é a API pública: aplica um silêncio (cooldown) por
  regra no Redis, para a mesma regra não disparar de novo antes de
  ALERT_COOLDOWN_SECONDS.
- `alert_loop` roda no lifespan e verifica a cada ALERT_INTERVAL_SECONDS: fila
  cheia, item travado em atendimento, taxa de falhas, sondas de saúde falhando
  ALERT_PROBE_FAILURES vezes seguidas e usuários recusados por limite diário de
  mensagens ou orçamento de tokens (contadores sem chat_id gravados pela fila).
LGPD: as mensagens só levam contagens e nomes de componentes, nunca chat_id,
matrícula ou conteúdo de conversa.
"""

import asyncio
import smtplib
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from sqlalchemy import func, select

import config
from models.database import AccessLog, AsyncSessionLocal
from services.admin import health_service
from services.chat import messaging_client, queue_service
from services.shared import logger, session_service

ERROR_WINDOW_MINUTES = 15
ERROR_MIN_SAMPLES = 5  # abaixo disso a taxa não é significativa
_COOLDOWN_KEY = "suap:alert:cooldown:{rule}"

# Falhas seguidas por sonda (estado do processo; zera quando a sonda volta)
_probe_failures: dict[str, int] = {}


# ── Canais ───────────────────────────────────────────────────────────────────

def channels() -> list[str]:
    out = []
    if config.ALERT_TELEGRAM_CHAT_ID:
        out.append("telegram")
    if config.ALERT_SMTP_HOST and config.ALERT_SMTP_TO:
        out.append("email")
    return out


async def _send_telegram(message: str) -> None:
    await messaging_client.enviar_texto_async(f"telegram:{config.ALERT_TELEGRAM_CHAT_ID}", message)


def _send_email_sync(subject: str, message: str) -> None:
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = config.ALERT_SMTP_USER or "suapia@localhost"
    msg["To"] = config.ALERT_SMTP_TO
    msg.set_content(message)
    with smtplib.SMTP(config.ALERT_SMTP_HOST, config.ALERT_SMTP_PORT, timeout=15) as smtp:
        if config.ALERT_SMTP_PORT != 25:
            smtp.starttls()
        if config.ALERT_SMTP_USER:
            smtp.login(config.ALERT_SMTP_USER, config.ALERT_SMTP_PASSWORD)
        smtp.send_message(msg)


async def _send_email(message: str) -> None:
    await asyncio.to_thread(_send_email_sync, f"[{config.AGENT_NAME}] alerta", message)


_SENDERS = {"telegram": _send_telegram, "email": _send_email}


async def _acquire_cooldown(rule: str) -> bool:
    """True se a regra pode alertar agora (e marca o silêncio). Sem Redis, alerta."""
    try:
        return bool(await session_service.get_redis().set(
            _COOLDOWN_KEY.format(rule=rule), "1", nx=True, ex=config.ALERT_COOLDOWN_SECONDS))
    except Exception as e:
        logger.warn("ALERT", f"Redis indisponível para cooldown: {type(e).__name__}")
        return True


# ── API pública ──────────────────────────────────────────────────────────────

async def notify(rule: str, message: str) -> bool:
    """
    Envia `message` por todos os canais configurados, no máximo uma vez a cada
    ALERT_COOLDOWN_SECONDS por `rule`. Retorna True se enviou por algum canal.
    Nunca levanta exceção. A mensagem não pode conter dado pessoal.
    """
    if not await _acquire_cooldown(rule):
        return False
    logger.warn("ALERT", f"[{rule}] {message}")
    text = f"⚠️ {config.AGENT_NAME}: {message}"
    sent = False
    for name in channels():
        try:
            await _SENDERS[name](text)
            sent = True
        except Exception as e:
            logger.error("ALERT", f"Falha no canal {name}: {type(e).__name__}")
    return sent


# ── Regras ───────────────────────────────────────────────────────────────────

async def _db_outcomes(since: datetime) -> tuple[int, int]:
    """(answered, failed) desde `since`."""
    stmt = (select(AccessLog.event, func.count()).where(
        AccessLog.event.in_(("answered", "failed")), AccessLog.created_at >= since)
        .group_by(AccessLog.event))
    async with AsyncSessionLocal() as s:
        counts = dict((await s.execute(stmt)).all())
    return counts.get("answered", 0), counts.get("failed", 0)


async def _check_queue() -> None:
    pending = (await queue_service.stats())["pending"]
    if pending > config.ALERT_QUEUE_MAX_PENDING:
        await notify("queue_pending", f"fila com {pending} mensagens pendentes "
                                      f"(limite {config.ALERT_QUEUE_MAX_PENDING}).")
    age = await queue_service.oldest_processing_seconds()
    if age > config.ALERT_PROCESSING_MAX_SECONDS:
        await notify("queue_stuck", f"mensagem em atendimento há {int(age)} s "
                                    f"(limite {config.ALERT_PROCESSING_MAX_SECONDS} s).")


async def _check_error_rate() -> None:
    since = datetime.now(timezone.utc) - timedelta(minutes=ERROR_WINDOW_MINUTES)
    answered, failed = await _db_outcomes(since)
    total = answered + failed
    if total >= ERROR_MIN_SAMPLES and failed / total > config.ALERT_ERROR_RATE:
        await notify("error_rate", f"{failed} de {total} atendimentos falharam nos últimos "
                                   f"{ERROR_WINDOW_MINUTES} min ({failed / total:.0%}).")


async def _check_health() -> None:
    for r in await health_service.check_all():
        name = r["name"]
        if r["ok"]:
            _probe_failures.pop(name, None)
            continue
        _probe_failures[name] = _probe_failures.get(name, 0) + 1
        if _probe_failures[name] >= config.ALERT_PROBE_FAILURES:
            await notify(f"health:{name}", f"{name} falhou {_probe_failures[name]} verificações "
                                           f"seguidas ({r['detail']}).")


LIMIT_MESSAGES = {
    "token_budget": "orçamento diário de tokens por usuário",
    "daily_messages": "limite diário de mensagens",
}


async def _check_limits() -> None:
    for kind, label in LIMIT_MESSAGES.items():
        n = await session_service.pop_limit_exceeded(kind)
        if n:
            await notify(f"limit:{kind}", f"{n} mensagem(ns) recusada(s) por {label} "
                                          f"desde a última verificação.")


async def run_checks() -> None:
    """Uma rodada de todas as regras; a falha de uma não impede as outras."""
    for check in (_check_queue, _check_error_rate, _check_health, _check_limits):
        try:
            await check()
        except Exception as e:
            logger.warn("ALERT", f"Regra {check.__name__} falhou: {type(e).__name__}")


async def alert_loop() -> None:
    """Task de fundo (lifespan). Erros não encerram o loop."""
    if not channels():
        logger.info("ALERT", "Nenhum canal de alerta configurado: alertas só no log.")
    while True:
        await run_checks()
        await asyncio.sleep(config.ALERT_INTERVAL_SECONDS)
