"""Security, file upload, 2FA, health endpoint, robots.txt tests."""
import pytest, io, os
from models import User
from werkzeug.security import generate_password_hash
from services.user_service import (
    validate_file_upload, hash_password, verify_password,
    needs_rehash, get_totp_qr_b64, generate_totp_secret, verify_totp
)


# ── Password hashing (Argon2) ─────────────────────────────────────────────────
class TestArgon2:
    def test_hash_and_verify(self):
        h = hash_password('Secure@123')
        assert verify_password(h, 'Secure@123')

    def test_wrong_password_fails(self):
        h = hash_password('Secure@123')
        assert not verify_password(h, 'Wrong@123')

    def test_legacy_werkzeug_hash_verified(self):
        """Werkzeug hashes from old versions must still work."""
        from werkzeug.security import generate_password_hash as wph
        legacy = wph('Secure@123')
        assert verify_password(legacy, 'Secure@123')

    def test_argon2_needs_no_rehash(self):
        h = hash_password('Secure@123')
        assert not needs_rehash(h)

    def test_werkzeug_hash_needs_rehash(self):
        from werkzeug.security import generate_password_hash as wph
        legacy = wph('Secure@123')
        assert needs_rehash(legacy)

    def test_different_hashes_for_same_password(self):
        """Argon2 uses random salt — same password gives different hash."""
        h1 = hash_password('Same@123')
        h2 = hash_password('Same@123')
        assert h1 != h2
        assert verify_password(h1, 'Same@123')
        assert verify_password(h2, 'Same@123')


# ── File upload MIME validation ───────────────────────────────────────────────
class TestFileUpload:
    def _make_file(self, content: bytes, filename: str):
        from werkzeug.datastructures import FileStorage
        return FileStorage(stream=io.BytesIO(content), filename=filename)

    def test_valid_jpeg(self):
        file = self._make_file(b'\xff\xd8\xff\xe0' + b'\x00' * 100, 'photo.jpg')
        ok, err = validate_file_upload(file)
        assert ok and err is None

    def test_valid_png(self):
        file = self._make_file(b'\x89PNG\r\n\x1a\n' + b'\x00' * 100, 'photo.png')
        ok, err = validate_file_upload(file)
        assert ok and err is None

    def test_invalid_extension(self):
        file = self._make_file(b'\xff\xd8\xff', 'file.php')
        ok, err = validate_file_upload(file)
        assert not ok and 'not allowed' in err

    def test_mismatched_mime_content(self):
        """PNG magic bytes but .jpg extension — should pass (MIME matches)."""
        file = self._make_file(b'\x89PNG\r\n\x1a\n' + b'\x00'*50, 'fake.jpg')
        ok, _ = validate_file_upload(file)
        assert ok  # MIME check passes; extension is just advisory

    def test_fake_image_content(self):
        """PHP script disguised as .jpg."""
        file = self._make_file(b'<?php echo "hack"; ?>', 'evil.jpg')
        ok, err = validate_file_upload(file)
        assert not ok

    def test_empty_file(self):
        file = self._make_file(b'', 'empty.jpg')
        ok, err = validate_file_upload(file)
        assert not ok

    def test_no_file(self):
        ok, err = validate_file_upload(None)
        assert not ok


# ── 2FA ───────────────────────────────────────────────────────────────────────
class TestTwoFactor:
    def _make_user_with_totp(self, db, app):
        secret = generate_totp_secret()
        u = User(
            name='2FA User', email='twofa@test.com',
            password=hash_password('Test@1234'),
            student_id='2FA001', department='CS', year='1st Year',
            role='voter', is_active=True, is_verified=True,
            totp_secret=secret, totp_enabled=True,
        )
        db.session.add(u)
        db.session.commit()
        return u

    def test_valid_totp_code(self, app, db):
        import pyotp
        u = self._make_user_with_totp(db, app)
        totp = pyotp.TOTP(u.totp_secret)
        assert verify_totp(u, totp.now())

    def test_invalid_totp_code(self, app, db):
        u = self._make_user_with_totp(db, app)
        assert not verify_totp(u, '000000')

    def test_qr_code_generated(self, app, db):
        u = self._make_user_with_totp(db, app)
        qr = get_totp_qr_b64(u)
        assert len(qr) > 100  # base64 PNG

    def test_setup_2fa_page(self, client, voter_user, app):
        with app.app_context():
            u = User.query.filter_by(email='voter@test.com').first()
            uid = str(u.id)
        with client.session_transaction() as s:
            s['_user_id'] = uid
        r = client.get('/setup-2fa')
        assert r.status_code == 200

    def test_disable_2fa(self, client, app, db):
        u = self._make_user_with_totp(db, app)
        with client.session_transaction() as s:
            s['_user_id'] = str(u.id)
        r = client.post('/disable-2fa', follow_redirects=True)
        assert r.status_code == 200
        with app.app_context():
            u2 = User.query.filter_by(email='twofa@test.com').first()
            if u2:
                assert not u2.totp_enabled


# ── Security headers ──────────────────────────────────────────────────────────
class TestSecurityHeaders:
    def test_csp_header_present(self, client):
        r = client.get('/')
        assert 'Content-Security-Policy' in r.headers
        assert 'default-src' in r.headers['Content-Security-Policy']

    def test_xframe_options(self, client):
        r = client.get('/')
        assert r.headers.get('X-Frame-Options') == 'DENY'

    def test_x_content_type(self, client):
        r = client.get('/')
        assert r.headers.get('X-Content-Type-Options') == 'nosniff'

    def test_request_id_header(self, client):
        r = client.get('/')
        assert 'X-Request-ID' in r.headers

    def test_custom_request_id_echoed(self, client):
        r = client.get('/', headers={'X-Request-ID': 'test-req-123'})
        assert r.headers.get('X-Request-ID') == 'test-req-123'


# ── Health endpoint ───────────────────────────────────────────────────────────
class TestHealthEndpoint:
    def test_health_responds(self, client):
        r = client.get('/health')
        assert r.status_code in (200, 503)  # 503 if Redis not running

    def test_health_json(self, client):
        import json
        r = client.get('/health')
        data = json.loads(r.data)
        assert data['status'] in ('ok', 'degraded')
        assert 'checks' in data
        assert 'database' in data['checks']

    def test_health_db_ok(self, client):
        import json
        r = client.get('/health')
        data = json.loads(r.data)
        assert data['checks']['database']['status'] == 'ok'


# ── Robots.txt ────────────────────────────────────────────────────────────────
class TestRobotsTxt:
    def test_robots_txt_accessible(self, client):
        r = client.get('/robots.txt')
        assert r.status_code == 200

    def test_robots_blocks_admin(self, client):
        r = client.get('/robots.txt')
        assert b'/admin/' in r.data

    def test_robots_blocks_analytics(self, client):
        r = client.get('/robots.txt')
        assert b'/analytics/' in r.data
