"""Celery Beat scheduled tasks — replaces in-process APScheduler."""
from celery_app import celery
from utils.time_utils import now_ist
import logging

logger = logging.getLogger(__name__)

@celery.task
def auto_update_statuses():
    """
    Called by Celery Beat every 60s.
    Runs in ONE place (the beat process), not per Gunicorn worker.
    """
    from app import create_app, db
    from models import Election

    from services.election_service import emit_realtime

    now = now_ist()  # naive IST — matches how admins enter election dates
    changed = 0
    changed_elections = []
    try:
        for e in Election.query.all():
            if e.results_published:
                new = 'completed'
            elif now < e.nomination_start:
                new = 'upcoming'
            elif now <= e.nomination_end:
                new = 'nomination'
            elif now < e.voting_start:
                new = 'upcoming'
            elif now <= e.voting_end:
                new = 'voting'
            else:
                new = 'closed'
            if e.status != new:
                e.status = new
                changed += 1
                changed_elections.append((e.id, new))
        if changed:
            db.session.commit()
            logger.info(f"Updated {changed} election statuses")
            # This task runs in a separate Celery Beat/worker process, so we
            # bridge the event to browser clients via the Redis message
            # queue instead of touching the Flask process's socketio object.
            for election_id, new_status in changed_elections:
                emit_realtime('election_status', {'election_id': election_id, 'status': new_status},
                              room=f'election_{election_id}')
    except Exception as exc:
        db.session.rollback()
        logger.error(f"Status update failed: {exc}")
    return f"checked, {changed} updated"
