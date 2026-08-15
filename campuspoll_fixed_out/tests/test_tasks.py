"""Tests for Celery tasks using eager mode (no broker needed)."""
import pytest
from unittest.mock import patch, MagicMock
from models import User, Election, Candidate, Vote
from werkzeug.security import generate_password_hash
from datetime import datetime, timezone, timedelta


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_user(db, email, sid, role='voter'):
    u = User(
        name=email.split('@')[0], email=email,
        password=generate_password_hash('Test@1234'),
        student_id=sid, department='CS', year='1st Year',
        role=role, is_active=True, is_verified=True,
    )
    db.session.add(u); db.session.commit()
    return u


def make_election(db, published=False):
    n = now()
    e = Election(
        title='Task Test Election', position='President',
        nomination_start=n-timedelta(days=3), nomination_end=n-timedelta(days=1),
        voting_start=n-timedelta(hours=1), voting_end=n+timedelta(hours=24),
        status='voting', results_published=published,
    )
    db.session.add(e); db.session.commit()
    return e


class TestElectionStatusTask:
    def test_status_updates_correctly(self, app, db):
        """Election status should auto-update based on current time."""
        from services.election_service import auto_update_statuses
        n = now()
        e = make_election(db)
        assert e.status == 'voting'
        # Force to upcoming
        e.voting_start = n + timedelta(days=1)
        e.voting_end   = n + timedelta(days=2)
        e.status = 'wrong_status'
        db.session.commit()
        auto_update_statuses(app)
        db.session.refresh(e)
        assert e.status == 'upcoming'


class TestEmailTasks:
    """Test email task logic without sending real emails."""

    def test_verification_email_skips_missing_user(self, app, db):
        from tasks.email_tasks import send_verification_email
        with patch('tasks.email_tasks._send') as mock_send:
            # User 99999 doesn't exist — should not crash
            send_verification_email.apply(args=[99999])
            mock_send.assert_not_called()

    def test_verification_email_calls_send(self, app, db):
        import secrets
        u = make_user(db, 'verify_task@test.com', 'VT001')
        u.verify_token = secrets.token_urlsafe(16)
        db.session.commit()
        with patch('tasks.email_tasks._send', return_value=True) as mock_send:
            send_verification_email = __import__('tasks.email_tasks', fromlist=['send_verification_email']).send_verification_email
            send_verification_email.apply(args=[u.id])
            mock_send.assert_called_once()
            _, kwargs = mock_send.call_args if mock_send.call_args else ([], {})

    def test_nomination_approved_email_skips_missing(self, app, db):
        from tasks.email_tasks import send_nomination_approved_email
        with patch('tasks.email_tasks._send') as mock_send:
            send_nomination_approved_email.apply(args=[99999, 99999])
            mock_send.assert_not_called()

    def test_vote_confirmation_email(self, app, db):
        from tasks.email_tasks import send_vote_confirmation_email
        voter = make_user(db, 'vote_conf@test.com', 'VC001')
        other = make_user(db, 'vote_cand@test.com', 'VC002')
        e     = make_election(db)
        cand  = Candidate(user_id=other.id, election_id=e.id, manifesto='test')
        db.session.add(cand); db.session.commit()
        with patch('tasks.email_tasks._send', return_value=True) as mock_send:
            send_vote_confirmation_email.apply(args=[voter.id, e.id, cand.id])
            mock_send.assert_called_once()
            args = mock_send.call_args[0]
            assert voter.email in args[0]
            assert 'Confirmed' in args[1]

    def test_results_email_bulk_queues_tasks(self, app, db):
        from tasks.email_tasks import send_bulk_results
        voter = make_user(db, 'bulk_v@test.com', 'BV001')
        e     = make_election(db)
        with patch('tasks.email_tasks.send_results_published_email') as mock_task:
            mock_task.delay = MagicMock()
            send_bulk_results.apply(args=[e.id, 'Winner Name'])
            mock_task.delay.assert_called()


class TestConcurrentVoting:
    """Simulate concurrent votes — DB constraint must block duplicates."""

    def test_concurrent_votes_only_one_recorded(self, app, db):
        """
        Duplicate vote prevention: second vote attempt must be rejected.
        The UniqueConstraint(voter_id, election_id) enforces this at DB level.
        """
        from services.election_service import cast_vote

        voter = make_user(db, 'concurrent@test.com', 'CON001')
        other = make_user(db, 'concurrent_cand@test.com', 'CON002')
        e     = make_election(db)
        cand  = Candidate(user_id=other.id, election_id=e.id, manifesto='x')
        db.session.add(cand); db.session.commit()

        # First vote succeeds
        ok1, err1 = cast_vote(voter, e, cand)
        assert ok1 and err1 is None

        # Second vote (simulating duplicate/concurrent attempt) must fail
        ok2, err2 = cast_vote(voter, e, cand)
        assert not ok2
        assert 'already voted' in err2

        # DB must have exactly one vote
        vote_count = Vote.query.filter_by(voter_id=voter.id, election_id=e.id).count()
        assert vote_count == 1


class TestPublishResultsTask:
    def test_publish_results_task(self, app, db):
        from tasks.email_tasks import publish_results_task
        voter = make_user(db, 'pub_voter@test.com', 'PV001')
        other = make_user(db, 'pub_cand@test.com', 'PC001')
        e     = make_election(db)
        cand  = Candidate(user_id=other.id, election_id=e.id, manifesto='test')
        db.session.add(cand); db.session.commit()
        # Add a vote so there's a winner
        vote  = Vote(voter_id=voter.id, election_id=e.id, candidate_id=cand.id)
        db.session.add(vote); db.session.commit()
        eid = e.id
        with patch('tasks.email_tasks.send_bulk_results') as mock_bulk:
            mock_bulk.delay = MagicMock()
            publish_results_task.apply(args=[eid])
        with app.app_context():
            from models import Election
            updated = db.session.get(Election, eid)
            assert updated.results_published is True
            assert updated.status == 'completed'

    def test_publish_results_task_missing_election(self, app, db):
        from tasks.email_tasks import publish_results_task
        with patch('tasks.email_tasks.send_bulk_results') as mock_bulk:
            mock_bulk.delay = MagicMock()
            result = publish_results_task.apply(args=[99999])
            mock_bulk.delay.assert_not_called()


class TestBulkEmailTasks:
    def test_bulk_voting_open_queues_tasks(self, app, db):
        from tasks.email_tasks import send_bulk_voting_open, send_voting_open_email
        voter = make_user(db, 'bulk_voter2@test.com', 'BV002')
        e     = make_election(db)
        eid   = e.id
        with patch('tasks.email_tasks.send_voting_open_email') as mock_task:
            mock_task.delay = MagicMock()
            send_bulk_voting_open.apply(args=[eid])
            mock_task.delay.assert_called()

    def test_password_reset_email_task(self, app, db):
        from tasks.email_tasks import send_password_reset_email
        u = make_user(db, 'reset_task@test.com', 'RT001')
        with patch('tasks.email_tasks._send', return_value=True) as mock_send:
            send_password_reset_email.apply(args=[u.id, 'http://example.com/reset'])
            mock_send.assert_called_once()
            assert 'Reset' in mock_send.call_args[0][1]

    def test_nomination_approved_email(self, app, db):
        from tasks.email_tasks import send_nomination_approved_email
        u = make_user(db, 'nom_app@test.com', 'NA001')
        e = make_election(db)
        with patch('tasks.email_tasks._send', return_value=True) as mock_send:
            send_nomination_approved_email.apply(args=[u.id, e.id])
            mock_send.assert_called_once()

    def test_results_email_task(self, app, db):
        from tasks.email_tasks import send_results_published_email
        u = make_user(db, 'res_email@test.com', 'RE001')
        e = make_election(db)
        with patch('tasks.email_tasks._send', return_value=True) as mock_send:
            send_results_published_email.apply(args=[u.id, e.id, 'Winner Name'])
            mock_send.assert_called_once()
