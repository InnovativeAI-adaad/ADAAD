"""Placeholder for mirroring artifacts to GitHub.

This stub keeps the public interface stable while allowing downstream
projects to implement their own synchronization logic.
"""
from __future__ import annotations

from pathlib import Path


def find_logs(base: Path | str = "data/logs") -> list[Path]:
    base_path = Path(base)
    return sorted(base_path.glob("*.jsonl")) if base_path.exists() else []


def main() -> None:  # pragma: no cover - utility stub
    logs = find_logs()
    for log in logs:
        print(f"[SYNC] would push {log}")


if __name__ == "__main__":
    main()
