"""
Celery application — uses lazy app factory to avoid circular imports.

Start worker:  celery -A celery_app.celery worker --loglevel=info
Start beat:    celery -A celery_app.celery beat  --loglevel=info
"""
from celery import Celery
import os
from dotenv import load_dotenv

load_dotenv()

def make_celery(flask_app=None):
    broker  = os.getenv('CELERY_BROKER_URL',     'redis://localhost:6379/0')
    backend = os.getenv('CELERY_RESULT_BACKEND', 'redis://localhost:6379/0')

    celery = Celery('campuspoll', broker=broker, backend=backend)
    # Eager mode for tests
    if os.getenv('CELERY_TASK_ALWAYS_EAGER') == 'True':
        celery.conf.update(task_always_eager=True, task_eager_propagates=True)

    celery.conf.update(
        task_serializer='json',
        result_serializer='json',
        accept_content=['json'],
        timezone='UTC',
        enable_utc=True,
        broker_connection_retry_on_startup=True,
        beat_schedule={
            'auto-update-election-statuses': {
                'task': 'tasks.election_tasks.auto_update_statuses',
                'schedule': 60.0,
            },
            'celery-heartbeat': {
                'task': 'tasks.maintenance_tasks.celery_heartbeat',
                'schedule': 300.0,  # every 5 minutes
            },
            'purge-old-analytics': {
                'task': 'tasks.maintenance_tasks.purge_old_analytics',
                'schedule': 86400.0,  # daily
                'kwargs': {'days': 90},
            },
            'purge-old-login-attempts': {
                'task': 'tasks.maintenance_tasks.purge_old_login_attempts',
                'schedule': 86400.0,  # daily
                'kwargs': {'days': 7},
            },
        },
        # Dead letter queue — failed tasks after max_retries go here
        task_routes={
            'tasks.email_tasks.*': {'queue': 'emails'},
            'tasks.maintenance_tasks.*': {'queue': 'maintenance'},
            'tasks.election_tasks.*': {'queue': 'default'},
        },
        task_queues={
            'default': {'exchange': 'default'},
            'emails':  {'exchange': 'emails'},
            'maintenance': {'exchange': 'maintenance'},
        },
        # Reject (not ack) failed tasks so they go to DLQ if configured
        task_reject_on_worker_lost=True,
        task_acks_late=True,
    )

    if flask_app is not None:
        class ContextTask(celery.Task):
            def __call__(self, *args, **kwargs):
                with flask_app.app_context():
                    return self.run(*args, **kwargs)
        celery.Task = ContextTask

    return celery


# Standalone entry point — only imports Flask app when needed
celery = make_celery()

# Bind Flask context lazily when worker starts
@celery.on_after_finalize.connect
def bind_flask_app(sender, **kwargs):
    from app import create_app
    flask_app = create_app()

    class ContextTask(sender.Task):
        def __call__(self, *args, **kw):
            with flask_app.app_context():
                return self.run(*args, **kw)

    sender.Task = ContextTask
