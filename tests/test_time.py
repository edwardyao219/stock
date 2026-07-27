from datetime import UTC, datetime


def test_now_utc_returns_naive_utc_datetime() -> None:
    from services.shared.time import now_utc

    value = now_utc()

    assert value.tzinfo is None
    assert abs(value - datetime.now(UTC).replace(tzinfo=None)).total_seconds() < 1
