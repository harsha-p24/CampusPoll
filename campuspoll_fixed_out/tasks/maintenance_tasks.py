"""Scheduled maintenance tasks run by Celery Beat."""
from celery_app import celery
import logging

logger = logging.getLogger(__name__)


@celery.task
def purge_old_analytics(days=90):
    """
    Delete analytics events older than `days` days.
    Prevents analytics_events table from growing unboundedly.
    Called by Celery Beat daily.
    """
    from app import db
    from models import AnalyticsEvent
    from datetime import timedelta
    from utils.time_utils import now_ist

    cutoff = now_ist() - timedelta(days=days)
    try:
        deleted = AnalyticsEvent.query.filter(
            AnalyticsEvent.timestamp < cutoff
        ).delete(synchronize_session=False)
        db.session.commit()
        logger.info(f"Purged {deleted} analytics events older than {days} days")
        return deleted
    except Exception as exc:
        db.session.rollback()
        logger.error(f"Analytics purge failed: {exc}")
        raise


@celery.task
def purge_old_login_attempts(days=7):
    """Delete login attempt logs older than 7 days."""
    from app import db
    from models import LoginAttempt
    from datetime import timedelta
    from utils.time_utils import now_ist

    cutoff = now_ist() - timedelta(days=days)
    try:
        deleted = LoginAttempt.query.filter(
            LoginAttempt.attempted_at < cutoff
        ).delete(synchronize_session=False)
        db.session.commit()
        logger.info(f"Purged {deleted} old login attempts")
        return deleted
    except Exception as exc:
        db.session.rollback()
        logger.error(f"Login attempt purge failed: {exc}")
        raise


@celery.task
def celery_heartbeat():
    """
    Heartbeat task — proves Celery worker is alive.
    Called every 5 minutes by Beat; result stored in Redis.
    Health endpoint checks last heartbeat time.
    """
    from datetime import datetime, timezone
    import os

    ts = datetime.now(timezone.utc).isoformat()
    try:
        broker = os.getenv('CELERY_BROKER_URL', '')
        if 'redis' in broker:
            import redis as _redis
            parts = broker.replace('redis://', '').split('/')
            host_port = parts[0].split(':')
            host = host_port[0] or 'localhost'
            port = int(host_port[1]) if len(host_port) > 1 else 6379
            db_num = int(parts[1]) if len(parts) > 1 else 0
            r = _redis.Redis(host=host, port=port, db=db_num, socket_connect_timeout=2)
            r.setex('campuspoll:celery_heartbeat', 360, ts)  # TTL 6 min
    except Exception as exc:
        logger.warning(f"Heartbeat Redis write failed: {exc}")
    logger.info(f"Celery heartbeat: {ts}")
    return ts
