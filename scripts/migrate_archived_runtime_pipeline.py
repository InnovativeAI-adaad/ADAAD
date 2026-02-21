# SPDX-License-Identifier: Apache-2.0
"""Migrate archived adad_core runtime pipeline references to evolution kernel API."""

from __future__ import annotations

import json

from runtime import ROOT_DIR


def build_mapping() -> dict[str, str]:
    return {
        "archives/adad_core/runtime/pipeline.py:cycle_once": "runtime/evolution/evolution_kernel.py:run_cycle",
        "archives/adad_core/eval/fitness.py:evaluate_agent": "runtime/evolution/economic_fitness.py:EconomicFitnessEvaluator.evaluate",
        "archives/adad_core/runtime/sandbox.py:run_script": "runtime/evolution/evolution_kernel.py:execute_in_sandbox",
    }


def main() -> int:
    output = ROOT_DIR / "reports" / "migration" / "archived_runtime_pipeline_mapping.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(build_mapping(), indent=2, sort_keys=True), encoding="utf-8")
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
