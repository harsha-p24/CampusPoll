import pytest, os
os.environ['ADMIN_PASSWORD'] = 'TestAdmin@123'
os.environ['SECRET_KEY']     = 'test-secret-key-for-pytest'
os.environ['MAIL_USERNAME']  = ''

from app import create_app, db as _db

# Force Celery to run tasks synchronously in tests
import os
os.environ['CELERY_TASK_ALWAYS_EAGER'] = 'True'
os.environ['CELERY_TASK_EAGER_PROPAGATES'] = 'True'
from models import User
from werkzeug.security import generate_password_hash

@pytest.fixture(scope='function')
def app():
    _app = create_app(testing=True)
    ctx = _app.app_context()
    ctx.push()
    _db.create_all()
    yield _app
    _db.session.remove()
    _db.drop_all()
    ctx.pop()

@pytest.fixture(scope='function')
def db(app):
    return _db

@pytest.fixture(scope='function')
def client(app):
    with app.test_client() as c:
        yield c

@pytest.fixture(scope='function')
def voter_user(db, app):
    u = User(
        name='Test Voter', email='voter@test.com',
        password=generate_password_hash('Test@1234'),
        student_id='TEST001', department='CS', year='2nd Year',
        role='voter', is_active=True, is_verified=True,
    )
    db.session.add(u)
    db.session.commit()
    return u

@pytest.fixture(scope='function')
def admin_user(db, app):
    return User.query.filter_by(role='admin').first()
