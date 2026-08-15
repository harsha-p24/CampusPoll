# CampusPoll — Architecture Decision Records

## ADR-001: Flask over Django
**Decision:** Flask | **Reason:** Single-domain app. Flask's blueprints provide sufficient structure without Django's overhead. | **Trade-off:** More boilerplate written manually.

## ADR-002: SQLite → PostgreSQL migration path
**Decision:** SQLite (dev), PostgreSQL (prod) | **Reason:** SQLite has zero setup cost. PostgreSQL handles concurrent writes — SQLite's writer lock causes failures under real election load. | **Trade-off:** Must test PostgreSQL behaviour separately.

## ADR-003: Argon2 over bcrypt
**Decision:** argon2-cffi | **Reason:** OWASP recommendation, memory-hard, GPU-resistant. Legacy Werkzeug hashes migrated automatically on next login. | **Trade-off:** Extra dependency.

## ADR-004: Celery + Redis for emails/scheduling
**Decision:** Celery workers | **Reason:** Synchronous email blocks HTTP for 200–2000ms. Publishing results to 500 voters synchronously would time out. | **Trade-off:** Redis infrastructure required.

## ADR-005: Real-time vote_count JOIN query
**Decision:** No denormalized counter | **Reason:** Cached counters go stale on DB restore, mid-vote crash, concurrent writes. JOIN is always correct. | **Trade-off:** Slightly slower results page.

## ADR-006: Secrets abstraction layer
**Decision:** secrets_service.py | **Reason:** Institutions deploying to production use secrets managers. Abstraction means application code never changes. | **Trade-off:** Additional indirection.

## ADR-007: Flask-Migrate over bare create_all
**Decision:** Alembic migrations | **Reason:** create_all() has no schema upgrade path. Existing deployments need migrations, not full recreate. | **Trade-off:** Migration files must stay in sync with models.

## ADR-008: APScheduler (dev) vs Celery Beat (prod)
**Decision:** Dual-mode scheduling | **Reason:** Gunicorn 4 workers would run 4 APScheduler instances. Celery Beat is a single process. APScheduler requires no Redis for dev. | **Trade-off:** Different behaviour in dev vs prod.
