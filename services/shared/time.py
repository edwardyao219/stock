from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from services.shared.config import get_settings


def now_local() -> datetime:
    return datetime.now(ZoneInfo(get_settings().timezone))


def now_utc() -> datetime:
    return datetime.now(UTC).replace(tzinfo=None)
