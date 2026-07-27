from datetime import datetime, timedelta


def test_list_expired_logs_only_selects_named_old_log_files(tmp_path) -> None:
    from services.jobs.log_maintenance import list_expired_logs

    old_log = tmp_path / "celery-worker.log"
    old_log.write_text("old")
    old_time = (datetime.now() - timedelta(days=20)).timestamp()
    old_log.touch()
    import os

    os.utime(old_log, (old_time, old_time))
    (tmp_path / "notes.txt").write_text("keep")
    (tmp_path / "api.log").write_text("new")

    assert list_expired_logs(tmp_path, retention_days=14) == [old_log]
