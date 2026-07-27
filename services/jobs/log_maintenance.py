from __future__ import annotations

import argparse
import gzip
import shutil
from datetime import datetime, timedelta
from pathlib import Path


def list_expired_logs(log_dir: Path, *, retention_days: int) -> list[Path]:
    cutoff = datetime.now() - timedelta(days=retention_days)
    return sorted(
        path
        for path in log_dir.glob("*.log")
        if path.is_file() and datetime.fromtimestamp(path.stat().st_mtime) < cutoff
    )


def archive_expired_logs(paths: list[Path]) -> list[Path]:
    archived: list[Path] = []
    for path in paths:
        archive_path = path.with_suffix(path.suffix + ".gz")
        with path.open("rb") as source, gzip.open(archive_path, "wb") as target:
            shutil.copyfileobj(source, target)
        path.unlink()
        archived.append(archive_path)
    return archived


def main() -> None:
    parser = argparse.ArgumentParser(description="List or archive expired local runtime logs.")
    parser.add_argument("--log-dir", type=Path, default=Path("logs"))
    parser.add_argument("--retention-days", type=int, default=14)
    parser.add_argument("--archive", action="store_true")
    args = parser.parse_args()
    paths = list_expired_logs(args.log_dir, retention_days=args.retention_days)
    if args.archive:
        paths = archive_expired_logs(paths)
    for path in paths:
        print(path)


if __name__ == "__main__":
    main()
