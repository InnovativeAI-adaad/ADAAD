from __future__ import annotations

from pathlib import Path
from typing import Dict, List

ELEMENT_ID = "wood"


class ArchitectAgent:
    """Wood element: scans agent metadata and reports structural gaps."""

    def __init__(self, agents_root: Path | None = None) -> None:
        self.agents_root = agents_root or Path("app/agents")

    def scan(self) -> Dict[str, object]:
        present: List[str] = []
        invalid: Dict[str, List[str]] = {}
        required = {"meta.json", "dna.json", "certificate.json"}

        if not self.agents_root.exists():
            return {"present": present, "invalid": invalid, "missing_files": invalid}

        for entry in self.agents_root.iterdir():
            if entry.is_dir():
                files = {p.name for p in entry.iterdir() if p.is_file()}
                missing = sorted(list(required - files))
                present.append(entry.name)
                if missing:
                    invalid[entry.name] = missing

        return {
            "present": sorted(present),
            "invalid": invalid,
        }


# === HE65 compat: governance hooks for BeastLoop ===
# BeastLoop expects these methods. Older ArchitectAgent versions may not have them.
# Provide safe defaults: return empty proposals, export is no-op.
try:
    ArchitectAgent
except NameError:
    ArchitectAgent = None

def _aa_governance_sweep(self):
    return []

def _aa_export_proposals(self, proposals):
    return None

def _aa_audit_system_layers(self):
    return []

def _aa_export_system_proposals(self, proposals):
    return None

if ArchitectAgent is not None:
    for _name, _fn in (
        ("governance_sweep", _aa_governance_sweep),
        ("export_proposals", _aa_export_proposals),
        ("audit_system_layers", _aa_audit_system_layers),
        ("export_system_proposals", _aa_export_system_proposals),
    ):
        if not hasattr(ArchitectAgent, _name):
            setattr(ArchitectAgent, _name, _fn)
