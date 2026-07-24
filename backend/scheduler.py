"""Runs Daily Notes card generation once a day at config.DAILY_NOTES_CARD_TIME
(server local time, 24h "HH:MM"). A single BackgroundScheduler thread inside
this same process -- fine for the single-instance personal use this app is
built for; running multiple instances of the app would double-fire it."""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import config

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler()

# How often to retry pushing any Daily Notes cards that are still waiting on
# Anki (e.g. Anki desktop was closed at generation time). Frequent enough
# that reopening Anki gets your cards synced within minutes, cheap enough
# (a no-op when nothing is pending) to just leave running.
_PUSH_RETRY_INTERVAL_MINUTES = 15


def _run_daily_notes_job() -> None:
    from .services.generator import process_daily_notes

    try:
        process_daily_notes()
    except Exception:  # noqa: BLE001 - a scheduler job must never raise
        logger.exception("Daily notes card generation failed")


def _run_daily_notes_push_retry_job() -> None:
    from .services.generator import push_pending_daily_notes_cards

    try:
        push_pending_daily_notes_cards()
    except Exception:  # noqa: BLE001 - a scheduler job must never raise
        logger.exception("Daily notes push retry failed")


def _parse_time(value: str):
    try:
        hour_str, minute_str = value.split(":")
        return int(hour_str), int(minute_str)
    except (ValueError, AttributeError):
        logger.warning("Invalid DAILY_NOTES_CARD_TIME=%r, defaulting to 23:59", value)
        return 23, 59


def start() -> None:
    hour, minute = _parse_time(config.DAILY_NOTES_CARD_TIME)
    _scheduler.add_job(
        _run_daily_notes_job,
        CronTrigger(hour=hour, minute=minute),
        id="daily_notes_card_job",
        replace_existing=True,
        # A laptop that's asleep at 23:59 means the scheduler never got a
        # chance to fire then -- without a generous grace window here,
        # APScheduler just skips straight to tomorrow's occurrence instead
        # of catching up once the machine wakes back up.
        misfire_grace_time=12 * 3600,
    )
    _scheduler.add_job(
        _run_daily_notes_push_retry_job,
        IntervalTrigger(minutes=_PUSH_RETRY_INTERVAL_MINUTES),
        id="daily_notes_push_retry_job",
        replace_existing=True,
    )
    if not _scheduler.running:
        _scheduler.start()


def stop() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
