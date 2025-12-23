from __future__ import annotations

from pathlib import Path
from typing import Dict

from runtime.logger import get_logger
from security.cryovant import Cryovant


def check_paths() -> Dict[str, object]:
    required = [
        "app",
        "runtime",
        "security",
        "tests",
        "docs",
        "data",
        "reports",
        "releases",
        "experiments",
        "scripts",
        "ui",
        "tools",
        "archives",
    ]
    missing = [p for p in required if not Path(p).exists()]
    return {
        "structure_ok": not missing,
        "missing": missing,
    }


def check_ledger() -> Dict[str, object]:
    ledger_dir = Path("security/ledger")
    temp = ledger_dir / ".write_probe"
    try:
        ledger_dir.mkdir(parents=True, exist_ok=True)
        temp.write_text("ok", encoding="utf-8")
        temp.unlink(missing_ok=True)
        ok = True
        detail = str(ledger_dir)
    except Exception as exc:
        ok = False
        detail = str(exc)
    return {
        "ledger_ok": ok,
        "ledger_path": detail,
    }


def check_architect_scan() -> Dict[str, object]:
    """
    He65 rule:
      - app/agents/<bucket>/ is a container
      - app/agents/<bucket>/<agent_name>/ is an agent directory
    """
    from app.agents.contract import validate_agent_contract

    agents_root = Path("app/agents")
    present = []
    invalid = {}

    if not agents_root.is_dir():
        return {
            "architect_scan": {
                "agent_dirs": [],
                "invalid": {"app/agents": {"missing": ["(dir)"], "schema_violations": []}},
            }
        }

    for bucket in sorted(agents_root.iterdir(), key=lambda p: p.name):
        if not bucket.is_dir() or bucket.name == "__pycache__":
            continue

        for agent_dir in sorted(bucket.iterdir(), key=lambda p: p.name):
            if not agent_dir.is_dir() or agent_dir.name == "__pycache__":
                continue

            rel = agent_dir.relative_to(agents_root).as_posix()
            present.append(rel)

            result = validate_agent_contract(agent_dir)
            if not result.get("ok", False):
                invalid[rel] = {
                    "missing": [],
                    "schema_violations": [
                        __import__("json").dumps(e, ensure_ascii=False)
                        for e in (result.get("errors") or [])
                    ],
                }

    return {
        "architect_scan": {
            "agent_dirs": sorted(present),
            "invalid": invalid,
        }
    }


def check_dream_discovery() -> Dict[str, object]:
    paths = [Path("app/dream_mode.py"), Path("app/beast_mode_loop.py")]
    return {
        "dream_ready": all(p.exists() for p in paths),
        "discovered": [str(p) for p in paths if p.exists()],
    }


def health_snapshot() -> Dict[str, object]:
    status: Dict[str, object] = {}
    status.update(check_paths())
    status.update(check_ledger())
    status.update(check_architect_scan())
    status.update(check_dream_discovery())
    return status
