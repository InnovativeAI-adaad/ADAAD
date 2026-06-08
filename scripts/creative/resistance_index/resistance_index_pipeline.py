#!/usr/bin/env python3
"""
resistance_index - Creative Output Pipeline (Governed)
Next piece in the American Shame Tapestry series after the_unburied.

Registered live via: python scripts/creative/creative_output.py --action register --project resistance_index
Now fully realized as a polished hyper-stylized example (ledger / index corruption motif).
"""

import argparse
import json
from datetime import datetime
from pathlib import Path

LEDGER_PATH = Path("data/creative_ledger.jsonl")


def log_to_ledger(entry: dict):
    entry["timestamp"] = datetime.utcnow().isoformat() + "Z"
    entry["source"] = "resistance_index_pipeline"
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")


def generate(mode: str, assets_dir: str = None):
    print(f"[resistance_index] Generating in mode: {mode}")
    if mode == "advanced":
        print("  → Launching hyper-stylized ledger corruption render (typewriter index tearing, vertical roll glitches, counting names being erased)")
        print("  → Execute: scripts/creative/resistance_index/render_resistance_index.sh")
        log_to_ledger({
            "action": "advanced_generation_invoked",
            "project": "resistance_index",
            "mode": "advanced",
            "renderer": "scripts/creative/resistance_index/render_resistance_index.sh"
        })
    elif mode == "manifest":
        create_manifest()
    else:
        print(f"  → Mode '{mode}' — full advanced output lives in render_resistance_index.sh")


def create_manifest(asset_name: str = "resistance_index_advanced.mp4"):
    manifest = {
        "artifact_id": "creative.resistance_index.advanced_example",
        "title": "Resistance Index (Advanced)",
        "series": "American Shame Tapestry",
        "version": "0.2",
        "duration_seconds": 105,
        "resolution": "1920x1080",
        "effects": [
            "vertical roll + data-tear index corruption (multi-split difference/addition blends)",
            "typewriter-list kinetic text (mono font, staggered list items that get redacted/erased)",
            "dual-layer counting / ledger text with independent high-freq ghost layers",
            "real-time name erasure motif (NO. 184x lines being overwritten by glitch)",
            "extreme geq chromatic aberration + heavy archival data-mosh grain"
        ],
        "sections": [
            {"name": "Index Opening", "start": 0, "end": 34, "text": "RESISTANCE INDEX (primary + red tear)"},
            {"name": "Name List Corruption", "start": 11, "end": 58, "text": "NO. 1847-1849 typewriter lines + erasure"},
            {"name": "Ledger Lie Climax", "start": 31, "end": 71, "text": "THE LEDGER IS A LIE (dual kinetic)"},
            {"name": "Total Erasure", "start": 69, "end": 105, "text": "NO NAMES — NO NUMBERS + THE INDEX REMEMBERS"}
        ],
        "governed_under": "ADAAD Creative Output Workflow (register + advanced)",
        "renderer": "scripts/creative/resistance_index/render_resistance_index.sh",
        "docs": "scripts/creative/resistance_index/docs/advanced_effects.md",
        "ledger_reference": "data/creative_ledger.jsonl",
        "created": "2026-05-28"
    }
    out_path = Path("artifacts/creative/resistance_index/resistance_index_advanced.manifest.json")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(manifest, indent=2))
    print(f"Manifest written: {out_path}")
    log_to_ledger({"action": "manifest_created", "project": "resistance_index", "asset": str(out_path)})


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="full", choices=["full", "advanced", "manifest"])
    parser.add_argument("--assets", type=str)
    parser.add_argument("--asset-name", default="resistance_index_advanced.mp4")
    args = parser.parse_args()
    if args.mode == "manifest":
        create_manifest(args.asset_name)
    else:
        generate(args.mode, args.assets)
