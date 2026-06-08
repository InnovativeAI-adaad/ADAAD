#!/usr/bin/env python3
"""
The Unburied - Creative Output Pipeline (Governed)
Next piece in the American Shame Tapestry series.

Registered through: python scripts/creative/creative_output.py --action register --project the_unburied
This is the polished "small example" demonstrating the full advanced creative workflow.
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

LEDGER_PATH = Path("data/creative_ledger.jsonl")


def log_to_ledger(entry: dict):
    entry["timestamp"] = datetime.utcnow().isoformat() + "Z"
    entry["source"] = "the_unburied_pipeline"
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def generate(mode: str, assets_dir: str = None):
    print(f"[the_unburied] Generating in mode: {mode}")
    if mode == "advanced":
        print("  → Launching hyper-stylized render (extreme redacted glitch + kinetic digging text + datamosh burial)")
        # In a full impl this would call the render script or emit it.
        # For the governed small example we point to the standalone renderer.
        print("  → Execute: scripts/creative/the_unburied/render_the_unburied.sh")
        log_to_ledger({
            "action": "advanced_generation_invoked",
            "project": "the_unburied",
            "mode": "advanced",
            "renderer": "scripts/creative/the_unburied/render_the_unburied.sh"
        })
    elif mode == "manifest":
        create_manifest()
    else:
        print(f"  → Basic mode '{mode}' — see render_the_unburied.sh for full advanced output.")


def create_manifest(asset_name: str = "the_unburied_advanced.mp4"):
    manifest = {
        "artifact_id": "creative.the_unburied.advanced_example",
        "title": "The Unburied (Advanced Small Example)",
        "series": "American Shame Tapestry",
        "version": "0.2",
        "duration_seconds": 110,
        "resolution": "1920x1080",
        "effects": [
            "multi-stage datamosh + RGB block corruption",
            "high-frequency geq chromatic aberration per section",
            "dual-layer kinetic digging text (primary + violent ghost/tear)",
            "redacted overlay with timed alpha bursts",
            "extreme archival film grain + eq crushing"
        ],
        "governed": True,
        "registered_via": "creative_output.py --action register",
        "renderer": "scripts/creative/the_unburied/render_the_unburied.sh",
        "docs": "scripts/creative/the_unburied/docs/advanced_effects.md",
        "created": "2026-05-28"
    }
    out_path = Path("artifacts/creative/the_unburied/the_unburied_advanced.manifest.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2))
    print(f"Manifest written: {out_path}")
    log_to_ledger({"action": "manifest_created", "project": "the_unburied", "asset": str(out_path)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="full", choices=["full", "advanced", "manifest"])
    parser.add_argument("--assets", type=str)
    parser.add_argument("--asset-name", default="the_unburied_advanced.mp4")
    args = parser.parse_args()
    if args.mode == "manifest":
        create_manifest(args.asset_name)
    else:
        generate(args.mode, args.assets)