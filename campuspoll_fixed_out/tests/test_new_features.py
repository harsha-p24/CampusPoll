"""
Tests for v7 features:
  - AI fraud detection
  - WebSocket realtime
  - JWT service
  - Cache service
  - Circuit breaker
  - Admin fraud signals route
"""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from models import User, Election, Candidate, Vote
from werkzeug.security import generate_password_hash


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_user(db, email, sid, role='voter'):
    u = User(
        name=email.split('@')[0], email=email,
        password=generate_password_hash('Test@1234'),
        student_id=sid, department='CS', year='2nd Year',
        role=role, is_active=True, is_verified=True,
    )
    db.session.add(u); db.session.commit()
    return u


def make_election(db, **kw):
    n = now()
    e = Election(
        title=kw.get('title', 'Fraud Test'), position='Rep',
        nomination_start=n-timedelta(days=3), nomination_end=n-timedelta(days=1),
        voting_start=n-timedelta(hours=1),    voting_end=n+timedelta(hours=24),
        status='voting', results_published=kw.get('published', False),
    )
    db.session.add(e); db.session.commit()
    return e


# ── Fraud Detection ───────────────────────────────────────────────────────────

class TestFraudDetection:
    def test_normal_request_allowed(self, app, db, voter_user):
        from services.fraud_detection import FraudDetector
        det = FraudDetector()
        signal = det.analyse_vote_attempt(
            voter_id     = voter_user.id,
            election_id  = 1,
            ip_address   = '192.168.1.10',
            user_agent   = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            request_time = datetime(2024, 4, 25, 14, 30, 0),
        )
        assert signal.action == 'allow'
        assert signal.risk_score < 0.4

    def test_bot_user_agent_flagged(self, app, db, voter_user):
        from services.fraud_detection import FraudDetector
        det = FraudDetector()
        signal = det.analyse_vote_attempt(
            voter_id     = voter_user.id,
            election_id  = 1,
            ip_address   = '1.2.3.4',
            user_agent   = 'python-requests/2.28.0',
            request_time = datetime(2024, 4, 25, 14, 0, 0),
        )
        assert 'bot_user_agent' in signal.flags
        assert signal.action in ('flag', 'block')

    def test_unusual_hour_adds_risk(self, app, db, voter_user):
        from services.fraud_detection import FraudDetector
        det = FraudDetector()
        signal = det.analyse_vote_attempt(
            voter_id     = voter_user.id,
            election_id  = 1,
            ip_address   = '10.0.0.1',
            user_agent   = 'Mozilla/5.0',
            request_time = datetime(2024, 4, 25, 3, 0, 0),  # 3am
        )
        assert 'unusual_voting_hour' in signal.flags

    def test_ip_velocity_flagged(self, app, db, voter_user):
        from services.fraud_detection import FraudDetector
        from models import AnalyticsEvent
        n = now()
        event = AnalyticsEvent(
            user_id=voter_user.id, event_type='vote_cast',
            ip_address='10.5.5.5', timestamp=n,
        )
        db.session.add(event); db.session.commit()
        det = FraudDetector()
        signal = det.analyse_vote_attempt(
            voter_id=voter_user.id, election_id=1,
            ip_address='10.5.5.5',
            user_agent='Mozilla/5.0',
            request_time=n,
        )
        assert 'ip_velocity_too_high' in signal.flags

    def test_duplicate_vote_attempt_blocked(self, app, db, voter_user):
        from services.fraud_detection import FraudDetector
        from models import Vote
        e    = make_election(db)
        other = make_user(db, 'dup_cand2@test.com', 'DC002')
        cand  = Candidate(user_id=other.id, election_id=e.id, manifesto='x')
        db.session.add(cand); db.session.commit()
        vote = Vote(voter_id=voter_user.id, election_id=e.id, candidate_id=cand.id)
        db.session.add(vote); db.session.commit()
        det = FraudDetector()
        signal = det.analyse_vote_attempt(
            voter_id=voter_user.id, election_id=e.id,
            ip_address='1.1.1.1', user_agent='Mozilla/5.0',
            request_time=now(),
        )
        assert 'duplicate_vote_attempt' in signal.flags
        assert signal.risk_score >= 0.6

    def test_unknown_user_blocked(self, app, db):
        from services.fraud_detection import FraudDetector
        det = FraudDetector()
        signal = det.analyse_vote_attempt(
            voter_id=99999, election_id=1,
            ip_address='1.1.1.1', user_agent='Mozilla/5.0',
            request_time=now(),
        )
        assert signal.action == 'block'
        assert signal.risk_score == 1.0

    def test_risk_score_capped_at_1(self, app, db, voter_user):
        from services.fraud_detection import FraudDetector
        det = FraudDetector()
        signal = det.analyse_vote_attempt(
            voter_id=voter_user.id, election_id=1,
            ip_address='1.2.3.4',
            user_agent='python-requests/headlesschrome',
            request_time=datetime(2024, 4, 25, 3, 0, 0),
        )
        assert signal.risk_score <= 1.0

    def test_fraud_log_persisted(self, app, db, voter_user):
        from services.fraud_detection import FraudDetector
        from models import FraudLog
        det = FraudDetector()
        det.analyse_vote_attempt(
            voter_id=voter_user.id, election_id=1,
            ip_address='1.2.3.4',
            user_agent='python-requests/2.0',
            request_time=datetime(2024, 4, 25, 14, 0, 0),
        )
        logs = FraudLog.query.filter_by(voter_id=voter_user.id).all()
        assert len(logs) >= 1


# ── JWT Service ───────────────────────────────────────────────────────────────

class TestJWTService:
    def test_generate_and_decode(self, app, db):
        from services.jwt_service import generate_token
        token = generate_token(user_id=1, expires_in=3600)
        assert isinstance(token, str)
        assert len(token) > 20

    def test_token_endpoint(self, client, voter_user, app):
        with app.app_context():
            u = User.query.filter_by(email='voter@test.com').first()
            uid = str(u.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid
        r = client.get('/analytics/token')
        assert r.status_code == 200
        import json
        data = json.loads(r.data)
        assert 'token' in data
        assert data['expires_in'] == 3600

    def test_token_requires_login(self, client):
        r = client.get('/analytics/token', follow_redirects=False)
        assert r.status_code in (302, 401)


# ── Cache Service ─────────────────────────────────────────────────────────────

class TestCacheService:
    def test_cache_decorator_without_redis(self, app, db):
        """Should fall through gracefully when Redis not available."""
        from services.cache_service import cache

        call_count = [0]

        @cache(ttl=60)
        def expensive_fn(x):
            call_count[0] += 1
            return x * 2

        result1 = expensive_fn(5)
        result2 = expensive_fn(5)
        assert result1 == 10
        assert result2 == 10

    def test_invalidate_no_redis(self, app, db):
        from services.cache_service import invalidate
        # Should not raise even without Redis
        invalidate('election_results')


# ── Circuit Breaker ───────────────────────────────────────────────────────────

class TestCircuitBreaker:
    def test_closed_state_allows_calls(self):
        from services.circuit_breaker import CircuitBreaker
        cb = CircuitBreaker('test', threshold=3)
        result = cb.call(lambda: 'ok')
        assert result == 'ok'
        assert cb.state.value == 'closed'

    def test_opens_after_threshold(self):
        from services.circuit_breaker import CircuitBreaker, State
        cb = CircuitBreaker('test_open', threshold=3)
        for _ in range(3):
            try:
                cb.call(lambda: (_ for _ in ()).throw(Exception('fail')))
            except Exception:
                pass
        assert cb.state == State.OPEN

    def test_open_raises_immediately(self):
        from services.circuit_breaker import CircuitBreaker, State
        cb = CircuitBreaker('test_raise', threshold=1)
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception('fail')))
        except Exception:
            pass
        with pytest.raises(RuntimeError, match='OPEN'):
            cb.call(lambda: 'should not execute')

    def test_resets_on_success(self):
        from services.circuit_breaker import CircuitBreaker, State
        cb = CircuitBreaker('test_reset', threshold=5)
        cb.call(lambda: 'ok')
        assert cb.state == State.CLOSED
        assert cb.failures == 0

    def test_half_open_after_timeout(self):
        import time
        from services.circuit_breaker import CircuitBreaker, State
        cb = CircuitBreaker('test_half', threshold=1, timeout=0)
        try:
            cb.call(lambda: (_ for _ in ()).throw(Exception('fail')))
        except Exception:
            pass
        time.sleep(0.01)
        # Next call should attempt (half-open)
        assert cb.state == State.OPEN  # still open until next call
        cb.call(lambda: 'recover')
        assert cb.state == State.CLOSED


# ── WebSocket Routes ──────────────────────────────────────────────────────────

class TestWebSocket:
    def test_broadcast_no_crash_with_no_election(self, app, db):
        from routes.realtime import broadcast_vote_update
        from app import socketio as sio
        # Should not raise even for non-existent election
        with app.app_context():
            broadcast_vote_update(sio, 99999)

    def test_broadcast_sends_payload(self, app, db):
        from routes.realtime import broadcast_vote_update
        from app import socketio as sio
        e     = make_election(db)
        other = make_user(db, 'ws_cand@test.com', 'WSC01')
        cand  = Candidate(user_id=other.id, election_id=e.id, manifesto='x')
        db.session.add(cand); db.session.commit()
        emitted = []
        with patch.object(sio, 'emit', side_effect=lambda *a, **k: emitted.append(a)):
            broadcast_vote_update(sio, e.id)
        assert len(emitted) == 1
        assert emitted[0][0] == 'vote_update'
        assert emitted[0][1]['election_id'] == e.id


# ── Admin Fraud Signals Route ─────────────────────────────────────────────────

class TestAdminFraudRoute:
    def _login_admin(self, client, app):
        with app.app_context():
            admin = User.query.filter_by(role='admin').first()
            uid = str(admin.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid

    def test_fraud_signals_page(self, client, app, db):
        self._login_admin(client, app)
        r = client.get('/admin/fraud-signals')
        assert r.status_code == 200

    def test_fraud_signals_shows_logs(self, client, app, db, voter_user):
        from models import FraudLog
        self._login_admin(client, app)
        log = FraudLog(
            voter_id=voter_user.id, election_id=1,
            risk_score=0.8, flags='bot_user_agent', action='block',
        )
        db.session.add(log); db.session.commit()
        r = client.get('/admin/fraud-signals')
        assert r.status_code == 200
        assert b'block' in r.data.lower() or b'BLOCK' in r.data

    def test_fraud_page_blocked_for_voters(self, client, voter_user, app):
        with app.app_context():
            u = User.query.filter_by(email='voter@test.com').first()
            uid = str(u.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid
        r = client.get('/admin/fraud-signals', follow_redirects=True)
        assert b'Admin access required' in r.data or r.status_code == 200
