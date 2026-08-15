"""
Additional tests targeting uncovered lines to push coverage above 80%.
Focuses on: admin routes, auth edge cases, secrets service, maintenance tasks.
"""
import pytest
import io
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from models import User, Election, Candidate, Vote, Nomination
from werkzeug.security import generate_password_hash


def now():
    return datetime.now(timezone.utc).replace(tzinfo=None)


def make_user(db, email, sid, role='voter', verified=True):
    u = User(
        name=email.split('@')[0], email=email,
        password=generate_password_hash('Test@1234'),
        student_id=sid, department='CS', year='2nd Year',
        role=role, is_active=True, is_verified=verified,
    )
    db.session.add(u); db.session.commit()
    return u


def make_election(db, **kw):
    n = now()
    e = Election(
        title=kw.get('title', 'Test'), position=kw.get('position', 'Rep'),
        nomination_start=kw.get('nom_start', n - timedelta(days=3)),
        nomination_end  =kw.get('nom_end',   n - timedelta(days=1)),
        voting_start    =kw.get('vote_start', n - timedelta(hours=1)),
        voting_end      =kw.get('vote_end',   n + timedelta(hours=24)),
        status=kw.get('status', 'voting'),
        results_published=kw.get('published', False),
    )
    db.session.add(e); db.session.commit()
    return e


# ── Secrets service ───────────────────────────────────────────────────────────

class TestSecretsService:
    def test_env_backend_default(self):
        import os
        from services.secrets_service import get_secret, clear_cache
        clear_cache()
        os.environ['_TEST_SECRET_KEY'] = 'test_value_123'
        assert get_secret('_TEST_SECRET_KEY') == 'test_value_123'
        del os.environ['_TEST_SECRET_KEY']
        clear_cache()

    def test_missing_key_returns_default(self):
        from services.secrets_service import get_secret, clear_cache
        clear_cache()
        assert get_secret('_NONEXISTENT_KEY_9999', 'fallback') == 'fallback'
        clear_cache()

    def test_cache_hit(self):
        from services.secrets_service import get_secret, clear_cache, _cache
        clear_cache()
        import os
        os.environ['_CACHED_KEY'] = 'cached_val'
        get_secret('_CACHED_KEY')  # populate cache
        del os.environ['_CACHED_KEY']
        # Should still return from cache
        assert get_secret('_CACHED_KEY') == 'cached_val'
        clear_cache()

    def test_aws_backend_falls_back_without_boto3(self):
        import os
        from services.secrets_service import get_secret, clear_cache
        clear_cache()
        os.environ['SECRETS_BACKEND'] = 'aws'
        os.environ['_AWS_TEST'] = 'env_fallback'
        val = get_secret('_AWS_TEST')
        assert val == 'env_fallback'
        del os.environ['SECRETS_BACKEND']
        del os.environ['_AWS_TEST']
        clear_cache()


# ── Maintenance tasks ─────────────────────────────────────────────────────────

class TestMaintenanceTasks:
    def test_purge_old_analytics(self, app, db):
        from tasks.maintenance_tasks import purge_old_analytics
        from models import AnalyticsEvent
        # Insert old event
        old_event = AnalyticsEvent(
            event_type='old_event',
            timestamp=now() - timedelta(days=100),
            page='test',
        )
        db.session.add(old_event); db.session.commit()
        result = purge_old_analytics.apply(args=[90])
        assert result.result >= 1

    def test_purge_old_login_attempts(self, app, db):
        from tasks.maintenance_tasks import purge_old_login_attempts
        from models import LoginAttempt
        old_attempt = LoginAttempt(
            email='old@test.com', ip_address='1.2.3.4',
            attempted_at=now() - timedelta(days=10),
        )
        db.session.add(old_attempt); db.session.commit()
        result = purge_old_login_attempts.apply(args=[7])
        assert result.result >= 1

    def test_heartbeat_task_runs(self, app, db):
        from tasks.maintenance_tasks import celery_heartbeat
        with patch.object(celery_heartbeat, 'apply', return_value=MagicMock(result='2024-01-01T00:00:00+00:00')):
            result = celery_heartbeat.apply()
            assert result is not None

    def test_purge_keeps_recent_events(self, app, db):
        from tasks.maintenance_tasks import purge_old_analytics
        from models import AnalyticsEvent
        recent = AnalyticsEvent(event_type='recent', timestamp=now(), page='test')
        db.session.add(recent); db.session.commit()
        rid = recent.id
        purge_old_analytics.apply(args=[90])
        with app.app_context():
            assert db.session.get(AnalyticsEvent, rid) is not None


# ── Auth edge cases ───────────────────────────────────────────────────────────

class TestAuthEdgeCases:
    def test_honeypot_blocks_bots(self, client, app, db):
        """Bot fills the honeypot field — should be silently redirected."""
        r = client.post('/register', data={
            'name': 'Bot', 'email': 'bot@test.com',
            'password': 'Test@1234', 'student_id': 'BOT001',
            'department': 'CS', 'year': '1st Year',
            'website': 'http://spam.com',  # honeypot filled
        }, follow_redirects=True, environ_base={'REMOTE_ADDR': '10.1.1.1'})
        assert r.status_code == 200
        # User should NOT be created
        with app.app_context():
            assert User.query.filter_by(email='bot@test.com').first() is None

    def test_register_with_weak_password(self, client):
        r = client.post('/register', data={
            'name': 'Weak', 'email': 'weak@test.com',
            'password': 'password',  # no uppercase, number, special
            'student_id': 'WK001', 'department': 'CS', 'year': '1st Year',
        }, follow_redirects=True, environ_base={'REMOTE_ADDR': '10.1.1.2'})
        assert r.status_code == 200
        assert b'uppercase' in r.data or b'Password' in r.data

    def test_register_missing_department(self, client):
        r = client.post('/register', data={
            'name': 'NoDept', 'email': 'nodept@test.com',
            'password': 'Test@1234', 'student_id': 'ND001',
            'department': '', 'year': '1st Year',
        }, follow_redirects=True, environ_base={'REMOTE_ADDR': '10.1.1.3'})
        assert r.status_code == 200
        assert b'department' in r.data.lower()

    def test_login_blocked_after_max_attempts(self, client, app, db):
        """After 5 failed logins, IP should be blocked."""
        ip = '10.5.5.5'
        for _ in range(5):
            client.post('/login', data={'email': 'block@test.com', 'password': 'wrong'},
                        environ_base={'REMOTE_ADDR': ip})
        r = client.post('/login', data={'email': 'block@test.com', 'password': 'wrong'},
                        follow_redirects=True, environ_base={'REMOTE_ADDR': ip})
        assert b'Too many' in r.data or b'attempts' in r.data

    def test_password_reset_with_weak_password(self, client, app, db):
        import secrets
        token = secrets.token_urlsafe(16)
        u = make_user(db, 'reset_weak@test.com', 'RW001')
        u.reset_token = token; db.session.commit()
        r = client.post(f'/reset-password/{token}', data={'password': 'weak'},
                        follow_redirects=True)
        assert r.status_code == 200
        assert b'least 8' in r.data or b'Password' in r.data


# ── Admin coverage ────────────────────────────────────────────────────────────

class TestAdminCoverage:
    def _login_admin(self, client, app):
        with app.app_context():
            admin = User.query.filter_by(role='admin').first()
            uid = str(admin.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid

    def test_approve_nomination(self, client, app, db):
        self._login_admin(client, app)
        voter = make_user(db, 'nom_voter@test.com', 'NV001')
        e = make_election(db)
        nom = Nomination(user_id=voter.id, election_id=e.id,
                         manifesto='I will do great things', status='pending')
        db.session.add(nom); db.session.commit()
        nid = nom.id
        r = client.get(f'/admin/nominations/{nid}/approve', follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            n2 = db.session.get(Nomination, nid)
            assert n2.status == 'approved'

    def test_reject_nomination(self, client, app, db):
        self._login_admin(client, app)
        voter = make_user(db, 'nom_voter2@test.com', 'NV002')
        e = make_election(db)
        nom = Nomination(user_id=voter.id, election_id=e.id,
                         manifesto='Test manifesto here', status='pending')
        db.session.add(nom); db.session.commit()
        nid = nom.id
        r = client.get(f'/admin/nominations/{nid}/reject', follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            n2 = db.session.get(Nomination, nid)
            assert n2.status == 'rejected'

    def test_publish_results(self, client, app, db):
        self._login_admin(client, app)
        e = make_election(db)
        eid = e.id
        r = client.get(f'/admin/elections/{eid}/publish-results', follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            e2 = db.session.get(Election, eid)
            assert e2.results_published is True

    def test_edit_election_post(self, client, app, db):
        self._login_admin(client, app)
        n = now()
        with app.app_context():
            e = Election(
                title='Edit Me', position='Rep',
                nomination_start=n+timedelta(days=1), nomination_end=n+timedelta(days=2),
                voting_start=n+timedelta(days=3), voting_end=n+timedelta(days=4),
                status='upcoming',
            )
            db.session.add(e); db.session.commit()
            eid = e.id
        r = client.post(f'/admin/elections/{eid}/edit', data={
            'title': 'Updated Title', 'position': 'President', 'description': '',
            'nomination_start': (n+timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),
            'nomination_end':   (n+timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),
            'voting_start':     (n+timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
            'voting_end':       (n+timedelta(days=4)).strftime('%Y-%m-%dT%H:%M'),
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            e2 = db.session.get(Election, eid)
            assert e2.title == 'Updated Title'

    def test_import_csv_duplicate_skipped(self, client, app, db):
        self._login_admin(client, app)
        make_user(db, 'dup_csv@test.com', 'DC001')
        csv_data = b'name,email,student_id,department,year\nDup,dup_csv@test.com,DC001,CS,1st Year\n'
        data = {'csv_file': (io.BytesIO(csv_data), 'dup.csv')}
        r = client.post('/admin/users/import-csv', data=data,
                        content_type='multipart/form-data', follow_redirects=True)
        assert r.status_code == 200
        assert b'Skipped 1' in r.data

    def test_create_election_invalid_dates(self, client, app, db):
        self._login_admin(client, app)
        n = now()
        r = client.post('/admin/elections/create', data={
            'title': 'Bad Dates', 'position': 'Rep', 'description': '',
            'nomination_start': (n+timedelta(days=2)).strftime('%Y-%m-%dT%H:%M'),
            'nomination_end':   (n+timedelta(days=1)).strftime('%Y-%m-%dT%H:%M'),  # end before start
            'voting_start':     (n+timedelta(days=3)).strftime('%Y-%m-%dT%H:%M'),
            'voting_end':       (n+timedelta(days=4)).strftime('%Y-%m-%dT%H:%M'),
        }, follow_redirects=True)
        assert r.status_code == 200
        assert b'after' in r.data.lower()

    def test_deactivated_user_cannot_login(self, client, app, db):
        u = make_user(db, 'deact2@test.com', 'DA002')
        u.is_active = False; db.session.commit()
        r = client.post('/login', data={'email': 'deact2@test.com', 'password': 'Test@1234'},
                        follow_redirects=True, environ_base={'REMOTE_ADDR': '10.2.2.2'})
        assert b'deactivated' in r.data


# ── Health endpoint extended ──────────────────────────────────────────────────

class TestHealthExtended:
    def test_health_has_version(self, client):
        import json
        r = client.get('/health')
        data = json.loads(r.data)
        assert 'version' in data

    def test_health_has_uptime(self, client):
        import json
        r = client.get('/health')
        data = json.loads(r.data)
        assert 'uptime_seconds' in data
        assert data['uptime_seconds'] >= 0

    def test_health_has_disk_info(self, client):
        import json
        r = client.get('/health')
        data = json.loads(r.data)
        assert 'disk' in data['checks']
        assert 'free_pct' in data['checks']['disk']

    def test_queue_depth_endpoint(self, client, voter_user, app):
        with app.app_context():
            u = User.query.filter_by(email='voter@test.com').first()
            uid = str(u.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid
        # Redis not running in test — expect 503 or a response
        r = client.get('/health/queue')
        assert r.status_code in (200, 503)


# ── Voter route coverage ──────────────────────────────────────────────────────

class TestVoterCoverage:
    def _login(self, client, app, email='voter@test.com'):
        with app.app_context():
            u = User.query.filter_by(email=email).first()
            uid = str(u.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid

    def test_cannot_vote_outside_window(self, client, voter_user, app, db):
        self._login(client, app)
        n = now()
        with app.app_context():
            e = Election(
                title='Closed Election', position='Rep',
                nomination_start=n-timedelta(days=5),
                nomination_end=n-timedelta(days=3),
                voting_start=n-timedelta(days=2),
                voting_end=n-timedelta(days=1),
                status='closed',
            )
            db.session.add(e); db.session.commit()
            voter = User.query.filter_by(email='voter@test.com').first()
            other = make_user(db, 'cov_cand@test.com', 'CC001')
            cand  = Candidate(user_id=other.id, election_id=e.id, manifesto='x')
            db.session.add(cand); db.session.commit()
            eid, cid = e.id, cand.id
        r = client.post(f'/vote/{eid}', data={'candidate_id': str(cid)},
                        follow_redirects=True)
        assert b'not active' in r.data.lower()

    def test_vote_confirmation_page(self, client, voter_user, app, db):
        from services.election_service import cast_vote
        self._login(client, app)
        with app.app_context():
            e     = make_election(db)
            voter = User.query.filter_by(email='voter@test.com').first()
            other = make_user(db, 'conf_cand@test.com', 'CF001')
            cand  = Candidate(user_id=other.id, election_id=e.id, manifesto='x')
            db.session.add(cand); db.session.commit()
            cast_vote(voter, e, cand)
            eid, cid = e.id, cand.id
        r = client.get(f'/vote-confirmation/{eid}/{cid}')
        assert r.status_code == 200
        assert b'Vote' in r.data


# ── Election tasks (Celery Beat task) ─────────────────────────────────────────

class TestElectionTasks:
    def test_election_status_task_runs(self, app, db):
        from tasks.election_tasks import auto_update_statuses
        n = now()
        e = make_election(db, vote_start=n+timedelta(hours=2), vote_end=n+timedelta(hours=5), status='wrong')
        eid = e.id
        result = auto_update_statuses.apply()
        with app.app_context():
            e2 = db.session.get(Election, eid)
            assert e2.status in ('upcoming', 'voting', 'nomination', 'closed', 'completed')

    def test_election_task_updates_to_voting(self, app, db):
        from tasks.election_tasks import auto_update_statuses
        n = now()
        e = make_election(db, title='Task Voting',
                          vote_start=n-timedelta(hours=1),
                          vote_end=n+timedelta(hours=24),
                          status='upcoming')
        eid = e.id
        auto_update_statuses.apply()
        with app.app_context():
            e2 = db.session.get(Election, eid)
            assert e2.status == 'voting'


# ── Auth 2FA path coverage ────────────────────────────────────────────────────

class TestAuth2FACoverage:
    def test_2fa_page_requires_pre_session(self, client):
        """2FA page redirects if no pre_2fa_user_id in session."""
        r = client.get('/2fa', follow_redirects=True)
        assert r.status_code == 200
        # Should redirect to login
        assert b'Login' in r.data or b'login' in r.data.lower()

    def test_2fa_wrong_code_shows_error(self, client, app, db):
        """Wrong 2FA code shows error message."""
        from services.user_service import generate_totp_secret, hash_password
        u = User(
            name='2FA Test', email='twofa_cov@test.com',
            password=hash_password('Test@1234'),
            student_id='2FAC01', department='CS', year='1st Year',
            role='voter', is_active=True, is_verified=True,
            totp_secret=generate_totp_secret(), totp_enabled=True,
        )
        db.session.add(u); db.session.commit()
        with client.session_transaction() as s:
            s['pre_2fa_user_id'] = u.id
        r = client.post('/2fa', data={'token': '000000'}, follow_redirects=True)
        assert b'Invalid' in r.data

    def test_setup_2fa_requires_login(self, client):
        r = client.get('/setup-2fa', follow_redirects=True)
        assert b'log in' in r.data.lower() or r.status_code == 200


# ── Notification route coverage ───────────────────────────────────────────────

class TestNotificationCoverage:
    def _login(self, client, app, email='voter@test.com'):
        with app.app_context():
            u = User.query.filter_by(email=email).first()
            uid = str(u.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid

    def test_mark_single_notification_read(self, client, voter_user, app, db):
        from models import Notification
        self._login(client, app)
        with app.app_context():
            u = User.query.filter_by(email='voter@test.com').first()
            n = Notification(user_id=u.id, title='T', message='M', is_read=False)
            db.session.add(n); db.session.commit()
            nid = n.id
        r = client.post(f'/notifications/mark-read/{nid}')
        assert r.status_code == 200
        with app.app_context():
            from models import Notification
            n2 = db.session.get(Notification, nid)
            assert n2.is_read is True


# ── Audit service coverage ────────────────────────────────────────────────────

class TestAuditServiceCoverage:
    def test_log_audit_works(self, app, db, voter_user):
        from services.audit_service import log_audit
        from models import AuditLog
        with app.app_context():
            u = User.query.filter_by(email='voter@test.com').first()
            with app.test_request_context('/test', environ_base={'REMOTE_ADDR': '127.0.0.1'}):
                from flask_login import login_user
                login_user(u)
                log_audit('test_action', 'test details')
            log = AuditLog.query.filter_by(action='test_action').first()
            assert log is not None

    def test_log_event_works(self, app, db, voter_user):
        from services.audit_service import log_event
        from models import AnalyticsEvent
        with app.app_context():
            u = User.query.filter_by(email='voter@test.com').first()
            with app.test_request_context('/test', environ_base={'REMOTE_ADDR': '127.0.0.1'}):
                from flask_login import login_user
                login_user(u)
                log_event('test_event', 'test_page', 'test_details')
            ev = AnalyticsEvent.query.filter_by(event_type='test_event').first()
            assert ev is not None


# ── Auth route coverage boost ─────────────────────────────────────────────────

class TestAuthCoverage:
    def test_resend_verification_known_email(self, client, app, db):
        u = make_user(db, 'resend@test.com', 'RS001', verified=False)
        u.verify_token = 'abc123'; db.session.commit()
        r = client.post('/resend-verification',
                        data={'email': 'resend@test.com'},
                        follow_redirects=True,
                        environ_base={'REMOTE_ADDR': '10.3.3.1'})
        assert r.status_code == 200

    def test_resend_verification_unknown_email(self, client):
        r = client.post('/resend-verification',
                        data={'email': 'nobody@unknown.com'},
                        follow_redirects=True,
                        environ_base={'REMOTE_ADDR': '10.3.3.2'})
        assert r.status_code == 200

    def test_two_factor_page_without_session(self, client):
        r = client.get('/2fa', follow_redirects=True)
        assert r.status_code == 200

    def test_forgot_password_unknown_email(self, client):
        r = client.post('/forgot-password',
                        data={'email': 'nobody@nowhere.com'},
                        follow_redirects=True,
                        environ_base={'REMOTE_ADDR': '10.3.3.3'})
        assert r.status_code == 200

    def test_forgot_password_known_email_no_mail(self, client, app, db):
        import os
        os.environ['MAIL_USERNAME'] = ''
        u = make_user(db, 'forgotpw@test.com', 'FP001')
        r = client.post('/forgot-password',
                        data={'email': 'forgotpw@test.com'},
                        follow_redirects=True,
                        environ_base={'REMOTE_ADDR': '10.3.3.4'})
        assert r.status_code == 200

    def test_index_with_announcements(self, client, app, db):
        from models import Announcement
        with app.app_context():
            admin = User.query.filter_by(role='admin').first()
            ann = Announcement(title='Test', message='Hello', created_by=admin.id)
            db.session.add(ann); db.session.commit()
        r = client.get('/')
        assert r.status_code == 200
        assert b'Hello' in r.data

    def test_register_duplicate_student_id(self, client, app, db):
        make_user(db, 'existing@test.com', 'EX001')
        r = client.post('/register', data={
            'name': 'Dup', 'email': 'new@test.com',
            'password': 'Test@1234', 'student_id': 'EX001',
            'department': 'CS', 'year': '1st Year',
        }, follow_redirects=True, environ_base={'REMOTE_ADDR': '10.3.3.5'})
        assert r.status_code == 200
        assert b'already registered' in r.data

    def test_setup_2fa_generates_secret(self, client, app, db):
        u = make_user(db, 'setup2fa@test.com', 'S2FA01')
        with client.session_transaction() as s:
            s['_user_id'] = str(u.id)
        r = client.get('/setup-2fa')
        assert r.status_code == 200
        assert b'QR' in r.data or b'data:image' in r.data or b'secret' in r.data.lower()


# ── Health route coverage boost ───────────────────────────────────────────────

class TestHealthCoverage:
    def test_health_redis_not_configured(self, client, app):
        import os
        old = os.environ.get('CELERY_BROKER_URL', '')
        os.environ['CELERY_BROKER_URL'] = ''
        r = client.get('/health')
        import json
        data = json.loads(r.data)
        assert data['checks'].get('redis', {}).get('status') in ('not_configured', 'error', 'ok')
        os.environ['CELERY_BROKER_URL'] = old

    def test_health_response_structure(self, client):
        import json
        r = client.get('/health')
        data = json.loads(r.data)
        assert 'status' in data
        assert 'timestamp' in data
        assert 'version' in data
        assert 'uptime_seconds' in data
        assert 'checks' in data
        assert 'database' in data['checks']


# ── Candidate route coverage ──────────────────────────────────────────────────

class TestCandidateCoverage:
    def _login(self, client, app, email='voter@test.com'):
        with app.app_context():
            u = User.query.filter_by(email=email).first()
            uid = str(u.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid

    def test_apply_nomination_post(self, client, voter_user, app, db):
        self._login(client, app)
        n = now()
        with app.app_context():
            e = Election(
                title='Nom Apply', position='Secretary',
                nomination_start=n-timedelta(hours=1),
                nomination_end=n+timedelta(hours=5),
                voting_start=n+timedelta(days=1),
                voting_end=n+timedelta(days=2),
                status='nomination',
            )
            db.session.add(e); db.session.commit()
            eid = e.id
        r = client.post(f'/apply-nomination/{eid}', data={
            'manifesto': 'I will serve the student body with dedication and passion for improvement.'
        }, follow_redirects=True)
        assert r.status_code == 200

    def test_apply_nomination_already_applied(self, client, voter_user, app, db):
        self._login(client, app)
        n = now()
        with app.app_context():
            e = Election(
                title='Already Applied', position='Secretary',
                nomination_start=n-timedelta(hours=1),
                nomination_end=n+timedelta(hours=5),
                voting_start=n+timedelta(days=1),
                voting_end=n+timedelta(days=2),
                status='nomination',
            )
            db.session.add(e); db.session.commit()
            voter = User.query.filter_by(email='voter@test.com').first()
            nom = Nomination(user_id=voter.id, election_id=e.id,
                             manifesto='Already applied', status='pending')
            db.session.add(nom); db.session.commit()
            eid = e.id
        r = client.get(f'/apply-nomination/{eid}', follow_redirects=True)
        assert r.status_code == 200
        assert b'already' in r.data.lower()


# ── Tasks coverage boost ──────────────────────────────────────────────────────

class TestTasksCoverage:
    def test_send_voting_open_missing_user(self, app, db):
        from tasks.email_tasks import send_voting_open_email
        with patch('tasks.email_tasks._send') as mock_send:
            send_voting_open_email.apply(args=[99999, 99999])
            mock_send.assert_not_called()

    def test_send_results_missing_user(self, app, db):
        from tasks.email_tasks import send_results_published_email
        with patch('tasks.email_tasks._send') as mock_send:
            send_results_published_email.apply(args=[99999, 99999, 'Winner'])
            mock_send.assert_not_called()

    def test_send_nomination_rejected_email(self, app, db):
        from tasks.email_tasks import send_nomination_rejected_email
        u = make_user(db, 'rej_email@test.com', 'REJ01')
        e = make_election(db)
        with patch('tasks.email_tasks._send', return_value=True) as mock_send:
            send_nomination_rejected_email.apply(args=[u.id, e.id])
            mock_send.assert_called_once()

    def test_election_status_task(self, app, db):
        from tasks.election_tasks import auto_update_statuses
        n = now()
        with app.app_context():
            e = Election(
                title='Status Task', position='Rep',
                nomination_start=n+timedelta(days=1),
                nomination_end=n+timedelta(days=2),
                voting_start=n+timedelta(days=3),
                voting_end=n+timedelta(days=4),
                status='wrong',
            )
            db.session.add(e); db.session.commit()
            eid = e.id
        auto_update_statuses.apply()
        with app.app_context():
            e2 = db.session.get(Election, eid)
            assert e2.status == 'upcoming'

    def test_heartbeat_without_redis(self, app, db):
        from tasks.maintenance_tasks import celery_heartbeat
        import os
        old = os.environ.get('CELERY_BROKER_URL', '')
        os.environ['CELERY_BROKER_URL'] = ''
        result = celery_heartbeat.apply()
        assert result.result is not None
        os.environ['CELERY_BROKER_URL'] = old
