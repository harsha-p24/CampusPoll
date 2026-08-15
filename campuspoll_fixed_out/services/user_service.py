"""User-related business logic, validation, password hashing, 2FA."""
import re, bleach, os
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, InvalidHashError

_ph = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=2)

ALLOWED_MIME_TYPES = {'image/jpeg', 'image/png', 'image/gif', 'image/webp'}
ALLOWED_EXTENSIONS = {'jpg', 'jpeg', 'png', 'gif', 'webp'}

EMAIL_RE      = re.compile(r'^[^@\s]+@[^@\s]+\.[^@\s]+$')
STUDENT_ID_RE = re.compile(r'^[A-Za-z0-9]{4,20}$')


# ── Password hashing (Argon2) ─────────────────────────────────────────────────

def hash_password(password: str) -> str:
    return _ph.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Returns True if password matches. Handles both Argon2 and legacy Werkzeug hashes."""
    # Try Argon2 first
    try:
        return _ph.verify(stored_hash, password)
    except (VerifyMismatchError, InvalidHashError):
        pass
    # Fallback: legacy Werkzeug bcrypt hash (migration path)
    try:
        from werkzeug.security import check_password_hash
        return check_password_hash(stored_hash, password)
    except Exception:
        return False


def needs_rehash(stored_hash: str) -> bool:
    """True if hash should be upgraded to current Argon2 parameters."""
    try:
        return _ph.check_needs_rehash(stored_hash)
    except Exception:
        return True  # Legacy hash — rehash on next login


# ── Sanitisation ─────────────────────────────────────────────────────────────

def sanitize(text, max_len=500):
    if not text:
        return ''
    return bleach.clean(str(text), tags=[], strip=True).strip()[:max_len]


# ── File validation ───────────────────────────────────────────────────────────

def validate_file_upload(file_storage):
    """
    Validate an uploaded file is a real image.
    Returns (ok: bool, error: str | None)
    """
    if not file_storage or not file_storage.filename:
        return False, 'No file selected.'

    ext = file_storage.filename.rsplit('.', 1)[-1].lower() if '.' in file_storage.filename else ''
    if ext not in ALLOWED_EXTENSIONS:
        return False, f'File type not allowed. Use: {", ".join(ALLOWED_EXTENSIONS)}'

    # Read first 12 bytes to check magic bytes (MIME sniffing)
    header = file_storage.stream.read(12)
    file_storage.stream.seek(0)

    mime = _sniff_mime(header)
    if mime not in ALLOWED_MIME_TYPES:
        return False, 'File content does not match an allowed image type.'

    return True, None


def _sniff_mime(header: bytes) -> str:
    if header[:3] == b'\xff\xd8\xff':              return 'image/jpeg'
    if header[:8] == b'\x89PNG\r\n\x1a\n':         return 'image/png'
    if header[:6] in (b'GIF87a', b'GIF89a'):       return 'image/gif'
    if header[:4] in (b'RIFF', b'WEBP'):            return 'image/webp'
    if b'WEBP' in header:                           return 'image/webp'
    return 'application/octet-stream'


# ── Validation ────────────────────────────────────────────────────────────────

def validate_password(password):
    if len(password) < 8:
        return False, 'Password must be at least 8 characters.'
    if not re.search(r'[A-Z]', password):
        return False, 'Password must contain at least one uppercase letter.'
    if not re.search(r'[a-z]', password):
        return False, 'Password must contain at least one lowercase letter.'
    if not re.search(r'\d', password):
        return False, 'Password must contain at least one number.'
    if not re.search(r'[@$!%*?&_\-]', password):
        return False, 'Password must contain at least one special character (@$!%*?&_-).'
    return True, None


def validate_email(email):
    if not email or not EMAIL_RE.match(email):
        return False, 'Invalid email address.'
    return True, None


def validate_student_id(student_id):
    if not student_id or not STUDENT_ID_RE.match(student_id):
        return False, 'Student ID must be 4–20 alphanumeric characters.'
    return True, None


def validate_registration(form):
    errors = []
    name = sanitize(form.get('name', ''), 100)
    if len(name) < 2:
        errors.append('Name must be at least 2 characters.')
    ok, msg = validate_email(form.get('email', '').strip().lower())
    if not ok: errors.append(msg)
    ok, msg = validate_student_id(form.get('student_id', '').strip())
    if not ok: errors.append(msg)
    ok, msg = validate_password(form.get('password', ''))
    if not ok: errors.append(msg)
    if not form.get('department'):
        errors.append('Please select a department.')
    if not form.get('year'):
        errors.append('Please select a year.')
    return errors


# ── 2FA ───────────────────────────────────────────────────────────────────────

def generate_totp_secret():
    import pyotp
    return pyotp.random_base32()

def get_totp_uri(user):
    import pyotp
    return pyotp.TOTP(user.totp_secret).provisioning_uri(
        name=user.email, issuer_name='CampusPoll')

def verify_totp(user, token):
    import pyotp
    if not user.totp_secret: return False
    return pyotp.TOTP(user.totp_secret).verify(token, valid_window=1)

def get_totp_qr_b64(user):
    import qrcode, io, base64
    img = qrcode.make(get_totp_uri(user))
    buf = io.BytesIO()
    img.save(buf, format='PNG')
    return base64.b64encode(buf.getvalue()).decode()
