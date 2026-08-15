"""
AI-based fraud detection using Isolation Forest + rule-based checks.
No labelled training data required — learns normal patterns from activity.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import List

logger = logging.getLogger(__name__)

try:
    import numpy as np
    from sklearn.ensemble import IsolationForest
    from sklearn.preprocessing import StandardScaler
    ML_AVAILABLE = True
except ImportError:
    ML_AVAILABLE = False
    logger.warning("scikit-learn not available — using rule-based detection only")


@dataclass
class FraudSignal:
    risk_score: float
    flags:      List[str] = field(default_factory=list)
    action:     str = 'allow'   # allow | flag | block


class FraudDetector:
    FLAG_THRESHOLD  = 0.40
    BLOCK_THRESHOLD = 0.75

    BOT_SIGNALS = [
        'python-requests', 'python-urllib', 'curl/', 'wget/',
        'headlesschrome', 'phantomjs', 'selenium', 'scrapy',
        'go-http-client', 'okhttp',
    ]

    def analyse_vote_attempt(self, voter_id: int, election_id: int,
                             ip_address: str, user_agent: str,
                             request_time: datetime) -> FraudSignal:
        from app import db
        from models import AnalyticsEvent, User

        flags:      List[str] = []
        risk_score: float     = 0.0

        from app import db as _fdb
        user = _fdb.session.get(User, voter_id)
        if not user:
            return FraudSignal(1.0, ['unknown_user'], 'block')

        # ── Rule 1: velocity — same IP voted in last 10 seconds ─────────
        recent = AnalyticsEvent.query.filter(
            AnalyticsEvent.ip_address == ip_address,
            AnalyticsEvent.event_type == 'vote_cast',
            AnalyticsEvent.timestamp  >= request_time - timedelta(seconds=10),
        ).count()
        if recent > 0:
            flags.append('ip_velocity_too_high')
            risk_score += 0.35

        # ── Rule 2: unusual hour (1am–5am) ───────────────────────────────
        if 1 <= request_time.hour <= 5:
            flags.append('unusual_voting_hour')
            risk_score += 0.15

        # ── Rule 3: bot / headless user-agent ───────────────────────────
        ua_lower = (user_agent or '').lower()
        if any(s in ua_lower for s in self.BOT_SIGNALS):
            flags.append('bot_user_agent')
            risk_score += 0.50

        # ── Rule 4: multiple IPs for same voter in 30-min window ─────────
        distinct_ips = (
            db.session.query(AnalyticsEvent.ip_address)
            .filter(
                AnalyticsEvent.user_id   == voter_id,
                AnalyticsEvent.timestamp >= request_time - timedelta(minutes=30),
            )
            .distinct()
            .count()
        )
        if distinct_ips > 3:
            flags.append('multiple_ips_same_session')
            risk_score += 0.30

        # ── Rule 5: same voter tried to vote twice ───────────────────────
        from models import Vote
        if Vote.query.filter_by(voter_id=voter_id, election_id=election_id).first():
            flags.append('duplicate_vote_attempt')
            risk_score += 0.60

        # ── ML layer (Isolation Forest) ──────────────────────────────────
        if ML_AVAILABLE:
            ml = self._ml_score(voter_id, ip_address, request_time, db)
            if ml > 0.6:
                flags.append('ml_anomaly_detected')
                risk_score += ml * 0.25

        risk_score = min(round(risk_score, 3), 1.0)
        action = (
            'block' if risk_score >= self.BLOCK_THRESHOLD else
            'flag'  if risk_score >= self.FLAG_THRESHOLD  else
            'allow'
        )

        self._persist(voter_id, election_id, risk_score, flags, action, db)
        return FraudSignal(risk_score, flags, action)

    # ── ML anomaly detection ─────────────────────────────────────────────

    def _ml_score(self, voter_id: int, ip_address: str,
                  request_time: datetime, db) -> float:
        from models import AnalyticsEvent
        week_ago = request_time - timedelta(days=7)
        events   = AnalyticsEvent.query.filter(
            AnalyticsEvent.timestamp >= week_ago
        ).all()
        if len(events) < 20:
            return 0.0
        try:
            rows = np.array([
                [
                    e.timestamp.hour,
                    sum(1 for x in events
                        if abs((x.timestamp - e.timestamp).total_seconds()) < 60),
                    len(set(x.ip_address for x in events
                            if x.user_id == voter_id and
                            abs((x.timestamp - e.timestamp).total_seconds()) < 1800)),
                ]
                for e in events
            ], dtype=float)

            scaler = StandardScaler()
            X      = scaler.fit_transform(rows)
            clf    = IsolationForest(contamination=0.05, random_state=42, n_estimators=50)
            clf.fit(X)

            current = scaler.transform(np.array([[
                request_time.hour,
                len([e for e in events
                     if e.ip_address == ip_address and
                     abs((e.timestamp - request_time).total_seconds()) < 60]),
                distinct_ips_window(voter_id, request_time, db),
            ]], dtype=float))
            raw = clf.score_samples(current)[0]
            return float(max(0.0, min(1.0, (-raw - 0.1) / 0.5)))
        except Exception as exc:
            logger.debug(f"ML scoring skipped: {exc}")
            return 0.0

    def _persist(self, voter_id, election_id, score, flags, action, db):
        from models import FraudLog
        try:
            db.session.add(FraudLog(
                voter_id=voter_id, election_id=election_id,
                risk_score=score, flags=','.join(flags), action=action,
            ))
            db.session.commit()
        except Exception:
            db.session.rollback()


def distinct_ips_window(voter_id: int, request_time: datetime, db) -> int:
    from models import AnalyticsEvent
    return (
        db.session.query(AnalyticsEvent.ip_address)
        .filter(
            AnalyticsEvent.user_id   == voter_id,
            AnalyticsEvent.timestamp >= request_time - timedelta(minutes=30),
        )
        .distinct().count()
    )


detector = FraudDetector()
