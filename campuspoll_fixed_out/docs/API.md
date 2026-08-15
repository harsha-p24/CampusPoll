# CampusPoll API Reference

## Public Routes
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/` | Homepage |
| GET/POST | `/register` | Register (rate limited: 10/hour) |
| GET/POST | `/login` | Login (rate limited: 30/min) |
| GET | `/health` | `[JSON]` Health check |
| GET | `/health/queue` | `[JSON]` Queue depths |
| GET | `/candidate/<id>` | Candidate profile |

## Voter Routes (login required)
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/dashboard` | Election list |
| GET | `/election/<id>` | Election detail + voting form |
| POST | `/vote/<id>` | Cast vote |
| GET | `/results/<id>` | Published results |
| GET | `/election/<id>/live-counts` | `[JSON]` Real-time vote counts (polls every 15s) |
| GET | `/profile` | User profile + voting history |
| GET | `/notifications/` | `[JSON]` Notifications |

## Admin Routes (/admin, admin role only)
| Method | Route | Description |
|--------|-------|-------------|
| GET | `/admin/dashboard` | Overview + announcements |
| GET/POST | `/admin/elections/create` | Create election |
| GET/POST | `/admin/elections/<id>/edit` | Edit election |
| POST | `/admin/elections/<id>/delete` | Delete election |
| GET | `/admin/elections/<id>/publish-results` | Publish (queued via Celery) |
| GET | `/admin/elections/<id>/export-pdf` | Download PDF |
| GET | `/admin/users` | User management |
| GET/POST | `/admin/users/import-csv` | Bulk import |
| GET | `/admin/users/export-csv` | Export CSV |
| GET | `/admin/audit-log` | Full audit trail |
| GET | `/analytics/dashboard` | Analytics charts |

## Health Response
```json
{
  "status": "ok",
  "version": "5.0.0",
  "uptime_seconds": 3600,
  "checks": {
    "database": {"status": "ok"},
    "redis": {"status": "ok", "used_memory_mb": 12.4},
    "celery_worker": {"status": "ok", "last_heartbeat": "2024-04-25T10:29:45+00:00"},
    "disk": {"status": "ok", "free_gb": 45.2, "free_pct": 45.2}
  }
}
```
