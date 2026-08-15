"""
/health — comprehensive health check endpoint.
Returns 200 OK if all critical services are healthy, 503 if degraded.
"""
from flask import Blueprint, jsonify
from datetime import datetime, timezone
import os, time

health = Blueprint('health', __name__)

_START_TIME = time.time()
VERSION = os.getenv('APP_VERSION', '5.0.0')


@health.route('/health')
def health_check():
    now   = datetime.now(timezone.utc)
    uptime = int(time.time() - _START_TIME)
    status = {'status': 'ok', 'timestamp': now.isoformat(),
              'version': VERSION, 'uptime_seconds': uptime, 'checks': {}}

    # ── Database ──────────────────────────────────────────────────
    try:
        from app import db
        db.session.execute(db.text('SELECT 1'))
        status['checks']['database'] = {'status': 'ok'}
    except Exception as e:
        status['checks']['database'] = {'status': 'error', 'detail': str(e)[:100]}
        status['status'] = 'degraded'

    # ── Redis ─────────────────────────────────────────────────────
    broker_url = os.getenv('CELERY_BROKER_URL', '')
    if broker_url and 'redis' in broker_url:
        try:
            import redis
            parts     = broker_url.replace('redis://', '').split('/')
            host_port = parts[0].split(':')
            host = host_port[0] or 'localhost'
            port = int(host_port[1]) if len(host_port) > 1 else 6379
            r    = redis.Redis(host=host, port=port, socket_connect_timeout=2)
            r.ping()
            info = r.info('memory')
            status['checks']['redis'] = {
                'status': 'ok',
                'used_memory_mb': round(info.get('used_memory', 0) / 1024 / 1024, 1),
            }

            # ── Celery heartbeat check ────────────────────────────
            db_num = int(parts[1]) if len(parts) > 1 else 0
            r2   = redis.Redis(host=host, port=port, db=db_num, socket_connect_timeout=2)
            last = r2.get('campuspoll:celery_heartbeat')
            if last:
                status['checks']['celery_worker'] = {
                    'status': 'ok',
                    'last_heartbeat': last.decode(),
                }
            else:
                status['checks']['celery_worker'] = {
                    'status': 'unknown',
                    'detail': 'No heartbeat yet (worker may not be running)',
                }
        except Exception as e:
            status['checks']['redis']         = {'status': 'error', 'detail': str(e)[:100]}
            status['checks']['celery_worker'] = {'status': 'unknown'}
            status['status'] = 'degraded'
    else:
        status['checks']['redis']         = {'status': 'not_configured'}
        status['checks']['celery_worker'] = {'status': 'not_configured'}

    # ── Disk space ────────────────────────────────────────────────
    try:
        import shutil
        total, used, free = shutil.disk_usage('/')
        free_pct = round(free / total * 100, 1)
        disk_status = 'ok' if free_pct > 10 else ('warning' if free_pct > 5 else 'critical')
        status['checks']['disk'] = {
            'status':      disk_status,
            'free_gb':     round(free / 1024**3, 2),
            'total_gb':    round(total / 1024**3, 2),
            'free_pct':    free_pct,
        }
        if disk_status == 'critical':
            status['status'] = 'degraded'
    except Exception as e:
        status['checks']['disk'] = {'status': 'error', 'detail': str(e)[:100]}

    http_status = 200 if status['status'] == 'ok' else 503
    return jsonify(status), http_status


@health.route('/health/queue')
def queue_depth():
    """Returns Celery queue depths — useful for monitoring backlogs."""
    broker_url = os.getenv('CELERY_BROKER_URL', '')
    if not broker_url or 'redis' not in broker_url:
        return jsonify({'error': 'Redis not configured'}), 503
    try:
        import redis
        parts     = broker_url.replace('redis://', '').split('/')
        host_port = parts[0].split(':')
        host = host_port[0] or 'localhost'
        port = int(host_port[1]) if len(host_port) > 1 else 6379
        r    = redis.Redis(host=host, port=port, socket_connect_timeout=2)
        queues = ['default', 'emails', 'maintenance', 'celery']
        depths = {}
        for q in queues:
            depths[q] = r.llen(q)
        return jsonify({'queues': depths, 'timestamp': datetime.now(timezone.utc).isoformat()})
    except Exception as e:
        return jsonify({'error': str(e)[:100]}), 503
