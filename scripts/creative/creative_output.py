#!/usr/bin/env python3
"""
ADAAD Creative Output Workflow Manager
Central governed tool for managing artistic/creative outputs.

Commands:
  generate    - Generate creative output for a project
  manifest    - Create manifest + ledger entry
  register    - Register a new creative project (scaffolds structure)
  list        - List registered projects
"""

import argparse
import json
import subprocess
from datetime import datetime
from pathlib import Path

LEDGER_PATH = Path("data/creative_ledger.jsonl")
PROJECTS_DIR = Path("scripts/creative")

def log_action(entry: dict):
    entry["timestamp"] = datetime.utcnow().isoformat() + "Z"
    entry["tool"] = "creative_output.py"
    LEDGER_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(LEDGER_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry, separators=(",", ":")) + "\n")

def generate(project: str, mode: str, assets_dir: Path = None):
    if project == "geography_of_ash":
        cmd = ["python", "scripts/creative/geography_of_ash_pipeline.py", "--mode", mode]
        if assets_dir:
            cmd.extend(["--assets", str(assets_dir)])
        print(f"Running: {' '.join(cmd)}")
        subprocess.run(cmd, check=True)
        log_action({
            "action": "creative_generation",
            "project": project,
            "mode": mode,
            "assets_dir": str(assets_dir) if assets_dir else None
        })
    else:
        print(f"No generator registered for project: {project}. Use 'register' first.")

def create_manifest(project: str, asset_name: str):
    if project == "geography_of_ash":
        cmd = ["python", "scripts/creative/geography_of_ash_pipeline.py", "--mode", "manifest", "--asset-name", asset_name]
        subprocess.run(cmd, check=True)
        log_action({
            "action": "manifest_created",
            "project": project,
            "asset": asset_name
        })
    else:
        print(f"No manifest handler for project: {project}")

def register_project(project_name: str):
    project_dir = PROJECTS_DIR / project_name
    if project_dir.exists():
        print(f"Project '{project_name}' already exists.")
        return

    project_dir.mkdir(parents=True)
    template = f'''#!/usr/bin/env python3
"""
{project_name} - Creative Output Pipeline (Governed)
"""

import argparse

def generate(mode: str, assets_dir: str = None):
    print(f"[{project_name}] Generating in mode: {{mode}}")
    # TODO: Implement actual generation logic here

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="full")
    parser.add_argument("--assets", type=str)
    args = parser.parse_args()
    generate(args.mode, args.assets)
'''
    (project_dir / f"{project_name}_pipeline.py").write_text(template)

    print(f"Registered new creative project: {project_name}")
    print(f"Created: {project_dir / f'{project_name}_pipeline.py'}")
    log_action({
        "action": "project_registered",
        "project": project_name
    })

def list_projects():
    print("Registered creative projects:")
    # Top-level loose pipelines (legacy)
    for f in PROJECTS_DIR.glob("*.py"):
        if "pipeline" in f.name or "creative_output" in f.name:
            continue
        print(f"  - {f.stem}")
    # Subdirectory projects (preferred pattern from register)
    for d in sorted(PROJECTS_DIR.iterdir()):
        if d.is_dir() and (d / f"{d.name}_pipeline.py").exists():
            print(f"  - {d.name} (subdir)")

def main():
    parser = argparse.ArgumentParser(description="ADAAD Governed Creative Output Workflow")
    parser.add_argument("--project", help="Creative project name")
    parser.add_argument("--action", choices=["generate", "manifest", "register", "list"], default="generate")
    parser.add_argument("--mode", default="full")
    parser.add_argument("--assets", type=Path)
    parser.add_argument("--asset-name")

    args = parser.parse_args()

    if args.action == "list":
        list_projects()
    elif args.action == "register":
        if not args.project:
            print("Error: --project <name> is required for register")
            return
        register_project(args.project)
    elif args.action == "generate":
        if not args.project:
            print("Error: --project is required")
            return
        generate(args.project, args.mode, args.assets)
    elif args.action == "manifest":
        if not args.project or not args.asset_name:
            print("Error: --project and --asset-name required for manifest")
            return
        create_manifest(args.project, args.asset_name)

if __name__ == "__main__":
    main()