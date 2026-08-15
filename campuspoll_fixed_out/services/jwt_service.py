"""JWT service for API endpoints."""
import os, logging
from datetime import datetime, timezone, timedelta
from functools import wraps
from flask import request, jsonify

logger = logging.getLogger(__name__)
SECRET = os.getenv('SECRET_KEY', 'dev')
ALGO   = 'HS256'


def generate_token(user_id: int, expires_in: int = 3600) -> str:
    try:
        import jwt
        payload = {
            'sub': user_id,
            'iat': datetime.now(timezone.utc),
            'exp': datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        }
        return jwt.encode(payload, SECRET, algorithm=ALGO)
    except Exception as e:
        logger.error(f"Token generation failed: {e}")
        raise


def jwt_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization', '').replace('Bearer ', '').strip()
        if not token:
            return jsonify({'error': 'Token required'}), 401
        try:
            import jwt as pyjwt
            payload = pyjwt.decode(token, SECRET, algorithms=[ALGO])
            from models import User
            user = User.query.get(payload['sub'])
            if not user or not user.is_active:
                return jsonify({'error': 'Invalid token'}), 401
            request.jwt_user = user
        except Exception:
            try:
                import jwt as pyjwt
                pyjwt.decode(token, SECRET, algorithms=[ALGO])
            except Exception as e:
                if 'expired' in str(e).lower():
                    return jsonify({'error': 'Token expired'}), 401
                return jsonify({'error': 'Invalid token'}), 401
        return f(*args, **kwargs)
    return decorated
