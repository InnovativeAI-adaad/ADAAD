"""Lightweight entry point for running a single ADAAD cycle."""
from __future__ import annotations

from adad_core.io.health import battery_allows_run, over_cpu_limit
from adad_core.runtime.pipeline import cycle_once


def main() -> None:
    if not battery_allows_run() or over_cpu_limit():
        print("[ADAD] Skipping: battery/CPU gate")
        return
    cycle_once()
    print("[ADAD] Cycle complete")


if __name__ == "__main__":
    main()
