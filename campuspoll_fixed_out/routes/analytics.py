from flask import Blueprint, render_template, jsonify, request, send_file
from flask_login import login_required, current_user
from models import AnalyticsEvent, Vote, User, Election, Candidate, AuditLog
from app import db, limiter
from datetime import timedelta
from utils.time_utils import now_ist
from functools import wraps
import io
import json

analytics = Blueprint('analytics', __name__, url_prefix='/analytics')

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            return jsonify({'error': 'Admin access required'}), 403
        return f(*args, **kwargs)
    return decorated

@analytics.route('/track', methods=['POST'])
@limiter.limit('120 per minute')
def track():
    data = request.get_json()
    if not data:
        return jsonify({'status': 'error'}), 400
    event = AnalyticsEvent(
        user_id=current_user.id if not current_user.is_anonymous else None,
        event_type=data.get('event_type', 'unknown'),
        page=data.get('page'),
        details=data.get('details'),
        load_time_ms=data.get('load_time_ms'),
        ip_address=request.remote_addr,
        user_agent=request.headers.get('User-Agent', '')[:300]
    )
    db.session.add(event)
    db.session.commit()
    return jsonify({'status': 'ok'})

@analytics.route('/dashboard')
@login_required
@admin_required
def dashboard():
    # Overview stats
    total_users = User.query.filter_by(role='voter').count()
    total_votes = Vote.query.count()
    total_events = AnalyticsEvent.query.count()
    total_elections = Election.query.count()

    # Page views
    page_views = db.session.query(
        AnalyticsEvent.page,
        db.func.count(AnalyticsEvent.id).label('count')
    ).filter(AnalyticsEvent.event_type == 'page_view', AnalyticsEvent.page != None)\
     .group_by(AnalyticsEvent.page).order_by(db.text('count DESC')).limit(10).all()

    # Event types
    event_types = db.session.query(
        AnalyticsEvent.event_type,
        db.func.count(AnalyticsEvent.id).label('count')
    ).group_by(AnalyticsEvent.event_type).order_by(db.text('count DESC')).all()

    # Signups last 7 days
    seven_days_ago = now_ist() - timedelta(days=7)
    daily_signups = db.session.query(
        db.func.date(User.created_at).label('date'),
        db.func.count(User.id).label('count')
    ).filter(User.created_at >= seven_days_ago).group_by(db.func.date(User.created_at)).all()

    # Votes per election
    votes_per_election = db.session.query(
        Election.title,
        db.func.count(Vote.id).label('count')
    ).join(Vote, Vote.election_id == Election.id, isouter=True)\
     .group_by(Election.id).all()

    # Department-wise voter stats
    dept_stats = db.session.query(
        User.department,
        db.func.count(User.id).label('total')
    ).filter(User.role == 'voter').group_by(User.department).all()

    # Votes over time (last 7 days)
    votes_over_time = db.session.query(
        db.func.date(Vote.voted_at).label('date'),
        db.func.count(Vote.id).label('count')
    ).filter(Vote.voted_at >= seven_days_ago).group_by(db.func.date(Vote.voted_at)).all()

    # Login failures
    login_failures = AnalyticsEvent.query.filter_by(event_type='login_failed').count()
    login_success = AnalyticsEvent.query.filter_by(event_type='login_success').count()

    # Voter turnout per election
    elections = Election.query.all()
    turnout_data = []
    for e in elections:
        voted = Vote.query.filter_by(election_id=e.id).distinct(Vote.voter_id).count()
        total = User.query.filter(User.role.in_(['voter', 'candidate'])).count()
        turnout_data.append({'title': e.title[:30], 'voted': voted, 'total': total,
                             'pct': round(voted/total*100, 1) if total > 0 else 0})

    return render_template('admin/analytics.html',
        total_users=total_users, total_votes=total_votes,
        total_events=total_events, total_elections=total_elections,
        page_views=page_views, event_types=event_types,
        daily_signups=daily_signups, votes_per_election=votes_per_election,
        dept_stats=dept_stats, votes_over_time=votes_over_time,
        login_failures=login_failures, login_success=login_success,
        turnout_data=turnout_data
    )

@analytics.route('/election/<int:election_id>/chart-data')
def election_chart_data(election_id):
    candidates = Candidate.query.filter_by(election_id=election_id).all()
    data = {
        'labels': [c.user.name for c in candidates],
        'votes': [c.vote_count for c in candidates]
    }
    return jsonify(data)

@analytics.route('/token')
@login_required
def get_token():
    """Issue a short-lived JWT for polling live-counts API from JS."""
    from services.jwt_service import generate_token
    token = generate_token(current_user.id, expires_in=3600)
    return jsonify({'token': token, 'expires_in': 3600})
