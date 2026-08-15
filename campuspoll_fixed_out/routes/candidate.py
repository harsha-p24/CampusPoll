from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from models import Election, Nomination, Candidate
from app import db
from services.audit_service import log_event, log_audit
from utils.time_utils import now_ist
import os
from werkzeug.utils import secure_filename

candidate = Blueprint('candidate', __name__)

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg'}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@candidate.route('/nominations')
@login_required
def nominations():
    log_event('page_view', 'nominations')
    now = now_ist()
    open_elections = Election.query.filter(
        Election.nomination_start <= now,
        Election.nomination_end >= now
    ).all()
    my_nominations = Nomination.query.filter_by(user_id=current_user.id).all()
    return render_template('nominations.html', open_elections=open_elections, my_nominations=my_nominations, now=now)


@candidate.route('/apply-nomination/<int:election_id>', methods=['GET', 'POST'])
@login_required
def apply_nomination(election_id):
    election = Election.query.get_or_404(election_id)
    now = now_ist()

    # Check nomination window is open
    if now < election.nomination_start or now > election.nomination_end:
        flash('Nomination period is not active for this election.', 'error')
        return redirect(url_for('candidate.nominations'))

    # Prevent duplicate nominations
    existing = Nomination.query.filter_by(user_id=current_user.id, election_id=election_id).first()
    if existing:
        flash('You have already applied for this election.', 'info')
        return redirect(url_for('candidate.nominations'))

    if request.method == 'POST':
        manifesto = request.form.get('manifesto', '').strip()

        # --- FIX: server-side manifesto validation ---
        if not manifesto:
            flash('Manifesto is required.', 'error')
            return render_template('apply_nomination.html', election=election)
        if len(manifesto) < 50:
            flash(f'Manifesto must be at least 50 characters (currently {len(manifesto)}).', 'error')
            return render_template('apply_nomination.html', election=election)
        if len(manifesto) > 2000:
            flash('Manifesto cannot exceed 2000 characters.', 'error')
            return render_template('apply_nomination.html', election=election)
        # --- END FIX ---

        log_event('form_submission', 'apply_nomination', f'election_id:{election_id}')
        nomination = Nomination(
            user_id=current_user.id,
            election_id=election_id,
            manifesto=manifesto,
            status='pending'
        )
        db.session.add(nomination)
        db.session.commit()
        log_audit('nomination_applied', f'Applied for election:{election_id}')
        flash('Nomination submitted! Waiting for admin approval.', 'success')
        return redirect(url_for('candidate.nominations'))

    log_event('page_view', 'apply_nomination', f'election_id:{election_id}')
    return render_template('apply_nomination.html', election=election)


@candidate.route('/candidate/<int:candidate_id>')
def candidate_profile(candidate_id):
    c = Candidate.query.get_or_404(candidate_id)
    log_event('page_view', 'candidate_profile', f'candidate_id:{candidate_id}')
    return render_template('candidate_profile.html', candidate=c)
