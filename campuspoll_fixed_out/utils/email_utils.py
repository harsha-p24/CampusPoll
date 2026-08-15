from flask_mail import Message
from app import mail
from flask import current_app, url_for
import traceback

def send_email(to, subject, body_html):
    """Send an email. Silently fails if mail not configured."""
    try:
        msg = Message(subject=subject, recipients=[to], html=body_html)
        mail.send(msg)
        return True
    except Exception:
        print(f"[Email] Failed to send to {to}: {traceback.format_exc()}")
        return False

def send_verification_email(user):
    link = url_for('auth.verify_email', token=user.verify_token, _external=True)
    html = f"""
    <h2>Welcome to CampusPoll!</h2>
    <p>Hi {user.name},</p>
    <p>Please verify your email address to activate your account and participate in elections.</p>
    <p><a href="{link}" style="background:#1a1a1a;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px;">Verify Email</a></p>
    <p>Or copy this link: {link}</p>
    <p>If you did not register, please ignore this email.</p>
    <br><p>— CampusPoll Team</p>
    """
    return send_email(user.email, "Verify your CampusPoll account", html)

def send_password_reset_email(user, reset_link):
    html = f"""
    <h2>Password Reset Request</h2>
    <p>Hi {user.name},</p>
    <p>Click below to reset your password. This link expires in 1 hour.</p>
    <p><a href="{reset_link}" style="background:#1a1a1a;color:#fff;padding:10px 20px;text-decoration:none;border-radius:4px;">Reset Password</a></p>
    <p>If you didn't request this, ignore this email.</p>
    <br><p>— CampusPoll Team</p>
    """
    return send_email(user.email, "Reset your CampusPoll password", html)

def send_nomination_approved_email(user, election):
    html = f"""
    <h2>🎉 Nomination Approved!</h2>
    <p>Hi {user.name},</p>
    <p>Your nomination for <strong>{election.position}</strong> in <strong>{election.title}</strong> has been <strong>approved</strong>!</p>
    <p>You are now an official candidate. Voting opens on <strong>{election.voting_start.strftime('%d %b %Y %H:%M')}</strong>.</p>
    <br><p>— CampusPoll Team</p>
    """
    return send_email(user.email, f"Nomination Approved — {election.title}", html)

def send_nomination_rejected_email(user, election):
    html = f"""
    <h2>Nomination Update</h2>
    <p>Hi {user.name},</p>
    <p>Unfortunately, your nomination for <strong>{election.position}</strong> in <strong>{election.title}</strong> was not approved this time.</p>
    <p>Please contact the admin for more details.</p>
    <br><p>— CampusPoll Team</p>
    """
    return send_email(user.email, f"Nomination Update — {election.title}", html)

def send_voting_open_email(user, election):
    html = f"""
    <h2>🗳️ Voting is Now Open!</h2>
    <p>Hi {user.name},</p>
    <p>Voting for <strong>{election.title}</strong> ({election.position}) is now open!</p>
    <p>Voting closes on <strong>{election.voting_end.strftime('%d %b %Y %H:%M')}</strong>.</p>
    <p>Cast your vote now and make your voice heard.</p>
    <br><p>— CampusPoll Team</p>
    """
    return send_email(user.email, f"Vote Now — {election.title}", html)

def send_results_published_email(user, election, winner_name):
    html = f"""
    <h2>📊 Election Results Published!</h2>
    <p>Hi {user.name},</p>
    <p>The results for <strong>{election.title}</strong> ({election.position}) are now available.</p>
    <p>Winner: <strong>{winner_name}</strong></p>
    <p>Log in to CampusPoll to view the full results and vote breakdown.</p>
    <br><p>— CampusPoll Team</p>
    """
    return send_email(user.email, f"Results Published — {election.title}", html)
