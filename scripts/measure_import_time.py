# SPDX-License-Identifier: Apache-2.0
#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import re
import statistics
import subprocess
import sys
from dataclasses import dataclass

PATTERN = re.compile(r"import time:\s+\d+\s+\|\s+(\d+)\s+\|\s+(.+)")


@dataclass
class Sample:
    module: str
    cumulative_us: int


def _measure_once(module: str, env: dict[str, str]) -> Sample:
    proc = subprocess.run(
        [sys.executable, "-X", "importtime", "-c", f"import {module}"],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"import failed for {module}: {proc.stderr.splitlines()[-1] if proc.stderr else 'unknown error'}")

    cumulative_us = -1
    for line in proc.stderr.splitlines():
        match = PATTERN.search(line)
        if not match:
            continue
        parsed_module = match.group(2).strip()
        if parsed_module == module:
            cumulative_us = int(match.group(1))
    if cumulative_us < 0:
        raise RuntimeError(f"could not parse importtime output for module {module}")
    return Sample(module=module, cumulative_us=cumulative_us)


def main() -> int:
    parser = argparse.ArgumentParser(description="Measure deterministic import-time cumulative latency for selected modules.")
    parser.add_argument("--iterations", type=int, default=3)
    parser.add_argument(
        "--module",
        action="append",
        dest="modules",
        default=["server", "ui.aponi_dashboard", "app.main"],
        help="Module to import (repeatable). Defaults to server, ui.aponi_dashboard, app.main.",
    )
    args = parser.parse_args()

    env = dict(os.environ)
    env.setdefault("ADAAD_ENV", "dev")
    env.setdefault("CRYOVANT_DEV_MODE", "1")

    print("module,mean_ms,median_ms,min_ms,max_ms,runs")
    for module in args.modules:
        samples = [_measure_once(module, env).cumulative_us / 1000.0 for _ in range(args.iterations)]
        print(
            f"{module},{statistics.mean(samples):.3f},{statistics.median(samples):.3f},"
            f"{min(samples):.3f},{max(samples):.3f},{args.iterations}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
