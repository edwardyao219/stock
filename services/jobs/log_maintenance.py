from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path


def list_expired_logs(log_dir: Path, *, retention_days: int) -> list[Path]:
    cutoff = datetime.now() - timedelta(days=retention_days)
    return sorted(
        path
        for path in log_dir.glob("*.log")
        if path.is_file() and datetime.fromtimestamp(path.stat().st_mtime) < cutoff
    )


def main() -> None:
    parser = argparse.ArgumentParser(description="List expired local runtime logs.")
    parser.add_argument("--log-dir", type=Path, default=Path("logs"))
    parser.add_argument("--retention-days", type=int, default=14)
    args = parser.parse_args()
    for path in list_expired_logs(args.log_dir, retention_days=args.retention_days):
        print(path)


if __name__ == "__main__":
    main()
