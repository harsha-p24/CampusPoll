from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from models import Election, Candidate, Vote
from app import db
from services.audit_service import log_event, log_audit
from services.election_service import can_vote, get_results, cast_vote
from services.fraud_detection import detector as fraud_detector

voter = Blueprint('voter', __name__)


@voter.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'admin':
        return redirect(url_for('admin.dashboard'))
    search    = request.args.get('q', '').strip()
    query     = Election.query
    if search:
        query = query.filter(Election.title.ilike(f'%{search}%'))
    elections = query.order_by(Election.created_at.desc()).all()
    voted_ids = {v.election_id for v in Vote.query.filter_by(voter_id=current_user.id).all()}
    log_event('page_view', 'voter_dashboard')
    return render_template('voter_dashboard.html', elections=elections,
                           voted_ids=voted_ids, search=search)


@voter.route('/election/<int:election_id>')
@login_required
def election_detail(election_id):
    election      = Election.query.get_or_404(election_id)
    candidates    = Candidate.query.filter_by(election_id=election_id).all()
    already_voted = Vote.query.filter_by(voter_id=current_user.id, election_id=election_id).first()
    log_event('page_view', 'election_detail', f'election_id:{election_id}')
    return render_template('election_detail.html', election=election,
                           candidates=candidates, already_voted=already_voted,
                           can_vote_now=can_vote(election))


@voter.route('/vote/<int:election_id>', methods=['POST'])
@login_required
def cast_vote_route(election_id):
    election     = Election.query.get_or_404(election_id)
    candidate_id = request.form.get('candidate_id')
    log_event('button_click', 'vote', f'election_id:{election_id}')

    if not candidate_id:
        flash('Please select a candidate.', 'error')
        return redirect(url_for('voter.election_detail', election_id=election_id))

    candidate = db.session.get(Candidate, int(candidate_id))
    if not candidate:
        flash('Invalid candidate.', 'error')
        return redirect(url_for('voter.election_detail', election_id=election_id))

    # ── Fraud detection ────────────────────────────────────────
    from datetime import datetime, timezone
    signal = fraud_detector.analyse_vote_attempt(
        voter_id     = current_user.id,
        election_id  = election_id,
        ip_address   = request.remote_addr,
        user_agent   = request.headers.get('User-Agent', ''),
        request_time = datetime.now(timezone.utc).replace(tzinfo=None),
    )
    if signal.action == 'block':
        log_audit('vote_blocked_fraud', f'risk:{signal.risk_score} flags:{signal.flags}')
        flash('Your vote could not be processed. Please contact admin.', 'error')
        return redirect(url_for('voter.dashboard'))
    if signal.action == 'flag':
        log_audit('vote_flagged_fraud', f'risk:{signal.risk_score} flags:{signal.flags}')

    success, error = cast_vote(current_user, election, candidate)
    if not success:
        flash(error, 'error')
        return redirect(url_for('voter.election_detail', election_id=election_id))

    # ── Broadcast real-time update ──────────────────────────────
    try:
        from app import socketio
        from routes.realtime import broadcast_vote_update
        broadcast_vote_update(socketio, election_id)
    except Exception:
        pass

    log_audit('vote_cast', f'election:{election_id}, candidate:{candidate_id}')
    log_event('vote_cast', 'vote', f'election:{election_id}')

    # Queue vote confirmation email
    try:
        from tasks.email_tasks import send_vote_confirmation_email
        send_vote_confirmation_email.delay(current_user.id, election_id, candidate.id)
    except Exception:
        pass

    return redirect(url_for('voter.vote_confirmation',
                             election_id=election_id, candidate_id=candidate.id))


@voter.route('/vote-confirmation/<int:election_id>/<int:candidate_id>')
@login_required
def vote_confirmation(election_id, candidate_id):
    from utils.time_utils import now_ist
    election  = Election.query.get_or_404(election_id)
    candidate = db.session.get(Candidate, candidate_id)
    if not candidate:
        return redirect(url_for('voter.dashboard'))
    log_event('page_view', 'vote_confirmation')
    return render_template('vote_confirmation.html', election=election,
                           candidate=candidate,
                           now=now_ist())


@voter.route('/results/<int:election_id>')
@login_required
def results(election_id):
    election = Election.query.get_or_404(election_id)
    if not election.results_published:
        flash('Results have not been published yet.', 'info')
        return redirect(url_for('voter.dashboard'))
    candidates, total_votes = get_results(election)
    log_event('page_view', 'results', f'election_id:{election_id}')
    return render_template('results.html', election=election,
                           candidates=candidates, total_votes=total_votes)


@voter.route('/election/<int:election_id>/live-counts')
@login_required
def live_counts(election_id):
    """JSON endpoint polled by frontend every 15s during active voting."""
    from sqlalchemy import func
    election = Election.query.get_or_404(election_id)
    if not election.results_published:
        return jsonify({'published': False})
    rows = (
        db.session.query(Candidate.id, db.func.count(Vote.id).label('cnt'))
        .outerjoin(Vote, Vote.candidate_id == Candidate.id)
        .filter(Candidate.election_id == election_id)
        .group_by(Candidate.id)
        .all()
    )
    return jsonify({
        'published': True,
        'counts': {str(cid): cnt for cid, cnt in rows}
    })


@voter.route('/profile')
@login_required
def profile():
    log_event('page_view', 'profile')
    votes = Vote.query.filter_by(voter_id=current_user.id).all()
    return render_template('profile.html', votes=votes)
