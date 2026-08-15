"""WebSocket handlers for real-time vote updates.

Two distinct rooms per election, deliberately kept separate:

  election_{id}        Public. Anyone (including voters mid-election) may
                        join. Only carries 'election_status' and
                        'results_announced' events — i.e. "something
                        changed, you may want to reload" — never vote
                        counts. Safe for anyone to observe.

  election_{id}_live    Restricted. Carries 'vote_update' events with the
                        real per-candidate vote breakdown. Only admins may
                        join while voting is in progress; everyone may join
                        once results have been officially announced (at
                        that point the numbers are public anyway). This is
                        what enforces "live results are visible only to
                        Admin until results are announced" at the
                        real-time layer, not just on HTTP routes.
"""
from flask_socketio import join_room, leave_room
from flask_login import current_user
import logging

logger = logging.getLogger(__name__)


def init_socketio(socketio, app):
    """Register all Socket.IO event handlers."""

    @socketio.on('connect')
    def on_connect():
        logger.debug(f"WS connect: {current_user}")

    @socketio.on('disconnect')
    def on_disconnect():
        logger.debug("WS disconnect")

    @socketio.on('join_election')
    def on_join(data):
        """Public room — status/results-announced notifications only."""
        election_id = data.get('election_id')
        if election_id:
            join_room(f'election_{election_id}')

    @socketio.on('leave_election')
    def on_leave(data):
        election_id = data.get('election_id')
        if election_id:
            leave_room(f'election_{election_id}')

    @socketio.on('join_live_results')
    def on_join_live(data):
        """Restricted room — real-time per-candidate vote counts.
        Only admins, or anyone once results are officially announced."""
        election_id = data.get('election_id')
        if not election_id or not current_user.is_authenticated:
            return
        if current_user.role == 'admin':
            join_room(f'election_{election_id}_live')
            return
        from models import Election
        election = Election.query.get(election_id)
        if election and election.results_published:
            join_room(f'election_{election_id}_live')

    @socketio.on('leave_live_results')
    def on_leave_live(data):
        election_id = data.get('election_id')
        if election_id:
            leave_room(f'election_{election_id}_live')


def broadcast_vote_update(socketio, election_id: int):
    """
    Push live vote counts to clients watching this election's restricted
    live-results room. Called after every successful vote. Never broadcasts
    to the public `election_{id}` room — voters/candidates must not receive
    live per-candidate counts before results are announced.
    """
    from app import db
    from models import Candidate, Vote
    from sqlalchemy import func

    try:
        rows = (
            db.session.query(Candidate, func.count(Vote.id).label('cnt'))
            .outerjoin(Vote, Vote.candidate_id == Candidate.id)
            .filter(Candidate.election_id == election_id)
            .group_by(Candidate.id)
            .all()
        )
        payload = {
            'election_id': election_id,
            'counts': {
                str(c.id): {'name': c.user.name, 'votes': cnt}
                for c, cnt in rows
            },
            'total': sum(cnt for _, cnt in rows),
        }
        socketio.emit('vote_update', payload, room=f'election_{election_id}_live')
    except Exception as exc:
        logger.error(f"broadcast_vote_update failed: {exc}")
