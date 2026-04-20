"""Background scheduler for periodic jobs."""

import atexit
import logging

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from app.alerts import check_all_timeouts, cleanup_old_history
from app.database import get_config

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def init_scheduler(app):
    """Initialize and start the background scheduler.

    Args:
        app: Flask application instance
    """
    with app.app_context():
        check_interval = int(get_config('check_interval_minutes', '1440'))

    def run_check_timeouts():
        with app.app_context():
            check_all_timeouts()

    def run_cleanup():
        with app.app_context():
            cleanup_old_history()

    scheduler.add_job(
        run_check_timeouts,
        trigger=IntervalTrigger(minutes=check_interval),
        id='check_timeouts',
        name='Check tool timeouts and send alerts',
        replace_existing=True,
    )

    scheduler.add_job(
        run_cleanup,
        trigger=CronTrigger(hour=2, minute=0),
        id='cleanup_history',
        name='Clean up old history entries',
        replace_existing=True,
    )

    if not scheduler.running:
        scheduler.start()
        logger.info("Background scheduler started")

    atexit.register(lambda: scheduler.shutdown() if scheduler.running else None)


def get_jobs():
    """Get list of scheduled jobs.

    Returns:
        List of job dicts
    """
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            'id': job.id,
            'name': job.name,
            'next_run': job.next_run_time.isoformat() if job.next_run_time else None,
        })
    return jobs
