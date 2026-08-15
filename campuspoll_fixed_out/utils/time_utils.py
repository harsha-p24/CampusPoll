"""
India Standard Time helpers.

CampusPoll's admin forms use HTML `datetime-local` inputs, which submit
whatever wall-clock time the admin typed with NO timezone info attached
(e.g. "2026-07-01T10:00"). Since this app is built for an Indian campus,
that value is always intended to mean IST (UTC+5:30).

Everywhere the app needs "the current time" to compare against those
stored election dates (nomination windows, voting windows, etc.), it must
use IST — NOT UTC — or windows will appear to open/close up to 5.5 hours
"late" relative to what the admin actually intended.

Use `now_ist()` anywhere you need "now" for that kind of comparison.
"""
from datetime import datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def now_ist():
    """Current time in IST, returned as a naive datetime so it compares
    directly with the naive IST values stored from admin date/time forms."""
    return datetime.now(IST).replace(tzinfo=None)
