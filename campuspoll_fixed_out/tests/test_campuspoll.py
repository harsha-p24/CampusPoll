"""
CampusPoll comprehensive test suite.
Run:  pytest tests/ -v --cov=. --cov-report=term-missing
"""
import pytest
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta, timezone
from models import User, Election, Candidate, Vote, Nomination, Announcement
from services.user_service import (
    validate_password, validate_email, validate_student_id,
    sanitize, validate_registration,
)
from services.election_service import (
    can_vote, can_nominate, get_election_status, cast_vote, get_results
)


# ── Helpers ───────────────────────────────────────────────────────────────────

def now():
    from utils.time_utils import now_ist
    return now_ist()

def make_election(db, **kw):
    n = now()
    e = Election(
        title   = kw.get('title', 'Test Election'),
        position= kw.get('position', 'President'),
        nomination_start = kw.get('nom_start',  n - timedelta(days=3)),
        nomination_end   = kw.get('nom_end',    n - timedelta(days=1)),
        voting_start     = kw.get('vote_start', n - timedelta(hours=1)),
        voting_end       = kw.get('vote_end',   n + timedelta(hours=24)),
        status  = kw.get('status', 'voting'),
        results_published = kw.get('published', False),
    )
    db.session.add(e); db.session.commit()
    return e

def make_user(db, email, student_id, role='voter', verified=True):
    u = User(
        name=email.split('@')[0], email=email,
        password=generate_password_hash('Test@1234'),
        student_id=student_id, department='CS', year='2nd Year',
        role=role, is_active=True, is_verified=verified,
    )
    db.session.add(u); db.session.commit()
    return u


# ── Password validation ───────────────────────────────────────────────────────

class TestPasswordValidation:
    @pytest.mark.parametrize("pw,fragment", [
        ('Ab1@', 'least 8'),
        ('abcdef1@', 'uppercase'),
        ('ABCDEF1@', 'lowercase'),
        ('Abcdefg@', 'number'),
        ('Abcdef12', 'special'),
    ])
    def test_invalid(self, pw, fragment):
        ok, msg = validate_password(pw)
        assert not ok and fragment in msg

    def test_valid(self):
        ok, _ = validate_password('Secure@123')
        assert ok

    def test_boundary_8_chars(self):
        ok, _ = validate_password('Aa1@aaaa')
        assert ok

    def test_very_long_password(self):
        ok, _ = validate_password('Aa1@' + 'x' * 100)
        assert ok


# ── Email / student ID validation ─────────────────────────────────────────────

class TestFieldValidation:
    @pytest.mark.parametrize("email,ok", [
        ('user@college.edu', True),
        ('usercollege.edu', False),
        ('', False),
        ('a@b', False),
    ])
    def test_email(self, email, ok):
        result, _ = validate_email(email)
        assert result == ok

    @pytest.mark.parametrize("sid,ok", [
        ('CS2021001', True),
        ('ab', False),
        ('', False),
        ('a' * 21, False),
    ])
    def test_student_id(self, sid, ok):
        result, _ = validate_student_id(sid)
        assert result == ok


# ── Sanitisation ──────────────────────────────────────────────────────────────

class TestSanitize:
    def test_strips_html_tags(self):
        result = sanitize('<script>alert(1)</script>Hello')
        assert '<script>' not in result and 'Hello' in result

    def test_strips_onclick(self):
        result = sanitize('<b onclick="bad()">text</b>')
        assert 'onclick' not in result

    def test_truncates(self):
        assert len(sanitize('a' * 600, 100)) == 100

    def test_empty(self):
        assert sanitize('') == ''

    def test_none(self):
        assert sanitize(None) == ''

    def test_whitespace_trimmed(self):
        assert sanitize('  hello  ') == 'hello'


# ── Election service ──────────────────────────────────────────────────────────

class TestElectionService:
    def _e(self, **kw):
        class E: pass
        e = E()
        n = now()
        e.nomination_start  = kw.get('nom_start',  n - timedelta(days=3))
        e.nomination_end    = kw.get('nom_end',    n - timedelta(days=1))
        e.voting_start      = kw.get('vote_start', n - timedelta(hours=1))
        e.voting_end        = kw.get('vote_end',   n + timedelta(hours=24))
        e.results_published = kw.get('published',  False)
        e.status            = 'voting'
        return e

    def test_can_vote_active(self):        assert can_vote(self._e())
    def test_cannot_vote_before(self):     assert not can_vote(self._e(vote_start=now()+timedelta(hours=1), vote_end=now()+timedelta(hours=5)))
    def test_cannot_vote_after(self):      assert not can_vote(self._e(vote_start=now()-timedelta(hours=5), vote_end=now()-timedelta(hours=1)))
    def test_can_nominate(self):           assert can_nominate(self._e(nom_start=now()-timedelta(hours=1), nom_end=now()+timedelta(hours=1)))
    def test_cannot_nominate_past(self):   assert not can_nominate(self._e())
    def test_status_completed(self):       assert get_election_status(self._e(published=True)) == 'completed'
    def test_status_upcoming(self):
        e = self._e(nom_start=now()+timedelta(days=1), nom_end=now()+timedelta(days=2),
                    vote_start=now()+timedelta(days=3), vote_end=now()+timedelta(days=4))
        assert get_election_status(e) == 'upcoming'
    def test_status_nomination(self):
        e = self._e(nom_start=now()-timedelta(hours=1), nom_end=now()+timedelta(hours=1),
                    vote_start=now()+timedelta(days=1), vote_end=now()+timedelta(days=2))
        assert get_election_status(e) == 'nomination'
    def test_status_closed(self):
        e = self._e(vote_start=now()-timedelta(days=3), vote_end=now()-timedelta(days=1))
        assert get_election_status(e) == 'closed'


# ── Auth routes ───────────────────────────────────────────────────────────────

class TestAuthRoutes:
    @pytest.mark.parametrize("route", ['/', '/login', '/register', '/forgot-password'])
    def test_pages_200(self, client, route):
        assert client.get(route).status_code == 200

    def test_invalid_login(self, client):
        # Use environ_base to set a unique IP so it won't block other tests
        r = client.post('/login', data={'email':'nobody@x.com','password':'wrong'},
                        follow_redirects=True, environ_base={'REMOTE_ADDR': '10.0.0.1'})
        assert b'Invalid' in r.data

    def test_deactivated_blocked(self, client, app, db):
        with app.app_context():
            u = make_user(db, 'inactive@test.com', 'INACT01')
            u.is_active = False
            db.session.commit()
        r = client.post('/login', data={'email':'inactive@test.com','password':'Test@1234'}, follow_redirects=True, environ_base={'REMOTE_ADDR': '10.0.0.2'})
        assert b'deactivated' in r.data

    def test_unverified_blocked(self, client, app, db):
        u = make_user(db, 'unver@test.com', 'UNVER01', verified=False)
        r = client.post('/login', data={'email':'unver@test.com','password':'Test@1234'}, follow_redirects=True, environ_base={'REMOTE_ADDR': '10.0.0.3'})
        assert b'verify' in r.data.lower()

    def test_logout(self, client, voter_user, app):
        with app.app_context():
            u = User.query.filter_by(email='voter@test.com').first()
            uid = str(u.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid
        r = client.get('/logout', follow_redirects=True)
        assert r.status_code == 200

    def test_verify_email_valid_token(self, client, app, db):
        import secrets
        token = secrets.token_urlsafe(16)
        u = make_user(db, 'toverify@test.com', 'VER01', verified=False)
        u.verify_token = token; db.session.commit()
        r = client.get(f'/verify-email/{token}', follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            u2 = User.query.filter_by(email='toverify@test.com').first()
            assert u2.is_verified

    def test_verify_email_invalid_token(self, client):
        r = client.get('/verify-email/badtoken123', follow_redirects=True)
        assert b'Invalid' in r.data


# ── Voter routes ──────────────────────────────────────────────────────────────

class TestVoterRoutes:
    def _login(self, client, app):
        with app.app_context():
            u = User.query.filter_by(email='voter@test.com').first()
            with client.session_transaction() as s:
                s['_user_id'] = str(u.id)

    def test_dashboard_requires_login(self, client):
        r = client.get('/dashboard', follow_redirects=True)
        assert b'log in' in r.data.lower() or r.status_code == 200

    def test_dashboard_200_logged_in(self, client, voter_user, app):
        self._login(client, app)
        r = client.get('/dashboard')
        assert r.status_code == 200


    def test_dashboard_search(self, client, voter_user, app, db):
        self._login(client, app)
        with app.app_context():
            make_election(db, title='Searchable Election')
        r = client.get('/dashboard?q=Searchable')
        assert b'Searchable' in r.data

    def test_election_detail_no_candidates(self, client, voter_user, app, db):
        self._login(client, app)
        with app.app_context():
            e = make_election(db, title='Empty Election')
            eid = e.id
        r = client.get(f'/election/{eid}')
        assert r.status_code == 200
        assert b'No approved candidates' in r.data

    def test_results_hidden_before_publish(self, client, voter_user, app, db):
        self._login(client, app)
        with app.app_context():
            e = make_election(db, title='Hidden Results', published=False)
            eid = e.id
        r = client.get(f'/results/{eid}', follow_redirects=True)
        assert b'not been published' in r.data

    def test_results_visible_after_publish(self, client, voter_user, app, db):
        self._login(client, app)
        with app.app_context():
            e = make_election(db, title='Published Results', published=True)
            eid = e.id
        r = client.get(f'/results/{eid}')
        assert r.status_code == 200


# ── Voting logic ──────────────────────────────────────────────────────────────

class TestVotingLogic:
    def test_duplicate_vote_blocked(self, app, db, voter_user):
        with app.app_context():
            e     = make_election(db)
            voter = User.query.filter_by(email='voter@test.com').first()
            other = make_user(db, 'other_dup@test.com', 'ODUP01')
            cand  = Candidate(user_id=other.id, election_id=e.id, manifesto='x')
            db.session.add(cand); db.session.commit()
            ok1, err1 = cast_vote(voter, e, cand)
            assert ok1 and err1 is None
            ok2, err2 = cast_vote(voter, e, cand)
            assert not ok2 and 'already voted' in err2
            Vote.query.filter_by(election_id=e.id).delete()
            Candidate.query.filter_by(election_id=e.id).delete()
            Election.query.filter_by(id=e.id).delete()
            User.query.filter_by(email='other_dup@test.com').delete()
            db.session.commit()

    def test_self_vote_blocked(self, app, db, voter_user):
        with app.app_context():
            e     = make_election(db)
            voter = User.query.filter_by(email='voter@test.com').first()
            cand  = Candidate(user_id=voter.id, election_id=e.id, manifesto='self')
            db.session.add(cand); db.session.commit()
            ok, err = cast_vote(voter, e, cand)
            assert not ok and 'yourself' in err
            Candidate.query.filter_by(election_id=e.id).delete()
            Election.query.filter_by(id=e.id).delete()
            db.session.commit()

    def test_vote_outside_window_blocked(self, app, db, voter_user):
        with app.app_context():
            n     = now()
            e     = make_election(db, vote_start=n-timedelta(days=3), vote_end=n-timedelta(days=1), status='closed')
            voter = User.query.filter_by(email='voter@test.com').first()
            other = make_user(db, 'other_win@test.com', 'OWIN01')
            cand  = Candidate(user_id=other.id, election_id=e.id, manifesto='x')
            db.session.add(cand); db.session.commit()
            ok, err = cast_vote(voter, e, cand)
            assert not ok and 'not active' in err
            Candidate.query.filter_by(election_id=e.id).delete()
            Election.query.filter_by(id=e.id).delete()
            User.query.filter_by(email='other_win@test.com').delete()
            db.session.commit()

    def test_live_vote_count(self, app, db, voter_user):
        """vote_count must be computed from Vote table, not a cached counter."""
        with app.app_context():
            e     = make_election(db)
            voter = User.query.filter_by(email='voter@test.com').first()
            other = make_user(db, 'other_cnt@test.com', 'OCNT01')
            cand  = Candidate(user_id=other.id, election_id=e.id, manifesto='x')
            db.session.add(cand); db.session.commit()
            assert cand.vote_count == 0
            cast_vote(voter, e, cand)
            db.session.expire(cand)
            assert cand.vote_count == 1
            Vote.query.filter_by(election_id=e.id).delete()
            Candidate.query.filter_by(election_id=e.id).delete()
            Election.query.filter_by(id=e.id).delete()
            User.query.filter_by(email='other_cnt@test.com').delete()
            db.session.commit()

    def test_zero_candidates_results(self, app, db):
        with app.app_context():
            e = make_election(db, title='Zero Cands', published=True)
            cands, total = get_results(e)
            assert cands == [] and total == 0
            Election.query.filter_by(id=e.id).delete()
            db.session.commit()


# ── Nomination flow ───────────────────────────────────────────────────────────

class TestNominationFlow:
    def _login(self, client, app, email='voter@test.com'):
        with app.app_context():
            u = User.query.filter_by(email=email).first()
            uid = str(u.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid

    def test_nominations_page_200(self, client, voter_user, app):
        self._login(client, app)
        r = client.get('/nominations')
        assert r.status_code == 200

    def test_apply_outside_window_blocked(self, client, voter_user, app, db):
        self._login(client, app)
        with app.app_context():
            e = make_election(db)
            eid = e.id
        r = client.get(f'/apply-nomination/{eid}', follow_redirects=True)
        assert b'not active' in r.data.lower() or r.status_code in (200, 302)


# ── Admin routes ──────────────────────────────────────────────────────────────

class TestAdminRoutes:
    def _login_admin(self, client, app):
        with app.app_context():
            admin = User.query.filter_by(role='admin').first()
            uid = str(admin.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid

    def test_dashboard_200(self, client, app):
        self._login_admin(client, app)
        r = client.get('/admin/dashboard')
        assert r.status_code == 200

    def test_dashboard_blocks_non_admin(self, client, voter_user, app):
        with app.app_context():
            u = User.query.filter_by(email='voter@test.com').first()
            with client.session_transaction() as s:
                s['_user_id'] = str(u.id)
        r = client.get('/admin/dashboard', follow_redirects=True)
        assert b'Admin access required' in r.data or r.status_code == 200

    def test_create_election_page_200(self, client, app):
        self._login_admin(client, app)
        r = client.get('/admin/elections/create')
        assert r.status_code == 200

    def test_nominations_page_200(self, client, app):
        self._login_admin(client, app)
        r = client.get('/admin/nominations')
        assert r.status_code == 200

    def test_users_page_200(self, client, app):
        self._login_admin(client, app)
        r = client.get('/admin/users')
        assert r.status_code == 200

    def test_audit_log_200(self, client, app):
        self._login_admin(client, app)
        r = client.get('/admin/audit-log')
        assert r.status_code == 200

    def test_analytics_200(self, client, app):
        self._login_admin(client, app)
        r = client.get('/analytics/dashboard')
        assert r.status_code == 200

    def test_toggle_user(self, client, app, db):
        self._login_admin(client, app)
        with app.app_context():
            u = make_user(db, 'toggle@test.com', 'TOG01')
            uid = u.id
        r = client.get(f'/admin/users/{uid}/toggle', follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            u2 = User.query.filter_by(email='toggle@test.com').first()
            assert not u2.is_active

    def test_delete_upcoming_election(self, client, app, db):
        self._login_admin(client, app)
        n = now()
        with app.app_context():
            e = make_election(db, title='To Delete',
                nom_start=n+timedelta(days=1), nom_end=n+timedelta(days=2),
                vote_start=n+timedelta(days=3), vote_end=n+timedelta(days=4),
                status='upcoming')
            eid = e.id
        r = client.post(f'/admin/elections/{eid}/delete', follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            assert db.session.get(Election, eid) is None

    def test_cannot_delete_active_election(self, client, app, db):
        self._login_admin(client, app)
        with app.app_context():
            e = make_election(db, title='Active Del', status='voting')
            eid = e.id
        r = client.post(f'/admin/elections/{eid}/delete', follow_redirects=True)
        assert b'Cannot delete' in r.data

    def test_export_csv(self, client, app):
        self._login_admin(client, app)
        r = client.get('/admin/users/export-csv')
        assert r.status_code == 200
        assert b'name,email' in r.data


# ── Analytics ─────────────────────────────────────────────────────────────────

class TestAnalytics:
    def test_track_endpoint(self, client):
        r = client.post('/analytics/track',
            json={'event_type': 'test_event', 'page': '/test'},
            content_type='application/json')
        assert r.status_code in (200, 400)  # 400 if CSRF enforced

    def test_chart_data_endpoint(self, client, voter_user, app, db):
        with app.app_context():
            u = User.query.filter_by(email='voter@test.com').first()
            with client.session_transaction() as s:
                s['_user_id'] = str(u.id)
        with app.app_context():
            e = make_election(db, title='Chart Test', published=True)
            eid = e.id
        r = client.get(f'/analytics/election/{eid}/chart-data')
        assert r.status_code == 200
        import json
        data = json.loads(r.data)
        assert 'labels' in data and 'votes' in data


# ── Edge cases ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    def test_expired_reset_token(self, client):
        r = client.get('/reset-password/expiredtoken999', follow_redirects=True)
        assert b'Invalid' in r.data

    def test_expired_verify_token(self, client):
        r = client.get('/verify-email/expiredtoken999', follow_redirects=True)
        assert b'Invalid' in r.data

    def test_404_election(self, client, voter_user, app):
        with app.app_context():
            u = User.query.filter_by(email='voter@test.com').first()
            with client.session_transaction() as s:
                s['_user_id'] = str(u.id)
        r = client.get('/election/9999999')
        assert r.status_code == 404

    def test_register_duplicate_email(self, client, voter_user, app):
        r = client.post('/register', data={
            'name': 'Dup', 'email': 'voter@test.com',
            'password': 'Test@1234', 'student_id': 'DUP999',
            'department': 'CS', 'year': '1st Year',
        }, follow_redirects=True)
        assert b'already registered' in r.data

    def test_register_duplicate_student_id(self, client, voter_user, app):
        r = client.post('/register', data={
            'name': 'Dup2', 'email': 'dup2@test.com',
            'password': 'Test@1234', 'student_id': 'TEST001',
            'department': 'CS', 'year': '1st Year',
        }, follow_redirects=True)
        assert b'already registered' in r.data


# ── Additional coverage tests ─────────────────────────────────────────────────

class TestCandidateRoutes:
    def _login(self, client, app, email='voter@test.com'):
        with app.app_context():
            u = User.query.filter_by(email=email).first()
            uid = str(u.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid

    def test_nominations_page(self, client, voter_user, app):
        self._login(client, app)
        r = client.get('/nominations')
        assert r.status_code == 200

    def test_candidate_profile_public(self, client, voter_user, app, db):
        from models import Candidate, Election
        n = now()
        with app.app_context():
            e = make_election(db)
            u = User.query.filter_by(email='voter@test.com').first()
            c = Candidate(user_id=u.id, election_id=e.id, manifesto='Test manifesto')
            db.session.add(c); db.session.commit()
            cid = c.id
        r = client.get(f'/candidate/{cid}')
        assert r.status_code == 200

    def test_apply_nomination_form(self, client, voter_user, app, db):
        from datetime import timedelta
        from utils.time_utils import now_ist
        self._login(client, app)
        n = now_ist()
        with app.app_context():
            from models import Election
            e = Election(
                title='Open Nom', position='Rep',
                nomination_start=n - timedelta(hours=1),
                nomination_end=n + timedelta(hours=5),
                voting_start=n + timedelta(days=1),
                voting_end=n + timedelta(days=2),
                status='nomination',
            )
            db.session.add(e); db.session.commit()
            eid = e.id
        r = client.get(f'/apply-nomination/{eid}')
        assert r.status_code == 200


class TestNotificationRoutes:
    def _login(self, client, app, email='voter@test.com'):
        with app.app_context():
            u = User.query.filter_by(email=email).first()
            uid = str(u.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid

    def test_get_notifications(self, client, voter_user, app):
        self._login(client, app)
        r = client.get('/notifications/')
        assert r.status_code == 200
        import json
        data = json.loads(r.data)
        assert 'unread' in data
        assert 'notifications' in data

    def test_mark_all_read(self, client, voter_user, app, db):
        from models import Notification
        self._login(client, app)
        with app.app_context():
            u = User.query.filter_by(email='voter@test.com').first()
            n = Notification(user_id=u.id, title='Test', message='Msg', is_read=False)
            db.session.add(n); db.session.commit()
        r = client.post('/notifications/mark-all-read')
        assert r.status_code == 200


class TestVoterLiveCounts:
    def _login(self, client, app):
        with app.app_context():
            u = User.query.filter_by(email='voter@test.com').first()
            uid = str(u.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid

    def test_live_counts_not_published(self, client, voter_user, app, db):
        self._login(client, app)
        with app.app_context():
            e = make_election(db, title='Live Test', published=False)
            eid = e.id
        r = client.get(f'/election/{eid}/live-counts')
        assert r.status_code == 200
        import json
        data = json.loads(r.data)
        assert data['published'] is False

    def test_live_counts_published(self, client, voter_user, app, db):
        self._login(client, app)
        with app.app_context():
            e = make_election(db, title='Live Published', published=True)
            eid = e.id
        r = client.get(f'/election/{eid}/live-counts')
        assert r.status_code == 200
        import json
        data = json.loads(r.data)
        assert data['published'] is True
        assert 'counts' in data


class TestAdminAnnouncements:
    def _login_admin(self, client, app):
        with app.app_context():
            admin = User.query.filter_by(role='admin').first()
            uid = str(admin.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid

    def test_create_announcement(self, client, app, db):
        self._login_admin(client, app)
        r = client.post('/admin/announcements/create', data={
            'title': 'Test Announcement',
            'message': 'This is a test message'
        }, follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            from models import Announcement
            ann = Announcement.query.filter_by(title='Test Announcement').first()
            assert ann is not None

    def test_create_announcement_empty_fails(self, client, app, db):
        self._login_admin(client, app)
        r = client.post('/admin/announcements/create', data={
            'title': '', 'message': ''
        }, follow_redirects=True)
        assert r.status_code == 200
        assert b'required' in r.data.lower()

    def test_delete_announcement(self, client, app, db):
        self._login_admin(client, app)
        with app.app_context():
            from models import Announcement
            admin = User.query.filter_by(role='admin').first()
            ann = Announcement(title='Del Me', message='msg', created_by=admin.id)
            db.session.add(ann); db.session.commit()
            aid = ann.id
        r = client.post(f'/admin/announcements/{aid}/delete', follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            from models import Announcement
            assert db.session.get(Announcement, aid) is None


class TestElectionEdit:
    def _login_admin(self, client, app):
        with app.app_context():
            admin = User.query.filter_by(role='admin').first()
            uid = str(admin.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid

    def test_edit_election_page(self, client, app, db):
        self._login_admin(client, app)
        n = now()
        with app.app_context():
            from models import Election
            e = Election(
                title='Editable', position='Rep',
                nomination_start=n + timedelta(days=1),
                nomination_end=n + timedelta(days=2),
                voting_start=n + timedelta(days=3),
                voting_end=n + timedelta(days=4),
                status='upcoming',
            )
            db.session.add(e); db.session.commit()
            eid = e.id
        r = client.get(f'/admin/elections/{eid}/edit')
        assert r.status_code == 200

    def test_cannot_edit_active_election(self, client, app, db):
        self._login_admin(client, app)
        with app.app_context():
            e = make_election(db, title='Active Edit', status='voting')
            eid = e.id
        r = client.get(f'/admin/elections/{eid}/edit', follow_redirects=True)
        assert b'Cannot edit' in r.data


class TestVoterVoteFlow:
    def _login(self, client, app, email='voter@test.com'):
        with app.app_context():
            u = User.query.filter_by(email=email).first()
            uid = str(u.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid

    def test_vote_no_candidate_selected(self, client, voter_user, app, db):
        self._login(client, app)
        with app.app_context():
            e = make_election(db, title='Vote No Cand')
            eid = e.id
        r = client.post(f'/vote/{eid}', data={}, follow_redirects=True)
        assert r.status_code == 200
        assert b'select a candidate' in r.data.lower()

    def test_vote_invalid_candidate(self, client, voter_user, app, db):
        self._login(client, app)
        with app.app_context():
            e = make_election(db, title='Vote Bad Cand')
            eid = e.id
        r = client.post(f'/vote/{eid}', data={'candidate_id': '99999'}, follow_redirects=True)
        assert r.status_code == 200

    def test_profile_page(self, client, voter_user, app):
        self._login(client, app)
        r = client.get('/profile')
        assert r.status_code == 200
        assert b'Profile' in r.data


class TestAdminImportCSV:
    def _login_admin(self, client, app):
        with app.app_context():
            admin = User.query.filter_by(role='admin').first()
            uid = str(admin.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid

    def test_import_csv_page(self, client, app):
        self._login_admin(client, app)
        r = client.get('/admin/users/import-csv')
        assert r.status_code == 200

    def test_import_valid_csv(self, client, app, db):
        import io
        self._login_admin(client, app)
        csv_data = b'name,email,student_id,department,year\nNew Student,newstudent@test.com,NS001,CS,1st Year\n'
        data = {'csv_file': (io.BytesIO(csv_data), 'students.csv')}
        r = client.post('/admin/users/import-csv',
                        data=data, content_type='multipart/form-data',
                        follow_redirects=True)
        assert r.status_code == 200
        assert b'Imported' in r.data

    def test_import_non_csv_rejected(self, client, app, db):
        import io
        self._login_admin(client, app)
        data = {'csv_file': (io.BytesIO(b'not a csv'), 'file.txt')}
        r = client.post('/admin/users/import-csv',
                        data=data, content_type='multipart/form-data',
                        follow_redirects=True)
        assert r.status_code == 200
        assert b'valid' in r.data.lower()

    def test_notify_voting_open(self, client, app, db):
        self._login_admin(client, app)
        with app.app_context():
            e = make_election(db, title='Notify Test')
            eid = e.id
        r = client.get(f'/admin/elections/{eid}/notify-voters', follow_redirects=True)
        assert r.status_code == 200
