from flask import Blueprint, render_template, redirect, url_for, request, flash, send_file
from flask_login import login_required, current_user
from models import User, Election, Nomination, Candidate, Vote, AuditLog, Announcement
from app import db
from datetime import datetime, timezone
from functools import wraps
from services.audit_service import log_audit, notify_user
from services.user_service import sanitize
from utils.time_utils import now_ist
import io, csv

admin = Blueprint('admin', __name__, url_prefix='/admin')


def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('Admin access required.', 'error')
            return redirect(url_for('auth.login'))
        return f(*args, **kwargs)
    return decorated


# ── Dashboard ────────────────────────────────────────────────────────────────

@admin.route('/dashboard')
@login_required
@admin_required
def dashboard():
    from services.election_service import get_results

    total_users        = User.query.filter(User.role != 'admin').count()
    total_elections    = Election.query.count()
    total_votes        = Vote.query.count()
    pending_noms       = Nomination.query.filter_by(status='pending').count()
    recent_logs        = AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(10).all()
    elections          = Election.query.order_by(Election.created_at.desc()).all()
    announcements      = Announcement.query.order_by(Announcement.created_at.desc()).limit(5).all()

    # ── Current Voting Dashboard (requirement: admin can always see the
    # currently active election with live, admin-only per-candidate counts
    # while voting is in progress) ─────────────────────────────────────────
    current_election  = next((e for e in elections if e.live_status == 'voting'), None)
    current_candidates, current_total_votes = ([], 0)
    if current_election:
        current_candidates, current_total_votes = get_results(current_election)

    return render_template('admin/dashboard.html',
        total_users=total_users, total_elections=total_elections,
        total_votes=total_votes, pending_nominations=pending_noms,
        recent_logs=recent_logs, elections=elections,
        announcements=announcements, now=now_ist(),
        current_election=current_election,
        current_candidates=current_candidates,
        current_total_votes=current_total_votes)


# ── Elections ────────────────────────────────────────────────────────────────

@admin.route('/elections/create', methods=['GET', 'POST'])
@login_required
@admin_required
def create_election():
    if request.method == 'POST':
        try:
            title    = sanitize(request.form.get('title', ''), 200)
            position = sanitize(request.form.get('position', ''), 100)
            if not title or not position:
                flash('Title and position are required.', 'error')
                return render_template('admin/create_election.html', form=request.form)

            nom_start = request.form.get('nomination_start', '').strip()
            nom_end   = request.form.get('nomination_end', '').strip()
            vot_start = request.form.get('voting_start', '').strip()
            vot_end   = request.form.get('voting_end', '').strip()

            if not all([nom_start, nom_end, vot_start, vot_end]):
                flash('All date/time fields are required.', 'error')
                return render_template('admin/create_election.html', form=request.form)

            election = Election(
                title=title,
                description=sanitize(request.form.get('description', ''), 1000),
                position=position,
                nomination_start=datetime.strptime(nom_start, '%Y-%m-%dT%H:%M'),
                nomination_end  =datetime.strptime(nom_end,   '%Y-%m-%dT%H:%M'),
                voting_start    =datetime.strptime(vot_start, '%Y-%m-%dT%H:%M'),
                voting_end      =datetime.strptime(vot_end,   '%Y-%m-%dT%H:%M'),
                status='upcoming',
            )
            if election.nomination_end <= election.nomination_start:
                flash('Nomination end must be after nomination start.', 'error')
                return render_template('admin/create_election.html', form=request.form)
            if election.voting_end <= election.voting_start:
                flash('Voting end must be after voting start.', 'error')
                return render_template('admin/create_election.html', form=request.form)
            db.session.add(election)
            db.session.commit()
            log_audit('election_created', f'title:{election.title}')
            flash('Election created successfully!', 'success')
            return redirect(url_for('admin.dashboard'))
        except ValueError:
            flash('Invalid date format.', 'error')
    return render_template('admin/create_election.html', form={})


@admin.route('/elections/<int:election_id>/edit', methods=['GET', 'POST'])
@login_required
@admin_required
def edit_election(election_id):
    election = Election.query.get_or_404(election_id)
    if election.live_status in ('voting', 'closed', 'completed'):
        flash('Cannot edit an election that is currently voting or has ended.', 'error')
        return redirect(url_for('admin.dashboard'))
    if request.method == 'POST':
        try:
            title    = sanitize(request.form.get('title', ''), 200)
            position = sanitize(request.form.get('position', ''), 100)
            if not title or not position:
                flash('Title and position are required.', 'error')
                return render_template('admin/edit_election.html', election=election)

            nom_start = request.form.get('nomination_start', '').strip()
            nom_end   = request.form.get('nomination_end', '').strip()
            vot_start = request.form.get('voting_start', '').strip()
            vot_end   = request.form.get('voting_end', '').strip()

            if not all([nom_start, nom_end, vot_start, vot_end]):
                flash('All date/time fields are required.', 'error')
                return render_template('admin/edit_election.html', election=election)

            election.title       = title
            election.description = sanitize(request.form.get('description', ''), 1000)
            election.position    = position
            election.nomination_start = datetime.strptime(nom_start, '%Y-%m-%dT%H:%M')
            election.nomination_end   = datetime.strptime(nom_end,   '%Y-%m-%dT%H:%M')
            election.voting_start     = datetime.strptime(vot_start, '%Y-%m-%dT%H:%M')
            election.voting_end       = datetime.strptime(vot_end,   '%Y-%m-%dT%H:%M')
            db.session.commit()
            log_audit('election_edited', f'id:{election_id}')
            flash('Election updated successfully!', 'success')
            return redirect(url_for('admin.dashboard'))
        except ValueError:
            flash('Invalid date format.', 'error')
    return render_template('admin/edit_election.html', election=election)


@admin.route('/elections/<int:election_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_election(election_id):
    election = Election.query.get_or_404(election_id)
    if election.live_status in ('voting', 'closed', 'completed'):
        flash('Cannot delete an active or completed election.', 'error')
        return redirect(url_for('admin.dashboard'))
    db.session.delete(election)
    db.session.commit()
    log_audit('election_deleted', f'title:{election.title}')
    flash('Election deleted.', 'info')
    return redirect(url_for('admin.dashboard'))


# ── Nominations ───────────────────────────────────────────────────────────────

@admin.route('/nominations')
@login_required
@admin_required
def manage_nominations():
    page   = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    q      = Nomination.query.filter_by(status='pending').join(User, Nomination.user_id == User.id)
    if search:
        q  = q.filter(User.name.ilike(f'%{search}%'))
    pending  = q.paginate(page=page, per_page=10, error_out=False)
    reviewed = Nomination.query.filter(Nomination.status != 'pending')\
        .order_by(Nomination.reviewed_at.desc()).limit(20).all()
    return render_template('admin/nominations.html', pending=pending, reviewed=reviewed, search=search)


@admin.route('/nominations/<int:nom_id>/approve')
@login_required
@admin_required
def approve_nomination(nom_id):
    nom = Nomination.query.get_or_404(nom_id)
    nom.status      = 'approved'
    nom.reviewed_at = now_ist()
    if not Candidate.query.filter_by(user_id=nom.user_id, election_id=nom.election_id).first():
        db.session.add(Candidate(user_id=nom.user_id, election_id=nom.election_id, manifesto=nom.manifesto))
        db.session.get(User, nom.user_id).role = 'candidate'
    db.session.commit()
    notify_user(nom.user_id, 'Nomination Approved 🎉',
                f'Your nomination for {nom.election.position} has been approved!', 'success')
    try:
        from utils.email_utils import send_nomination_approved_email
        send_nomination_approved_email(nom.student, nom.election)
    except Exception:
        pass
    log_audit('nomination_approved', f'nom_id:{nom_id}')
    flash('Nomination approved!', 'success')
    return redirect(url_for('admin.manage_nominations'))


@admin.route('/nominations/<int:nom_id>/reject')
@login_required
@admin_required
def reject_nomination(nom_id):
    nom = Nomination.query.get_or_404(nom_id)
    nom.status      = 'rejected'
    nom.reviewed_at = now_ist()
    db.session.commit()
    notify_user(nom.user_id, 'Nomination Update',
                f'Your nomination for {nom.election.position} was not approved.', 'warning')
    try:
        from utils.email_utils import send_nomination_rejected_email
        send_nomination_rejected_email(nom.student, nom.election)
    except Exception:
        pass
    log_audit('nomination_rejected', f'nom_id:{nom_id}')
    flash('Nomination rejected.', 'info')
    return redirect(url_for('admin.manage_nominations'))


# ── Results ───────────────────────────────────────────────────────────────────

@admin.route('/elections/<int:election_id>/publish-results')
@login_required
@admin_required
def publish_results(election_id):
    election = Election.query.get_or_404(election_id)
    if election.results_published:
        flash('Results have already been announced for this election.', 'info')
        return redirect(url_for('admin.dashboard'))
    if now_ist() <= election.voting_end:
        flash('Cannot announce results before voting has ended.', 'error')
        return redirect(url_for('admin.dashboard'))
    try:
        from tasks.email_tasks import publish_results_task
        publish_results_task.delay(election_id)
        log_audit('results_published_queued', f'election_id:{election_id}')
        flash('Results are being published and voters will be notified shortly!', 'success')
    except Exception:
        # Celery not running — do it synchronously
        from models import Candidate, Vote as _Vote
        from sqlalchemy import func as _func
        election = db.session.get(Election, election_id)
        election.results_published = True
        election.status = 'completed'
        db.session.commit()
        # FIX: vote_count is a Python @property — cannot use in ORDER BY.
        # Use a proper SQL COUNT via outerjoin instead.
        candidates = (
            db.session.query(Candidate)
            .outerjoin(_Vote, _Vote.candidate_id == Candidate.id)
            .filter(Candidate.election_id == election_id)
            .group_by(Candidate.id)
            .order_by(_func.count(_Vote.id).desc())
            .all()
        )
        winner_name = candidates[0].user.name if candidates else 'N/A'
        voters = User.query.filter(User.role.in_(['voter', 'candidate']), User.is_active == True).all()
        for v in voters:
            notify_user(v.id, f'Results — {election.title}', f'Winner: {winner_name}. View results now!', 'info')
        from app import socketio
        from services.election_service import emit_realtime
        emit_realtime('results_announced', {'election_id': election_id},
                      room=f'election_{election_id}', app_socketio=socketio)
        log_audit('results_published', f'election_id:{election_id}')
        flash('Results published and all voters notified!', 'success')
    return redirect(url_for('admin.dashboard'))


@admin.route('/elections/<int:election_id>/notify-voters')
@login_required
@admin_required
def notify_voting_open(election_id):
    election = Election.query.get_or_404(election_id)
    voters   = User.query.filter(User.role.in_(['voter', 'candidate']), User.is_active == True).all()
    for v in voters:
        notify_user(v.id, f'Voting Open — {election.title}',
                    f'Vote for {election.position} closes {election.voting_end.strftime("%d %b %Y %H:%M")}!', 'info')
    try:
        from tasks.email_tasks import send_bulk_voting_open
        send_bulk_voting_open.delay(election_id)
    except Exception:
        pass  # Celery not running — emails skipped
    log_audit('voters_notified', f'election_id:{election_id}')
    flash(f'Notified {len(voters)} voters!', 'success')
    return redirect(url_for('admin.dashboard'))


# ── Announcements ────────────────────────────────────────────────────────────

@admin.route('/announcements/create', methods=['POST'])
@login_required
@admin_required
def create_announcement():
    title   = sanitize(request.form.get('title', ''), 200)
    message = sanitize(request.form.get('message', ''), 1000)
    if not title or not message:
        flash('Title and message are required.', 'error')
        return redirect(url_for('admin.dashboard'))
    db.session.add(Announcement(title=title, message=message, created_by=current_user.id))
    db.session.commit()
    log_audit('announcement_created', f'title:{title}')
    flash('Announcement posted!', 'success')
    return redirect(url_for('admin.dashboard'))


@admin.route('/announcements/<int:ann_id>/delete', methods=['POST'])
@login_required
@admin_required
def delete_announcement(ann_id):
    ann = Announcement.query.get_or_404(ann_id)
    db.session.delete(ann)
    db.session.commit()
    log_audit('announcement_deleted', f'id:{ann_id}')
    flash('Announcement removed.', 'info')
    return redirect(url_for('admin.dashboard'))


# ── Users ────────────────────────────────────────────────────────────────────

@admin.route('/users')
@login_required
@admin_required
def manage_users():
    page   = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    dept   = request.args.get('dept', '')
    role   = request.args.get('role', '')
    q      = User.query.filter(User.role != 'admin')
    if search:
        q = q.filter(db.or_(
            User.name.ilike(f'%{search}%'),
            User.email.ilike(f'%{search}%'),
            User.student_id.ilike(f'%{search}%'),
        ))
    if dept:
        q = q.filter_by(department=dept)
    if role:
        q = q.filter_by(role=role)
    users       = q.order_by(User.created_at.desc()).paginate(page=page, per_page=15, error_out=False)
    departments = [d[0] for d in db.session.query(User.department).distinct().all()]
    return render_template('admin/users.html', users=users, search=search,
                           dept=dept, role=role, departments=departments)


@admin.route('/users/<int:user_id>/toggle')
@login_required
@admin_required
def toggle_user(user_id):
    user        = User.query.get_or_404(user_id)
    user.is_active = not user.is_active
    db.session.commit()
    status = 'activated' if user.is_active else 'deactivated'
    log_audit(f'user_{status}', f'user_id:{user_id}')
    flash(f'User {status}.', 'success')
    return redirect(url_for('admin.manage_users'))


@admin.route('/users/import-csv', methods=['GET', 'POST'])
@login_required
@admin_required
def import_users_csv():
    if request.method == 'POST':
        file = request.files.get('csv_file')
        if not file or not file.filename.endswith('.csv'):
            flash('Please upload a valid .csv file.', 'error')
            return redirect(url_for('admin.manage_users'))
        from werkzeug.security import generate_password_hash
        import secrets as _sec, io as _io
        stream  = _io.StringIO(file.stream.read().decode('UTF-8', errors='ignore'))
        reader  = csv.DictReader(stream)
        added, skipped = 0, 0
        for row in reader:
            email      = sanitize(row.get('email', '').strip().lower(), 120)
            student_id = sanitize(row.get('student_id', '').strip(), 20)
            if not email or not student_id:
                skipped += 1; continue
            if User.query.filter_by(email=email).first() or User.query.filter_by(student_id=student_id).first():
                skipped += 1; continue
            db.session.add(User(
                name=sanitize(row.get('name', 'Student'), 100),
                email=email, student_id=student_id,
                password=generate_password_hash(_sec.token_urlsafe(12)),
                department=sanitize(row.get('department', 'General'), 100),
                year=sanitize(row.get('year', '1st Year'), 20),
                role='voter', is_active=True, is_verified=True,
            ))
            added += 1
        db.session.commit()
        log_audit('bulk_import', f'added:{added}, skipped:{skipped}')
        flash(f'Imported {added} users. Skipped {skipped} duplicates.', 'success')
        return redirect(url_for('admin.manage_users'))
    return render_template('admin/import_csv.html')


@admin.route('/users/export-csv')
@login_required
@admin_required
def export_users_csv():
    users  = User.query.filter(User.role != 'admin').all()
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['name', 'email', 'student_id', 'department', 'year', 'role', 'is_active', 'joined'])
    for u in users:
        writer.writerow([u.name, u.email, u.student_id, u.department, u.year,
                         u.role, u.is_active, u.created_at.strftime('%Y-%m-%d')])
    output.seek(0)
    log_audit('users_exported_csv')
    return send_file(io.BytesIO(output.getvalue().encode()), as_attachment=True,
                     download_name='campuspoll_users.csv', mimetype='text/csv')


# ── Audit log ─────────────────────────────────────────────────────────────────

@admin.route('/audit-log')
@login_required
@admin_required
def audit_log():
    page   = request.args.get('page', 1, type=int)
    search = request.args.get('search', '')
    q      = AuditLog.query.order_by(AuditLog.timestamp.desc())
    if search:
        q = q.filter(AuditLog.action.ilike(f'%{search}%'))
    logs = q.paginate(page=page, per_page=25, error_out=False)
    return render_template('admin/audit_log.html', logs=logs, search=search)


# ── PDF export ────────────────────────────────────────────────────────────────

@admin.route('/elections/<int:election_id>/export-pdf')
@login_required
@admin_required
def export_results_pdf(election_id):
    from reportlab.lib.pagesizes import letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    election   = Election.query.get_or_404(election_id)
    # FIX: vote_count is a Python @property — cannot use in ORDER BY.
    from sqlalchemy import func as _func
    candidates = (
        db.session.query(Candidate)
        .outerjoin(Vote, Vote.candidate_id == Candidate.id)
        .filter(Candidate.election_id == election_id)
        .group_by(Candidate.id)
        .order_by(_func.count(Vote.id).desc())
        .all()
    )
    total_votes = sum(c.vote_count for c in candidates)
    buffer     = io.BytesIO()
    doc        = SimpleDocTemplate(buffer, pagesize=letter)
    styles     = getSampleStyleSheet()
    elements   = [
        Paragraph("CampusPoll — Election Results", styles['Title']),
        Paragraph(f"{election.title} — {election.position}", styles['Heading2']),
        Spacer(1, 12),
        Paragraph(f"Total Votes Cast: {total_votes}", styles['Normal']),
        Paragraph(f"Published: {now_ist().strftime('%d %b %Y %H:%M')}", styles['Normal']),
        Spacer(1, 12),
    ]
    data = [['Rank', 'Candidate', 'Department', 'Votes', '%']]
    for i, c in enumerate(candidates, 1):
        pct = f"{c.vote_count/total_votes*100:.1f}%" if total_votes else "0%"
        data.append([str(i), c.user.name, c.user.department, str(c.vote_count), pct])
    table = Table(data, colWidths=[40, 160, 160, 60, 60])
    table.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), colors.grey),
        ('TEXTCOLOR',  (0,0), (-1,0), colors.whitesmoke),
        ('FONTNAME',   (0,0), (-1,0), 'Helvetica-Bold'),
        ('ALIGN',      (0,0), (-1,-1), 'CENTER'),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.lightgrey]),
        ('GRID', (0,0), (-1,-1), 0.5, colors.black),
    ]))
    elements.append(table)
    if candidates:
        elements += [Spacer(1,16), Paragraph(f"Winner: {candidates[0].user.name}", styles['Heading3'])]
    doc.build(elements)
    buffer.seek(0)
    log_audit('results_pdf_exported', f'election_id:{election_id}')
    return send_file(buffer, as_attachment=True,
                     download_name=f'results_{election_id}.pdf', mimetype='application/pdf')

@admin.route('/fraud-signals')
@login_required
@admin_required
def fraud_signals():
    from models import FraudLog
    page    = request.args.get('page', 1, type=int)
    flagged = FraudLog.query.filter(
        FraudLog.action.in_(['flag', 'block'])
    ).order_by(FraudLog.created_at.desc()).paginate(page=page, per_page=25, error_out=False)
    total_flagged = FraudLog.query.filter_by(action='flag').count()
    total_blocked = FraudLog.query.filter_by(action='block').count()
    return render_template('admin/fraud_signals.html',
                           signals=flagged,
                           total_flagged=total_flagged,
                           total_blocked=total_blocked)
