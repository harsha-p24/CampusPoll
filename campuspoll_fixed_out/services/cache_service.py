"""Redis cache service with decorator support."""
import json, hashlib, os, logging
from functools import wraps

logger = logging.getLogger(__name__)

def _get_redis():
    try:
        import redis
        url = os.getenv('CELERY_BROKER_URL', 'redis://localhost:6379/0')
        # Use DB 2 for cache to avoid collisions with Celery (DB 0)
        cache_url = url.rsplit('/', 1)[0] + '/2'
        return redis.Redis.from_url(cache_url, socket_connect_timeout=2)
    except Exception:
        return None


def cache(ttl: int = 60, key_prefix: str = ''):
    """Decorator — caches function return value in Redis for `ttl` seconds."""
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            r = _get_redis()
            if not r:
                return f(*args, **kwargs)
            raw = f"{key_prefix or f.__name__}:{args}:{sorted(kwargs.items())}"
            key = f"cache:{hashlib.md5(raw.encode(), usedforsecurity=False).hexdigest()}"
            try:
                hit = r.get(key)
                if hit:
                    return json.loads(hit)
                result = f(*args, **kwargs)
                r.setex(key, ttl, json.dumps(result, default=str))
                return result
            except Exception as exc:
                logger.debug(f"Cache miss/error for {key}: {exc}")
                return f(*args, **kwargs)
        return wrapper
    return decorator


def invalidate(pattern: str):
    """Delete all cache keys matching pattern."""
    r = _get_redis()
    if not r:
        return
    try:
        keys = list(r.scan_iter(f"cache:*{pattern}*"))
        if keys:
            r.delete(*keys)
    except Exception as exc:
        logger.debug(f"Cache invalidate error: {exc}")
