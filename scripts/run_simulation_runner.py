#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""CI entrypoint for deterministic simulation runner."""

from runtime.evolution.simulation_runner import main


if __name__ == "__main__":
    raise SystemExit(main())
