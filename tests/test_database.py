import pytest

from services.shared import database


def test_require_primary_database_blocks_fallback(monkeypatch) -> None:
    monkeypatch.setattr(database, "_ENGINE_FALLBACK_ACTIVE", True)
    monkeypatch.setattr(database, "_ACTIVE_DATABASE_URL", "sqlite:////tmp/stock-dev.sqlite")

    with pytest.raises(RuntimeError, match="run_pipeline"):
        database.require_primary_database("run_pipeline")


def test_require_primary_database_allows_primary(monkeypatch) -> None:
    monkeypatch.setattr(database, "_ENGINE_FALLBACK_ACTIVE", False)

    database.require_primary_database("run_pipeline")
