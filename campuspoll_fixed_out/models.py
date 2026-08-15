from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime, timezone
from sqlalchemy import Index, func
from utils.time_utils import now_ist

@login_manager.user_loader
def load_user(user_id):
    return db.session.get(User, int(user_id))

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(100), nullable=False)
    email        = db.Column(db.String(120), unique=True, nullable=False, index=True)
    password     = db.Column(db.String(200), nullable=False)
    student_id   = db.Column(db.String(20),  unique=True, nullable=False, index=True)
    department   = db.Column(db.String(100), nullable=False)
    year         = db.Column(db.String(20),  nullable=False)
    role         = db.Column(db.String(20),  default='voter', index=True)
    is_active    = db.Column(db.Boolean, default=True)
    is_verified  = db.Column(db.Boolean, default=False)
    verify_token = db.Column(db.String(200), nullable=True)
    reset_token  = db.Column(db.String(200), nullable=True)
    totp_secret  = db.Column(db.String(100), nullable=True)
    totp_enabled   = db.Column(db.Boolean, default=False)
    session_token  = db.Column(db.String(64), nullable=True)
    created_at   = db.Column(db.DateTime, default=now_ist)
    last_login   = db.Column(db.DateTime, nullable=True)
    votes         = db.relationship('Vote',         backref='voter',  lazy='dynamic')
    nominations   = db.relationship('Nomination',   backref='student',lazy='dynamic')
    notifications = db.relationship('Notification', backref='user',   lazy='dynamic')

class Election(db.Model):
    __tablename__ = 'elections'
    id                = db.Column(db.Integer, primary_key=True)
    title             = db.Column(db.String(200), nullable=False)
    description       = db.Column(db.Text,   nullable=True)
    position          = db.Column(db.String(100), nullable=False)
    nomination_start  = db.Column(db.DateTime, nullable=False)
    nomination_end    = db.Column(db.DateTime, nullable=False)
    voting_start      = db.Column(db.DateTime, nullable=False)
    voting_end        = db.Column(db.DateTime, nullable=False)
    status            = db.Column(db.String(20), default='upcoming', index=True)
    results_published = db.Column(db.Boolean, default=False)
    created_at        = db.Column(db.DateTime, default=now_ist)
    candidates  = db.relationship('Candidate',  backref='election', lazy='dynamic', cascade='all, delete-orphan')
    votes       = db.relationship('Vote',       backref='election', lazy='dynamic', cascade='all, delete-orphan')
    nominations = db.relationship('Nomination', backref='election', lazy='dynamic', cascade='all, delete-orphan')

    @property
    def live_status(self):
        """
        Authoritative, always-correct status computed from the current time.

        `self.status` is a denormalized column only refreshed once a minute
        by a background job (APScheduler in dev / Celery Beat in prod).
        That's fine for DB filtering/sorting, but it must NEVER be used to
        decide whether voting/results are open right now — that decision
        has to be correct instantly, not up to 60s late. Every template and
        every access-control check uses this property instead of the raw
        `status` column.
        """
        from services.election_service import get_election_status
        return get_election_status(self)

class Nomination(db.Model):
    __tablename__ = 'nominations'
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'),     nullable=False, index=True)
    election_id = db.Column(db.Integer, db.ForeignKey('elections.id'), nullable=False, index=True)
    manifesto   = db.Column(db.Text, nullable=False)
    status      = db.Column(db.String(20), default='pending')
    applied_at  = db.Column(db.DateTime, default=now_ist)
    reviewed_at = db.Column(db.DateTime, nullable=True)

class Candidate(db.Model):
    __tablename__ = 'candidates'
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'),     nullable=False, index=True)
    election_id = db.Column(db.Integer, db.ForeignKey('elections.id'), nullable=False, index=True)
    manifesto   = db.Column(db.Text, nullable=False)
    photo       = db.Column(db.String(200), nullable=True)
    user        = db.relationship('User', backref='candidacies')

    @property
    def vote_count(self):
        """
        Returns _live_vote_count if set by get_results() (single JOIN query),
        otherwise falls back to a direct count (used in templates outside results).
        """
        if hasattr(self, '_live_vote_count'):
            return self._live_vote_count
        return Vote.query.filter_by(candidate_id=self.id).count()

class Vote(db.Model):
    __tablename__ = 'votes'
    id           = db.Column(db.Integer, primary_key=True)
    voter_id     = db.Column(db.Integer, db.ForeignKey('users.id'),     nullable=False, index=True)
    election_id  = db.Column(db.Integer, db.ForeignKey('elections.id'), nullable=False, index=True)
    candidate_id = db.Column(db.Integer, db.ForeignKey('candidates.id'),nullable=False, index=True)
    voted_at     = db.Column(db.DateTime, default=now_ist)
    __table_args__ = (db.UniqueConstraint('voter_id', 'election_id', name='unique_vote'),)

class Notification(db.Model):
    __tablename__ = 'notifications'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False, index=True)
    title      = db.Column(db.String(200), nullable=False)
    message    = db.Column(db.Text, nullable=False)
    type       = db.Column(db.String(50), default='info')
    is_read    = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=now_ist)

class LoginAttempt(db.Model):
    __tablename__ = 'login_attempts'
    id           = db.Column(db.Integer, primary_key=True)
    email        = db.Column(db.String(120), nullable=False)
    ip_address   = db.Column(db.String(50),  nullable=False, index=True)
    success      = db.Column(db.Boolean, default=False)
    attempted_at = db.Column(db.DateTime, default=now_ist)

class Announcement(db.Model):
    __tablename__ = 'announcements'
    id         = db.Column(db.Integer, primary_key=True)
    title      = db.Column(db.String(200), nullable=False)
    message    = db.Column(db.Text, nullable=False)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at = db.Column(db.DateTime, default=now_ist)
    is_active  = db.Column(db.Boolean, default=True)

class AnalyticsEvent(db.Model):
    __tablename__ = 'analytics_events'
    id           = db.Column(db.Integer, primary_key=True)
    user_id      = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    event_type   = db.Column(db.String(100), nullable=False, index=True)
    page         = db.Column(db.String(100), nullable=True)
    details      = db.Column(db.Text, nullable=True)
    load_time_ms = db.Column(db.Float, nullable=True)
    timestamp    = db.Column(db.DateTime, default=now_ist, index=True)
    ip_address   = db.Column(db.String(50), nullable=True)
    user_agent   = db.Column(db.String(300), nullable=True)

class AuditLog(db.Model):
    __tablename__ = 'audit_logs'
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    action     = db.Column(db.String(200), nullable=False, index=True)
    details    = db.Column(db.Text, nullable=True)
    timestamp  = db.Column(db.DateTime, default=now_ist, index=True)
    ip_address = db.Column(db.String(50), nullable=True)

class FraudLog(db.Model):
    __tablename__ = 'fraud_logs'
    id          = db.Column(db.Integer, primary_key=True)
    voter_id    = db.Column(db.Integer, db.ForeignKey('users.id'), index=True)
    election_id = db.Column(db.Integer, db.ForeignKey('elections.id'), index=True)
    risk_score  = db.Column(db.Float, nullable=False)
    flags       = db.Column(db.String(500))
    action      = db.Column(db.String(20))   # allow | flag | block
    created_at  = db.Column(db.DateTime, default=now_ist)
    voter       = db.relationship('User', foreign_keys=[voter_id])
