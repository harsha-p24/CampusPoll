import os, secrets, uuid
from flask_socketio import SocketIO

# async_mode='threading' avoids the eventlet/gevent monkey-patching requirement
# that causes AttributeError: 'NoneType'.eio when running in Flask debug mode.
socketio = SocketIO()
from flask import Flask, g, request, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_wtf.csrf import CSRFProtect
from flask_mail import Mail
from flask_migrate import Migrate
from datetime import timedelta
from dotenv import load_dotenv
from services.secrets_service import get_secret

load_dotenv()

db        = SQLAlchemy()
login_manager = LoginManager()
limiter   = Limiter(key_func=get_remote_address, default_limits=[])
csrf      = CSRFProtect()
mail      = Mail()
migrate   = Migrate()


# ── Logging ──────────────────────────────────────────────────────────────────
def configure_logging(app):
    import logging as _log, logging.handlers as _lh, json
    level = _log.DEBUG if app.debug else _log.INFO

    def _safe_rid():
        try:
            return g.request_id
        except Exception:
            return '-'

    class JsonFormatter(_log.Formatter):
        def format(self, record):
            return json.dumps({
                'time':       self.formatTime(record),
                'level':      record.levelname,
                'logger':     record.name,
                'message':    record.getMessage(),
                'request_id': _safe_rid(),
            })

    handler = _log.StreamHandler()
    handler.setFormatter(JsonFormatter())
    _log.basicConfig(level=level, handlers=[handler])

    if not app.debug:
        os.makedirs('logs', exist_ok=True)
        fh = _lh.RotatingFileHandler(
            'logs/campuspoll.log', maxBytes=5*1024*1024, backupCount=5)
        fh.setLevel(_log.INFO)
        fh.setFormatter(JsonFormatter())
        app.logger.addHandler(fh)
        _log.getLogger().addHandler(fh)


def _require_env_or_die(key):
    val = os.getenv(key)
    if not val:
        raise RuntimeError(
            f"\n{'='*60}\nMISSING REQUIRED ENV VAR: {key}\n"
            f"Copy .env.example → .env and fill all values.\n{'='*60}\n"
        )
    return val


def create_app(testing=False):
    app = Flask(__name__)
    configure_logging(app)

    # ── Request ID middleware ─────────────────────────────────────
    @app.before_request
    def set_request_id():
        g.request_id = request.headers.get('X-Request-ID', str(uuid.uuid4())[:8])

    @app.after_request
    def add_request_id(response):
        response.headers['X-Request-ID'] = getattr(g, 'request_id', '-')
        return response

    # ── Security headers ─────────────────────────────────────────
    @app.after_request
    def add_security_headers(response):
        response.headers['X-Frame-Options']        = 'DENY'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-XSS-Protection']       = '1; mode=block'
        response.headers['Referrer-Policy']        = 'strict-origin-when-cross-origin'
        response.headers['Permissions-Policy']     = 'geolocation=(), microphone=()'
        if not app.debug:
            response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        # Content Security Policy
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://cdn.socket.io; "
            "style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "connect-src 'self' wss: ws:; "
            "frame-ancestors 'none';"
        )
        response.headers['Content-Security-Policy'] = csp
        return response

    # ── Secret key ───────────────────────────────────────────────
    if testing:
        app.config['SECRET_KEY'] = 'test-secret-key'
    else:
        secret = os.getenv('SECRET_KEY', '')
        _placeholder = secret.lower() in ('', 'change-me', 'changeme', 'your-secret-key')
        if not secret or _placeholder:
            if os.getenv('FLASK_ENV') == 'production':
                raise RuntimeError("SECRET_KEY must be set in production!")
            app.logger.warning("SECRET_KEY not set — using random key (sessions reset on restart)")
            secret = secrets.token_hex(32)
        app.config['SECRET_KEY'] = secret

    # ── Database ─────────────────────────────────────────────────
    db_url = get_secret('DATABASE_URL', 'sqlite:///campuspoll.db')
    if db_url.startswith('postgres://'):
        db_url = db_url.replace('postgres://', 'postgresql://', 1)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:' if testing else db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    is_pg = 'postgresql' in ('' if testing else db_url)
    app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        **({'pool_size': 10, 'max_overflow': 20, 'pool_timeout': 30} if is_pg else {}),
    }

    # ── Session / cookies ────────────────────────────────────────
    app.config['PERMANENT_SESSION_LIFETIME']  = timedelta(minutes=30)
    app.config['SESSION_COOKIE_HTTPONLY']     = True
    app.config['SESSION_COOKIE_SAMESITE']     = 'Lax'
    app.config['SESSION_COOKIE_SECURE']       = os.getenv('FLASK_ENV') == 'production'
    app.config['WTF_CSRF_ENABLED']            = not testing
    app.config['WTF_CSRF_TIME_LIMIT']         = 3600  # 1 hour — prevents expiry on slow forms

    # ── Mail ─────────────────────────────────────────────────────
    app.config['MAIL_SERVER']         = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
    app.config['MAIL_PORT']           = int(os.getenv('MAIL_PORT', 587))
    app.config['MAIL_USE_TLS']        = os.getenv('MAIL_USE_TLS', 'True') == 'True'
    app.config['MAIL_USERNAME']       = os.getenv('MAIL_USERNAME', '')
    app.config['MAIL_PASSWORD']       = get_secret('MAIL_PASSWORD', '')
    app.config['MAIL_DEFAULT_SENDER'] = os.getenv('MAIL_DEFAULT_SENDER', 'CampusPoll <noreply@campuspoll.com>')

    # ── Celery / limits ──────────────────────────────────────────
    app.config['CELERY_BROKER_URL']     = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
    app.config['RATELIMIT_STORAGE_URL'] = os.getenv('RATELIMIT_STORAGE_URL', 'memory://')
    app.config['UPLOAD_FOLDER']         = os.path.join(app.root_path, 'static', 'images')
    app.config['MAX_CONTENT_LENGTH']    = 2 * 1024 * 1024
    app.config['TESTING']               = testing

    # ── Prometheus metrics ───────────────────────────────────────────────
    if not testing:
        try:
            from prometheus_flask_exporter import PrometheusMetrics
            metrics = PrometheusMetrics(app)
            metrics.info('campuspoll_info', 'CampusPoll', version='6.0.0')
        except Exception:
            pass

    # ── Sentry ───────────────────────────────────────────────────
    sentry_dsn = os.getenv('SENTRY_DSN', '')
    if sentry_dsn and not testing:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        sentry_sdk.init(dsn=sentry_dsn, integrations=[FlaskIntegration()],
                        traces_sample_rate=0.2, environment=os.getenv('FLASK_ENV', 'development'))

    # ── Init extensions ──────────────────────────────────────────
    db.init_app(app)
    login_manager.init_app(app)
    if not testing:
        limiter.init_app(app)
    else:
        app.config['RATELIMIT_ENABLED'] = False
        limiter.init_app(app)
    csrf.init_app(app)
    mail.init_app(app)
    migrate.init_app(app, db)

    # ── CSRF error handler ────────────────────────────────────────
    from flask_wtf.csrf import CSRFError
    @app.errorhandler(CSRFError)
    def handle_csrf_error(e):
        from flask import flash, redirect, request as _req
        app.logger.warning(f"CSRF error on {_req.path}: {e.description}")
        flash('Session expired or invalid request. Please try again.', 'error')
        return redirect(_req.referrer or url_for('auth.index'))

    login_manager.login_view    = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'

    # ── Blueprints ───────────────────────────────────────────────
    from routes.auth          import auth
    from routes.voter         import voter
    from routes.candidate     import candidate
    from routes.admin         import admin
    from routes.analytics     import analytics
    from routes.notifications import notifications
    from routes.health        import health
    from routes.realtime      import init_socketio

    for bp in (auth, voter, candidate, admin, analytics, notifications, health):
        app.register_blueprint(bp)

    # When Celery Beat/workers run as separate processes (production), they
    # can't call this process's `socketio.emit()` directly. Bridging over
    # the same Redis broker lets flask_socketio.SocketIO(message_queue=...)
    # calls made from those processes reach browsers connected here.
    use_celery = os.getenv('USE_CELERY', 'false').lower() == 'true'
    socketio_mq = os.getenv('CELERY_BROKER_URL') if use_celery else None
    socketio.init_app(app, async_mode='threading', cors_allowed_origins='*', message_queue=socketio_mq)
    init_socketio(socketio, app)

    # ── DB + seed ────────────────────────────────────────────────
    with app.app_context():
        from models import (User, Election, Candidate, Vote, Nomination,
                            AnalyticsEvent, AuditLog, Notification,
                            LoginAttempt, Announcement, FraudLog)
        db.create_all()
        _seed_admin(app)
        _seed_demo_users(app)
        if not testing and os.getenv('USE_CELERY', 'false').lower() != 'true':
            _start_fallback_scheduler(app)


    # ── Slow query logger (dev only) ─────────────────────────────
    if os.getenv('FLASK_ENV') != 'production' and not testing:
        import time
        from sqlalchemy import event
        from sqlalchemy.engine import Engine

        @event.listens_for(Engine, 'before_cursor_execute')
        def _before(conn, cursor, stmt, params, ctx, multi):
            conn.info.setdefault('qtime', []).append(time.time())

        @event.listens_for(Engine, 'after_cursor_execute')
        def _after(conn, cursor, stmt, params, ctx, multi):
            elapsed = time.time() - conn.info['qtime'].pop(-1)
            if elapsed > 0.1:
                app.logger.warning(f"SLOW QUERY ({elapsed:.3f}s): {stmt[:150]}")

    return app


def _seed_admin(app):
    from models import User
    from services.user_service import hash_password
    if User.query.filter_by(role='admin').first():
        return
    admin_email    = os.getenv('ADMIN_EMAIL', 'admin@campuspoll.com')
    admin_password = os.getenv('ADMIN_PASSWORD')
    if not admin_password:
        if app.config['TESTING']:
            admin_password = 'TestAdmin@123'
        else:
            raise RuntimeError("ADMIN_PASSWORD must be set in .env")
    db.session.add(User(
        name='Admin', email=admin_email,
        password=hash_password(admin_password),
        student_id='ADMIN001', department='Administration',
        year='N/A', role='admin', is_active=True, is_verified=True,
    ))
    db.session.commit()
    app.logger.info(f"Default admin created: {admin_email}")


def _seed_demo_users(app):
    """Seed demo voters and candidates for development/demo use.
    Safe to call on every startup — skips any user that already exists.
    Passwords follow the pattern: Name@123 (e.g. Harsha@123, Arjun@123).
    """
    from models import User
    from services.user_service import hash_password

    demo_users = [
        # (name, email, student_id, department, year, role)
        ('Harsha',   'harsha@campuspoll.com',   'STU001', 'Computer Science',        '2nd Year', 'voter'),
        ('Arjun',    'arjun@campuspoll.com',    'STU002', 'Electronics',             '3rd Year', 'voter'),
        ('Sindhu',   'sindhu@campuspoll.com',   'STU003', 'Business Administration', '2nd Year', 'voter'),
        ('Pavithra', 'pavithra@campuspoll.com', 'STU004', 'Arts & Humanities',       '1st Year', 'voter'),
        ('Shastri',  'shastri@campuspoll.com',  'STU005', 'Mechanical',              '3rd Year', 'candidate'),
        ('Rakesh',   'rakesh@campuspoll.com',   'STU006', 'Computer Science',        '4th Year', 'candidate'),
    ]

    added = 0
    for name, email, student_id, dept, year, role in demo_users:
        if User.query.filter_by(email=email).first():
            continue  # already exists — skip
        password = f"{name[0].upper()}{name[1:].lower()}@123"
        db.session.add(User(
            name=name, email=email,
            password=hash_password(password),
            student_id=student_id,
            department=dept, year=year,
            role=role,
            is_active=True, is_verified=True,
        ))
        added += 1

    if added:
        db.session.commit()
        app.logger.info(f"Demo users seeded: {added} users added.")


def _start_fallback_scheduler(app):
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from services.election_service import auto_update_statuses
        sched = BackgroundScheduler(daemon=True)
        sched.add_job(lambda: auto_update_statuses(app), 'interval', minutes=1)
        sched.start()
        app.logger.info("APScheduler started (dev mode). Use Celery Beat in production.")
    except Exception as exc:
        app.logger.warning(f"Fallback scheduler not started: {exc}")
