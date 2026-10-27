from datetime import datetime, timedelta, timezone

from app.domain.evidence import Freshness
from app.domain.freshness import classify_freshness, is_usable


def test_fresh_within_90_days() -> None:
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    published = now - timedelta(days=30)
    assert classify_freshness(published, now=now) == Freshness.fresh
    assert is_usable(Freshness.fresh)


def test_stale_older_than_90_days() -> None:
    now = datetime(2026, 10, 27, tzinfo=timezone.utc)
    published = now - timedelta(days=120)
    assert classify_freshness(published, now=now) == Freshness.stale
    assert not is_usable(Freshness.stale)


def test_unknown_when_no_publish_date() -> None:
    assert classify_freshness(None) == Freshness.unknown
    assert is_usable(Freshness.unknown)
