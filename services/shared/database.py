from collections.abc import Generator
from pathlib import Path
import logging

from sqlalchemy import create_engine
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from services.shared.config import get_settings

logger = logging.getLogger(__name__)


class Base(DeclarativeBase):
    pass


settings = get_settings()


def _create_engine():
    url = settings.database_url
    kwargs = {"pool_pre_ping": True}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}

    engine = create_engine(url, **kwargs)
    try:
        with engine.connect():
            return engine
    except SQLAlchemyError as exc:
        if url.startswith("sqlite"):
            raise
        fallback_path = Path(__file__).resolve().parents[2] / ".stock-dev.sqlite"
        fallback_url = f"sqlite:///{fallback_path}"
        logger.warning(
            "Primary database unreachable (%s). Falling back to %s.",
            exc,
            fallback_url,
        )
        return create_engine(
            fallback_url,
            pool_pre_ping=True,
            connect_args={"check_same_thread": False},
        )


engine = _create_engine()
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
