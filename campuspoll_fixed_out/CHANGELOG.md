# CampusPoll Changelog

## v6.0.1 — Real-time correctness & live-results isolation fixes

### Root cause fixed: UI relied on the stale, once-a-minute-refreshed `Election.status` column
Backend vote/publish logic was already time-safe (`can_vote()`, `publish_results` all
re-derive from the clock), but templates and a few admin guards read the stored
`status` column directly, which is only refreshed every 60s by APScheduler
(dev) / Celery Beat (prod). This meant the Vote button, status badges, and
edit/delete guards could lag reality by up to a minute, and could allow
editing/deleting an election that had already started or ended.
- Added `Election.live_status`, an always-correct, time-derived property; all
  templates (`voter_dashboard.html`, `election_detail.html`,
  `admin/dashboard.html`) and admin route guards (`edit_election`,
  `delete_election`) now use it instead of the raw `status` column.
- `publish_results` now has a server-side guard (not just a hidden template
  condition) preventing announcing results before voting has actually ended,
  and is idempotent if called twice.

### Real-time updates without manual refresh
- New `static/js/election_realtime.js` (loaded site-wide): renders
  start/close countdowns, auto-reloads the page once a voting window
  boundary is crossed, and listens for Socket.IO push events — with a
  20s polling fallback in case the socket drops.
- `services.election_service.emit_realtime()` broadcasts an
  `election_status` event whenever the background status job changes an
  election's status, and a `results_announced` event the moment an admin
  announces results — from both the in-process APScheduler path and the
  out-of-process Celery Beat/worker path (bridged over the existing Redis
  broker via Flask-SocketIO's `message_queue`).

### Fixed a live-results leak to voters (requirement: live results are admin-only pre-announcement)
- Split the single Socket.IO election room into a public `election_{id}`
  room (status/results-announced notifications only — safe for anyone) and
  a restricted `election_{id}_live` room (real per-candidate vote counts —
  admins only, or anyone once results are officially announced). Previously
  a single shared room meant a voter's browser could receive raw live vote
  counts over the wire during an active, unannounced election.

### Admin "Current Voting" dashboard
- Admin dashboard now always shows the currently active election (title,
  window, live status, total votes, and a live per-candidate vote table
  that updates via Socket.IO as votes come in) or a clear "no active
  election" message, per spec.

## v5.0.0 — Current Release

### Security
- Argon2 password hashing replacing bcrypt, with automatic legacy hash migration on login
- Content Security Policy header on all responses
- X-Frame-Options, X-Content-Type-Options, X-XSS-Protection headers
- X-Request-ID header for request tracing and log correlation
- robots.txt blocking /admin/, /analytics/, /notifications/
- MIME type sniffing on file uploads (magic bytes validation)
- Rate limiting on /register (10/hour), /login (30/min), /2fa (10/hour), /forgot-password (5/hour)
- Honeypot field on registration form to block bots
- Session invalidation token on password change
- TOTP 2FA with brute force protection
- 0 high-severity issues in Bandit security scan

### Architecture
- Celery + Redis for async email delivery with retry (max 3 attempts)
- Celery Beat for scheduled tasks (election status, analytics purge, heartbeat)
- Dead letter queue config with task_reject_on_worker_lost
- Secrets abstraction layer supporting env vars, AWS Secrets Manager, HashiCorp Vault, GCP Secret Manager
- JSON structured logging with request ID correlation
- Service layer: election_service, user_service, audit_service, secrets_service

### Database
- Flask-Migrate with committed baseline migration (flask db upgrade works out of the box)
- vote_count computed via real-time JOIN query — no stale denormalized counter
- Indexes on all hot columns (email, student_id, role, election_id, voter_id, timestamp)
- PostgreSQL pool config (pool_size=10, max_overflow=20, pool_timeout=30)
- Analytics events TTL purge (90 days, runs daily via Celery Beat)
- Login attempt purge (7 days, runs daily)

### Testing
- 184 tests | 80% coverage
- Celery tasks tested with eager mode + mock patching
- 2FA setup/verify/disable tested
- File upload MIME validation tested
- Concurrent vote duplicate prevention tested
- Security headers tested
- Health endpoint tested
- Honeypot tested
- Maintenance tasks tested

### DevOps
- GitHub Actions CI: tests + Bandit scan + Docker build on every push
- Zero-downtime deploy script with automated rollback on health check failure
- Database backup script (PostgreSQL + SQLite, 30-day retention)
- Nginx config with SSL, security headers, static file serving
- Systemd service files for Gunicorn, Celery worker, Celery Beat
- Docker Compose with Redis + all three services
- /health endpoint: DB, Redis, Celery heartbeat, disk space, version, uptime
- /health/queue: Celery queue depth monitoring

### Accessibility
- Skip-to-content link for keyboard users
- ARIA landmark roles (nav, main, footer, contentinfo)
- ARIA labels on notification bell, voting form inputs
- fieldset + legend on candidate selection
- Focus-visible styles for keyboard navigation
- Screen-reader-only utility class

### Load Testing
- Locust load test script with AnonymousUser, VoterUser, AdminUser scenarios
- Documented performance targets (p95 < 200ms homepage, <800ms vote)

---

## v4.0.0
- 72 tests | 62% coverage
- Rate limiting on login and 2FA
- Email verification
- CSRF protection
- Session timeout
- Flask-Migrate initial setup

## v3.0.0
- Service layer introduced
- Argon2 password hashing (first attempt)
- Celery async emails (first attempt)

## v2.0.0
- Pagination, search, CSV import/export
- Notification bell
- Docker support

## v1.0.0
- Initial release
- Core election flow: nomination → voting → results
- Admin dashboard
- Analytics tracking
