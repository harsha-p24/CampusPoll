"""Centralised audit and analytics logging."""
from flask import request
from flask_login import current_user
from app import db
from datetime import datetime, timezone
import logging

logger = logging.getLogger(__name__)


def _uid():
    try:
        if current_user and not current_user.is_anonymous:
            return current_user.id
        return None
    except Exception:
        return None


def log_event(event_type, page=None, details=None, user_id=None, load_time_ms=None):
    from models import AnalyticsEvent
    try:
        db.session.add(AnalyticsEvent(
            user_id=user_id or _uid(),
            event_type=event_type,
            page=page,
            details=str(details)[:500] if details else None,
            load_time_ms=load_time_ms,
            ip_address=request.remote_addr,
            user_agent=request.headers.get('User-Agent', '')[:300],
        ))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning(f"log_event failed: {exc}")


def log_audit(action, details=None, user_id=None):
    from models import AuditLog
    try:
        db.session.add(AuditLog(
            user_id=user_id or _uid(),
            action=action,
            details=str(details)[:500] if details else None,
            ip_address=request.remote_addr,
        ))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.warning(f"log_audit failed: {exc}")


def notify_user(user_id, title, message, ntype='info'):
    from models import Notification
    try:
        db.session.add(Notification(
            user_id=user_id, title=title[:200],
            message=message[:1000], type=ntype,
        ))
        db.session.commit()
    except Exception as exc:
        db.session.rollback()
        logger.debug(f"notify_user skipped: {exc}")
