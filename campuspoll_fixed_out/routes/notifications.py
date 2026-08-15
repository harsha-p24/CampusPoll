from flask import Blueprint, jsonify, request
from flask_login import login_required, current_user
from models import Notification
from app import db

notifications = Blueprint('notifications', __name__, url_prefix='/notifications')

@notifications.route('/')
@login_required
def get_notifications():
    notifs = Notification.query.filter_by(user_id=current_user.id)\
        .order_by(Notification.created_at.desc()).limit(20).all()
    unread = Notification.query.filter_by(user_id=current_user.id, is_read=False).count()
    return jsonify({
        'unread': unread,
        'notifications': [{
            'id': n.id,
            'title': n.title,
            'message': n.message,
            'type': n.type,
            'is_read': n.is_read,
            'created_at': n.created_at.strftime('%d %b %Y %H:%M')
        } for n in notifs]
    })

@notifications.route('/mark-read/<int:notif_id>', methods=['POST'])
@login_required
def mark_read(notif_id):
    n = Notification.query.filter_by(id=notif_id, user_id=current_user.id).first()
    if n:
        n.is_read = True
        db.session.commit()
    return jsonify({'status': 'ok'})

@notifications.route('/mark-all-read', methods=['POST'])
@login_required
def mark_all_read():
    Notification.query.filter_by(user_id=current_user.id, is_read=False)\
        .update({'is_read': True})
    db.session.commit()
    return jsonify({'status': 'ok'})
