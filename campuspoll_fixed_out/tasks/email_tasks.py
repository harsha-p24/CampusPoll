"""Async email tasks — always called via .delay() or .apply_async()."""
from celery_app import celery
import logging

logger = logging.getLogger(__name__)


def _send(to, subject, html):
    from flask_mail import Message
    from app import mail
    import traceback
    try:
        msg = Message(subject=subject, recipients=[to], html=html)
        mail.send(msg)
        logger.info(f"Email sent to {to}: {subject}")
        return True
    except Exception:
        logger.error(f"Email failed to {to}: {traceback.format_exc()}")
        return False


@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def send_verification_email(self, user_id):
    from app import db
    from models import User
    from flask import url_for
    user = db.session.get(User, user_id)
    if not user:
        return
    link = url_for('auth.verify_email', token=user.verify_token, _external=True)
    html = f"""
    <h2>Welcome to CampusPoll!</h2>
    <p>Hi {user.name}, please verify your email to activate your account.</p>
    <p><a href="{link}" style="background:#1a1a1a;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px;">Verify Email</a></p>
    <p>— CampusPoll Team</p>
    """
    try:
        _send(user.email, "Verify your CampusPoll account", html)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def send_password_reset_email(self, user_id, reset_link):
    from app import db
    from models import User
    user = db.session.get(User, user_id)
    if not user:
        return
    html = f"""
    <h2>Password Reset</h2>
    <p>Hi {user.name}, click below to reset your password (valid 1 hour).</p>
    <p><a href="{reset_link}" style="background:#1a1a1a;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px;">Reset Password</a></p>
    <p>— CampusPoll Team</p>
    """
    try:
        _send(user.email, "Reset your CampusPoll password", html)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def send_nomination_approved_email(self, user_id, election_id):
    from app import db
    from models import User, Election
    user     = db.session.get(User, user_id)
    election = db.session.get(Election, election_id)
    if not user or not election:
        return
    html = f"""
    <h2>🎉 Nomination Approved!</h2>
    <p>Hi {user.name}, your nomination for <strong>{election.position}</strong>
       in <strong>{election.title}</strong> has been approved!</p>
    <p>Voting opens on <strong>{election.voting_start.strftime('%d %b %Y %H:%M')}</strong>.</p>
    <p>— CampusPoll Team</p>
    """
    try:
        _send(user.email, f"Nomination Approved — {election.title}", html)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def send_nomination_rejected_email(self, user_id, election_id):
    from app import db
    from models import User, Election
    user     = db.session.get(User, user_id)
    election = db.session.get(Election, election_id)
    if not user or not election:
        return
    html = f"""
    <h2>Nomination Update</h2>
    <p>Hi {user.name}, your nomination for <strong>{election.position}</strong>
       in <strong>{election.title}</strong> was not approved. Contact admin for details.</p>
    <p>— CampusPoll Team</p>
    """
    try:
        _send(user.email, f"Nomination Update — {election.title}", html)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def send_voting_open_email(self, user_id, election_id):
    from app import db
    from models import User, Election
    user     = db.session.get(User, user_id)
    election = db.session.get(Election, election_id)
    if not user or not election:
        return
    html = f"""
    <h2>🗳️ Voting is Now Open!</h2>
    <p>Hi {user.name}, voting for <strong>{election.title}</strong> ({election.position}) is open!</p>
    <p>Closes: <strong>{election.voting_end.strftime('%d %b %Y %H:%M')}</strong>.</p>
    <p>— CampusPoll Team</p>
    """
    try:
        _send(user.email, f"Vote Now — {election.title}", html)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def send_results_published_email(self, user_id, election_id, winner_name):
    from app import db
    from models import User, Election
    user     = db.session.get(User, user_id)
    election = db.session.get(Election, election_id)
    if not user or not election:
        return
    html = f"""
    <h2>📊 Results Published!</h2>
    <p>Hi {user.name}, results for <strong>{election.title}</strong> are now available.</p>
    <p>Winner: <strong>{winner_name}</strong></p>
    <p>— CampusPoll Team</p>
    """
    try:
        _send(user.email, f"Results Published — {election.title}", html)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery.task(bind=True, max_retries=3, default_retry_delay=60)
def send_vote_confirmation_email(self, user_id, election_id, candidate_id):
    from app import db
    from models import User, Election, Candidate
    user      = db.session.get(User, user_id)
    election  = db.session.get(Election, election_id)
    candidate = db.session.get(Candidate, candidate_id)
    if not user or not election or not candidate:
        return
    html = f"""
    <h2>✅ Vote Confirmed</h2>
    <p>Hi {user.name}, your vote has been recorded.</p>
    <p><strong>Election:</strong> {election.title}</p>
    <p><strong>Position:</strong> {election.position}</p>
    <p><strong>Your vote:</strong> {candidate.user.name}</p>
    <p>Results will be published after the voting period ends.</p>
    <p>— CampusPoll Team</p>
    """
    try:
        _send(user.email, f"Vote Confirmed — {election.title}", html)
    except Exception as exc:
        raise self.retry(exc=exc)


@celery.task(bind=True, max_retries=2, default_retry_delay=120)
def send_bulk_voting_open(self, election_id):
    from app import db
    from models import User, Election
    election = db.session.get(Election, election_id)
    if not election:
        return
    voters = User.query.filter(
        User.role.in_(['voter', 'candidate']),
        User.is_active == True,
        User.is_verified == True,
    ).all()
    for v in voters:
        try:
            send_voting_open_email.delay(v.id, election_id)
        except Exception:
            pass
    return f"Queued {len(voters)} emails"


@celery.task(bind=True, max_retries=2, default_retry_delay=120)
def send_bulk_results(self, election_id, winner_name):
    from models import User
    voters = User.query.filter(
        User.role.in_(['voter', 'candidate']),
        User.is_active == True,
        User.is_verified == True,
    ).all()
    for v in voters:
        try:
            send_results_published_email.delay(v.id, election_id, winner_name)
        except Exception:
            pass


@celery.task(bind=True, max_retries=2)
def publish_results_task(self, election_id):
    from app import db
    from models import Election, Candidate, User, Vote
    from services.audit_service import notify_user
    try:
        election = db.session.get(Election, election_id)
        if not election:
            return
        election.results_published = True
        election.status = 'completed'
        db.session.commit()
        # Use real-time count from Vote table (vote_count is a property, not a column)
        from sqlalchemy import func
        rows = (
            db.session.query(Candidate, func.count(Vote.id).label('cnt'))
            .outerjoin(Vote, Vote.candidate_id == Candidate.id)
            .filter(Candidate.election_id == election_id)
            .group_by(Candidate.id)
            .order_by(func.count(Vote.id).desc())
            .all()
        )
        candidates = [c for c, cnt in rows]
        winner_name = candidates[0].user.name if candidates else 'N/A'
        voters = User.query.filter(
            User.role.in_(['voter', 'candidate']),
            User.is_active == True,
            User.is_verified == True,
        ).all()
        for v in voters:
            notify_user(v.id, f'Results — {election.title}',
                        f'Winner: {winner_name}. View results now!', 'info')
        from services.election_service import emit_realtime
        emit_realtime('results_announced', {'election_id': election_id}, room=f'election_{election_id}')
        send_bulk_results.delay(election_id, winner_name)
        return winner_name
    except Exception as exc:
        db.session.rollback()
        raise self.retry(exc=exc)
