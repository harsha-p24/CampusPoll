# CampusPoll — Digital Student Election Platform

A secure, production-grade web application for conducting college elections end-to-end.

**Test status: 72/72 passing | Coverage: 62%**

---

## Quick Start

### Option 1 — Docker (Recommended)
```bash
cp .env.example .env
# Edit .env with your values
docker-compose up -d
# Open http://localhost:5000
```

### Option 2 — Local Python
```bash
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env — set ADMIN_PASSWORD at minimum
python run.py
```

### Option 3 — Production (Linux VPS)
```bash
# 1. Install dependencies
sudo apt install python3-venv redis-server nginx certbot python3-certbot-nginx

# 2. Set up app
git clone <repo> /var/www/campuspoll
cd /var/www/campuspoll
python3 -m venv venv
venv/bin/pip install -r requirements.txt

# 3. Configure
cp .env.example .env
nano .env  # Set all values, FLASK_ENV=production

# 4. Install services
sudo cp deploy/nginx.conf /etc/nginx/sites-available/campuspoll
sudo ln -s /etc/nginx/sites-available/campuspoll /etc/nginx/sites-enabled/
sudo nano /etc/nginx/sites-available/campuspoll  # Replace your-domain.com
sudo certbot --nginx -d your-domain.com
sudo cp deploy/campuspoll.service /etc/systemd/system/
sudo cp deploy/campuspoll-celery.service /etc/systemd/system/
sudo cp deploy/campuspoll-beat.service /etc/systemd/system/
sudo systemctl enable --now campuspoll campuspoll-celery campuspoll-beat nginx
```

---

## Default Admin
- **Email**: set via `ADMIN_EMAIL` in `.env` (default: admin@campuspoll.com)
- **Password**: set via `ADMIN_PASSWORD` in `.env` — **required, no default**

---

## Environment Variables

| Variable | Required | Description |
|----------|----------|-------------|
| `SECRET_KEY` | ✅ | Long random string — use `python -c "import secrets; print(secrets.token_hex(32))"` |
| `ADMIN_PASSWORD` | ✅ | Initial admin password |
| `DATABASE_URL` | ✅ prod | Default: `sqlite:///campuspoll.db`. Prod: `postgresql://user:pass@host/db` |
| `MAIL_USERNAME` | For email | Gmail address |
| `MAIL_PASSWORD` | For email | Gmail App Password (not your login password) |
| `CELERY_BROKER_URL` | For async | Default: `redis://localhost:6379/0` |
| `FLASK_ENV` | Prod | Set to `production` to enable HTTPS cookies |
| `ADMIN_EMAIL` | Optional | Default: `admin@campuspoll.com` |
| `LOGIN_MAX_ATTEMPTS` | Optional | Default: `5` |
| `LOGIN_BLOCK_MINUTES` | Optional | Default: `15` |

---

## Features

### Security
- Passwords hashed with Werkzeug (bcrypt-style)
- Email verification on registration
- Rate limiting — IP blocked after 5 failed logins for 15 min
- CSRF protection on all forms (Flask-WTF)
- Login attempt tracking with IP logging
- TOTP 2FA (Google Authenticator / Authy)
- Role-based access control (Admin / Candidate / Voter)
- Session timeout (30 min) with JS warning at 25 min
- `HttpOnly`, `SameSite=Lax`, `Secure` (production) cookie flags
- No secret key default — app refuses to start without one in production
- Input sanitization via Bleach on all user content

### Elections
- Auto status updates every minute (Celery Beat in prod, APScheduler in dev)
- Duplicate vote prevention (DB UniqueConstraint + app-level check)
- Self-vote prevention
- Voting window enforcement
- Vote count computed from Vote table — no denormalized counter
- Vote confirmation page after casting ballot

### Notifications & Email
- In-app bell with unread count, auto-polls every 60s
- Async emails via Celery + Redis (with retry on failure)
- Events: nomination approved/rejected, voting open, results published
- Mark read / mark all read

### Admin Panel
- Create, edit, delete elections (with guards on active/completed)
- Approve/reject nominations
- Post and delete announcements
- Paginated users with search/filter (dept, role)
- Bulk CSV student import + CSV export
- Publish results + notify all voters
- Export results as PDF (ReportLab)
- Full paginated audit log with search

### Analytics
- Page views, clicks, load times, form submissions
- Voter turnout per election, department-wise distribution
- Votes over time, daily signups
- Login success/failure rate
- User behaviour event breakdown

### Deployment
- Docker + docker-compose
- Nginx config with SSL, security headers, static file serving
- Systemd service files for Gunicorn, Celery worker, Celery Beat
- File-based rotating log (5MB × 5 files)
- PostgreSQL pool config (pool_size=10, max_overflow=20)

---

## Running Tests
```bash
pytest tests/ -v                          # all tests
pytest tests/ --cov=. --cov-report=html  # with HTML coverage report
```

**72 tests | 62% coverage**

---

## CSV Import Format
```csv
name,email,student_id,department,year
Aryan Sharma,aryan@college.edu,CS2021001,Computer Science,3rd Year
```

---

## Gmail Setup
1. Enable 2FA on your Google account
2. Go to Google Account → Security → App Passwords
3. Generate a password for "Mail"
4. Set `MAIL_USERNAME` and `MAIL_PASSWORD` in `.env`

---

## Production Security Checklist
- [ ] `SECRET_KEY` is a long random string (not the example)
- [ ] `ADMIN_PASSWORD` is strong and changed after first login
- [ ] `FLASK_ENV=production` in `.env`
- [ ] `FLASK_DEBUG=False`
- [ ] Using PostgreSQL, not SQLite
- [ ] Nginx + SSL certificate installed
- [ ] Redis running for Celery
- [ ] All systemd services enabled and running
- [ ] Firewall allows only 80/443 (not 5000 directly)
