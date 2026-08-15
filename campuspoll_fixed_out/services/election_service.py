"""Election business logic."""
from app import db
from utils.time_utils import now_ist as _now


def get_election_status(election):
    now = _now()
    if election.results_published:      return 'completed'
    if now < election.nomination_start: return 'upcoming'
    if now <= election.nomination_end:  return 'nomination'
    if now < election.voting_start:     return 'upcoming'
    if now <= election.voting_end:      return 'voting'
    return 'closed'


def emit_realtime(event, data, room, app_socketio=None):
    """
    Best-effort Socket.IO push to `room`.

    - Called from within the running Flask process (a request, or the
      in-process APScheduler dev fallback): pass `app_socketio` (the shared
      `socketio` instance) and the event is delivered directly.
    - Called from a separate process (a Celery worker/beat task): pass
      nothing, and this bridges the event over the same Redis broker Celery
      already uses (Flask-SocketIO's `message_queue` mechanism), reaching
      browsers connected to the web process.

    This is a UX nicety (instant updates) layered on top of correctness
    that already holds without it — every page also re-derives the true
    status from `live_status`/`can_vote`/`results_published` on each load,
    and there's a client-side polling fallback — so failures here are
    swallowed rather than raised.
    """
    if app_socketio is not None:
        try:
            app_socketio.emit(event, data, room=room)
        except Exception:
            pass
        return
    import os
    mq = os.getenv('CELERY_BROKER_URL')
    if not mq:
        return
    try:
        from flask_socketio import SocketIO
        SocketIO(message_queue=mq).emit(event, data, room=room)
    except Exception:
        pass


def auto_update_statuses(app):
    """Dev fallback called by APScheduler (in-process, so it can emit
    Socket.IO events directly on the app's live socketio instance)."""
    with app.app_context():
        from models import Election
        from app import socketio
        changed_elections = []
        for e in Election.query.all():
            new = get_election_status(e)
            if e.status != new:
                e.status = new
                changed_elections.append((e.id, new))
        if changed_elections:
            db.session.commit()
            for election_id, new_status in changed_elections:
                emit_realtime('election_status', {'election_id': election_id, 'status': new_status},
                              room=f'election_{election_id}', app_socketio=socketio)


def can_nominate(election):
    now = _now()
    return election.nomination_start <= now <= election.nomination_end


def can_vote(election):
    now = _now()
    return election.voting_start <= now <= election.voting_end


def cast_vote(voter, election, candidate):
    from models import Vote
    if not can_vote(election):
        return False, 'Voting is not active for this election.'
    if Vote.query.filter_by(voter_id=voter.id, election_id=election.id).first():
        return False, 'You have already voted in this election.'
    if candidate.election_id != election.id:
        return False, 'Invalid candidate selection.'
    if candidate.user_id == voter.id:
        return False, 'You cannot vote for yourself.'
    try:
        vote = Vote(voter_id=voter.id, election_id=election.id, candidate_id=candidate.id)
        db.session.add(vote)
        db.session.commit()
        return True, None
    except Exception:
        db.session.rollback()
        return False, 'Vote could not be recorded. Please try again.'


def get_results(election):
    from models import Candidate, Vote
    from sqlalchemy import func
    # Real-time count from Vote table — no denormalized counter
    rows = (
        db.session.query(Candidate, func.count(Vote.id).label('cnt'))
        .outerjoin(Vote, Vote.candidate_id == Candidate.id)
        .filter(Candidate.election_id == election.id)
        .group_by(Candidate.id)
        .order_by(func.count(Vote.id).desc())
        .all()
    )
    candidates = []
    for cand, cnt in rows:
        cand._live_vote_count = cnt
        candidates.append(cand)
    total = sum(c._live_vote_count for c in candidates)
    return candidates, total
