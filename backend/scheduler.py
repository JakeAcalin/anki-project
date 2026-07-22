"""Runs Daily Notes card generation once a day at config.DAILY_NOTES_CARD_TIME
(server local time, 24h "HH:MM"). A single BackgroundScheduler thread inside
this same process -- fine for the single-instance personal use this app is
built for; running multiple instances of the app would double-fire it."""
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

from . import config

logger = logging.getLogger(__name__)

_scheduler = BackgroundScheduler()


def _run_daily_notes_job() -> None:
    from .services.generator import process_daily_notes

    try:
        process_daily_notes()
    except Exception:  # noqa: BLE001 - a scheduler job must never raise
        logger.exception("Daily notes card generation failed")


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
    )
    if not _scheduler.running:
        _scheduler.start()


def stop() -> None:
    if _scheduler.running:
        _scheduler.shutdown(wait=False)
