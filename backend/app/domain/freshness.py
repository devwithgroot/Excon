from datetime import datetime, timedelta, timezone

from app.domain.evidence import Freshness

FRESHNESS_DAYS = 90


def classify_freshness(
    published_at: datetime | None,
    *,
    now: datetime | None = None,
    max_age_days: int = FRESHNESS_DAYS,
) -> Freshness:
    if published_at is None:
        return Freshness.unknown
    current = now or datetime.now(timezone.utc)
    dated = published_at
    if dated.tzinfo is None:
        dated = dated.replace(tzinfo=timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    if current - dated <= timedelta(days=max_age_days):
        return Freshness.fresh
    return Freshness.stale


def is_usable(freshness: Freshness) -> bool:
    return freshness != Freshness.stale
