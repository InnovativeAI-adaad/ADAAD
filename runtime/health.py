from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from runtime.tools.agent_validator import validate_agents

REQUIRED_DIRS = [
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


def _missing_dirs(required: List[str]) -> List[str]:
    return [d for d in required if not Path(d).exists()]


def check_paths() -> Dict[str, object]:
    missing = _missing_dirs(REQUIRED_DIRS)
    return {"structure_ok": not missing, "missing": missing}


def check_ledger() -> Dict[str, object]:
    ledger_dir = Path("security/ledger")
    ledger_dir.mkdir(parents=True, exist_ok=True)
    temp = ledger_dir / ".write_probe"
    ok = False
    detail: str
    try:
        temp.write_text("probe", encoding="utf-8")
        ok = True
        detail = str(ledger_dir)
    except Exception as exc:  # pragma: no cover - defensive
        detail = str(exc)
    finally:
        if temp.exists():
            try:
                temp.unlink()
            except Exception:
                pass
    return {"ledger_ok": ok, "ledger_path": detail}


def check_architect_scan() -> Dict[str, object]:
    agents_root = Path("app/agents")
    ok_agents, bad_agents = validate_agents(agents_root)
    present = [res.path.name for res in ok_agents] + [res.path.name for res in bad_agents]
    invalid = {
        res.path.name: {"missing": res.missing, "schema_violations": res.schema_violations} for res in bad_agents
    }
    return {"architect_scan": {"agent_dirs": sorted(present), "invalid": invalid}}


def check_dream_discovery() -> Dict[str, object]:
    dream_paths = [p for p in [Path("app/dream_mode.py"), Path("app/beast_mode_loop.py")] if p.exists()]
    return {"dream_ready": all(p.exists() for p in dream_paths), "discovered": [str(p) for p in dream_paths]}


def health_snapshot() -> Dict[str, object]:
    status: Dict[str, object] = {}
    status.update(check_paths())
    status.update(check_ledger())
    status.update(check_architect_scan())
    status.update(check_dream_discovery())
    return status
