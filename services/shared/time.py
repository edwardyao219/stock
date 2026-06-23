from datetime import datetime
from zoneinfo import ZoneInfo

from services.shared.config import get_settings


def now_local() -> datetime:
    return datetime.now(ZoneInfo(get_settings().timezone))
