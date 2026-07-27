from datetime import UTC, datetime


def test_now_utc_returns_naive_utc_datetime() -> None:
    from services.shared.time import now_utc

    value = now_utc()

    assert value.tzinfo is None
    assert abs(value - datetime.now(UTC).replace(tzinfo=None)).total_seconds() < 1


def test_orm_timestamp_defaults_use_shared_utc_clock() -> None:
    from services.shared.models import Security
    from services.shared.time import now_utc

    assert Security.__table__.c.created_at.default.arg.__name__ == now_utc.__name__
    assert Security.__table__.c.updated_at.default.arg.__name__ == now_utc.__name__
