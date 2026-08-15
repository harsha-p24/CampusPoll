from flask import Blueprint, render_template, redirect, url_for, request, flash, session
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from services.user_service import hash_password, verify_password, needs_rehash
from models import User, LoginAttempt, Notification
from app import db, limiter
from services.audit_service import log_event, log_audit, notify_user
from services.user_service import validate_registration, sanitize, validate_email
from datetime import timedelta
from utils.time_utils import now_ist
import secrets, os

auth = Blueprint('auth', __name__)

MAX_ATTEMPTS   = int(os.getenv('LOGIN_MAX_ATTEMPTS', 5))
BLOCK_MINUTES  = int(os.getenv('LOGIN_BLOCK_MINUTES', 15))


def _is_ip_blocked(ip):
    cutoff = now_ist() - timedelta(minutes=BLOCK_MINUTES)
    fails  = LoginAttempt.query.filter(
        LoginAttempt.ip_address == ip,
        LoginAttempt.success == False,
        LoginAttempt.attempted_at >= cutoff
    ).count()
    return fails >= MAX_ATTEMPTS


def _record_attempt(email, ip, success):
    db.session.add(LoginAttempt(email=email, ip_address=ip, success=success))
    db.session.commit()


def _remaining_attempts(ip):
    cutoff = now_ist() - timedelta(minutes=BLOCK_MINUTES)
    fails  = LoginAttempt.query.filter(
        LoginAttempt.ip_address == ip,
        LoginAttempt.success == False,
        LoginAttempt.attempted_at >= cutoff
    ).count()
    return max(0, MAX_ATTEMPTS - fails)


# ── Home ─────────────────────────────────────────────────────────────────────


@auth.route('/robots.txt')
def robots():
    from flask import send_from_directory, current_app
    return send_from_directory(current_app.static_folder, 'robots.txt')

@auth.route('/')
def index():
    log_event('page_view', 'home')
    from models import Announcement
    announcements = Announcement.query.filter_by(is_active=True)\
        .order_by(Announcement.created_at.desc()).limit(3).all()
    return render_template('index.html', announcements=announcements)


# ── Register ──────────────────────────────────────────────────────────────────

@auth.route('/register', methods=['GET', 'POST'])
@limiter.limit('10 per hour')
def register():
    if current_user.is_authenticated:
        return redirect(url_for('voter.dashboard'))

    if request.method == 'POST':
        # Honeypot: bots fill hidden field, humans leave it blank
        if request.form.get('website', ''):
            return redirect(url_for('auth.register'))
        log_event('form_submission', 'register')
        errors = validate_registration(request.form)

        email      = sanitize(request.form.get('email', '').strip().lower(), 120)
        student_id = sanitize(request.form.get('student_id', '').strip(), 20)

        if not errors:
            if User.query.filter_by(email=email).first():
                errors.append('Email already registered.')
            if User.query.filter_by(student_id=student_id).first():
                errors.append('Student ID already registered.')

        if errors:
            for e in errors:
                flash(e, 'error')
            return render_template('register.html', form=request.form)

        verify_token = secrets.token_urlsafe(32)
        user = User(
            name=sanitize(request.form.get('name'), 100),
            email=email,
            password=generate_password_hash(request.form.get('password')),
            student_id=student_id,
            department=sanitize(request.form.get('department'), 100),
            year=sanitize(request.form.get('year'), 20),
            role='voter',
            verify_token=verify_token,
            is_verified=False,
        )
        db.session.add(user)
        db.session.commit()

        if not os.getenv('MAIL_USERNAME'):
            # Mail not configured — auto-verify for local dev
            user.is_verified = True
            user.verify_token = None
            db.session.commit()
            flash('Registration successful! Please login.', 'success')
        else:
            try:
                from tasks.email_tasks import send_verification_email as send_ver
                send_ver.delay(user.id)
            except Exception:
                pass  # Celery not running
            flash('Registration successful! Check your email to verify your account.', 'success')

        log_audit('user_registered', f'email:{email}', user.id)
        return redirect(url_for('auth.login'))

    log_event('page_view', 'register')
    return render_template('register.html', form={})


# ── Email verification ────────────────────────────────────────────────────────

@auth.route('/verify-email/<token>')
def verify_email(token):
    user = User.query.filter_by(verify_token=token).first()
    if not user:
        flash('Invalid or expired verification link.', 'error')
        return redirect(url_for('auth.login'))
    user.is_verified  = True
    user.verify_token = None
    db.session.commit()
    notify_user(user.id, 'Welcome to CampusPoll!',
                'Your account is verified. You can now vote in elections.', 'success')
    log_audit('email_verified', f'email:{user.email}', user.id)
    flash('Email verified! You can now login.', 'success')
    return redirect(url_for('auth.login'))


@auth.route('/resend-verification', methods=['POST'])
@limiter.limit("3 per hour")
def resend_verification():
    email = sanitize(request.form.get('email', '').strip().lower(), 120)
    user  = User.query.filter_by(email=email, is_verified=False).first()
    if user:
        user.verify_token = secrets.token_urlsafe(32)
        db.session.commit()
        try:
            from utils.email_utils import send_verification_email
            send_verification_email(user)
        except Exception:
            pass
    flash('If that email exists and is unverified, a link has been sent.', 'info')
    return redirect(url_for('auth.login'))


# ── Login ─────────────────────────────────────────────────────────────────────

@auth.route('/login', methods=['GET', 'POST'])
@limiter.limit("30 per minute")
def login():
    if current_user.is_authenticated:
        return redirect(url_for('voter.dashboard'))

    if request.method == 'POST':
        email    = sanitize(request.form.get('email', '').strip().lower(), 120)
        password = request.form.get('password', '')
        ip       = request.remote_addr

        if _is_ip_blocked(ip):
            flash(f'Too many failed attempts. Try again in {BLOCK_MINUTES} minutes.', 'error')
            return render_template('login.html')

        user = User.query.filter_by(email=email).first()

        if not user or not verify_password(user.password, password):
            _record_attempt(email, ip, False)
            log_event('login_failed', 'login', f'email:{email}')
            remaining = _remaining_attempts(ip)
            flash(f'Invalid email or password. {remaining} attempts remaining before temporary block.', 'error')
            return render_template('login.html')

        if not user.is_active:
            flash('Your account has been deactivated. Contact admin.', 'error')
            return render_template('login.html')

        if not user.is_verified:
            flash('Please verify your email before logging in.', 'error')
            return render_template('login.html', show_resend=True, resend_email=email)

        # 2FA check
        if user.totp_enabled:
            session['pre_2fa_user_id'] = user.id
            return redirect(url_for('auth.two_factor'))

        # Rehash legacy passwords on login
        if needs_rehash(user.password):
            user.password = hash_password(password)
            db.session.commit()
        _complete_login(user, ip)
        return redirect(url_for('admin.dashboard') if user.role == 'admin' else url_for('voter.dashboard'))

    log_event('page_view', 'login')
    return render_template('login.html')


def _complete_login(user, ip):
    login_user(user)
    session.permanent = True
    user.last_login   = now_ist()
    db.session.commit()
    _record_attempt(user.email, ip, True)
    log_audit('user_login', f'email:{user.email}', user.id)
    log_event('login_success', 'login', user_id=user.id)


# ── 2FA ──────────────────────────────────────────────────────────────────────

@auth.route('/2fa', methods=['GET', 'POST'])
@limiter.limit('10 per hour')
def two_factor():
    user_id = session.get('pre_2fa_user_id')
    if not user_id:
        return redirect(url_for('auth.login'))
    user = User.query.get_or_404(user_id)

    if request.method == 'POST':
        token = request.form.get('token', '').strip()
        from services.user_service import verify_totp
        if verify_totp(user, token):
            session.pop('pre_2fa_user_id', None)
            _complete_login(user, request.remote_addr)
            return redirect(url_for('admin.dashboard') if user.role == 'admin' else url_for('voter.dashboard'))
        flash('Invalid 2FA code. Please try again.', 'error')

    return render_template('two_factor.html')


@auth.route('/setup-2fa', methods=['GET', 'POST'])
@login_required
@limiter.limit('20 per hour')
def setup_2fa():
    from services.user_service import generate_totp_secret, get_totp_qr_b64, verify_totp
    if request.method == 'POST':
        token = request.form.get('token', '').strip()
        if verify_totp(current_user, token):
            current_user.totp_enabled = True
            db.session.commit()
            log_audit('2fa_enabled', user_id=current_user.id)
            flash('Two-factor authentication enabled!', 'success')
            return redirect(url_for('voter.profile'))
        flash('Invalid code. Please try again.', 'error')

    if not current_user.totp_secret:
        current_user.totp_secret = generate_totp_secret()
        db.session.commit()

    qr = get_totp_qr_b64(current_user)
    return render_template('setup_2fa.html', qr=qr, secret=current_user.totp_secret)


@auth.route('/disable-2fa', methods=['POST'])
@login_required
def disable_2fa():
    current_user.totp_enabled = False
    current_user.totp_secret  = None
    db.session.commit()
    log_audit('2fa_disabled', user_id=current_user.id)
    flash('Two-factor authentication disabled.', 'info')
    return redirect(url_for('voter.profile'))


# ── Forgot / Reset password ───────────────────────────────────────────────────

@auth.route('/forgot-password', methods=['GET', 'POST'])
@limiter.limit("5 per hour")
def forgot_password():
    if request.method == 'POST':
        email = sanitize(request.form.get('email', '').strip().lower(), 120)
        user  = User.query.filter_by(email=email).first()
        if user:
            token        = secrets.token_urlsafe(32)
            user.reset_token = token
            db.session.commit()
            reset_link = url_for('auth.reset_password', token=token, _external=True)
            try:
                from tasks.email_tasks import send_password_reset_email as send_pr
                send_pr.delay(user.id, reset_link)
            except Exception:
                if not os.getenv('MAIL_USERNAME'):
                    flash(f'Reset link (mail not configured): {reset_link}', 'info')
                    return redirect(url_for('auth.login'))
        flash('If that email is registered, a reset link has been sent.', 'info')
        return redirect(url_for('auth.login'))

    log_event('page_view', 'forgot_password')
    return render_template('forgot_password.html')


@auth.route('/reset-password/<token>', methods=['GET', 'POST'])
def reset_password(token):
    user = User.query.filter_by(reset_token=token).first()
    if not user:
        flash('Invalid or expired reset link.', 'error')
        return redirect(url_for('auth.login'))

    if request.method == 'POST':
        from services.user_service import validate_password
        pwd = request.form.get('password', '')
        ok, msg = validate_password(pwd)
        if not ok:
            flash(msg, 'error')
            return render_template('reset_password.html', token=token)
        user.password     = hash_password(pwd)
        user.reset_token  = None
        user.session_token = secrets.token_hex(16)  # invalidate existing sessions
        db.session.commit()
        log_audit('password_reset', f'email:{user.email}', user.id)
        flash('Password reset successful! Please login.', 'success')
        return redirect(url_for('auth.login'))

    return render_template('reset_password.html', token=token)


# ── Logout ────────────────────────────────────────────────────────────────────

@auth.route('/logout')
@login_required
def logout():
    log_audit('user_logout', f'email:{current_user.email}')
    logout_user()
    session.clear()
    flash('Logged out successfully.', 'success')
    return redirect(url_for('auth.index'))
