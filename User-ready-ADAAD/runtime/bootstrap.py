from pathlib import Path

def init_logging(p: Path):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.touch(exist_ok=True)

def init_runtime_environment(base: Path):
    for d in ["reports", "security/ledger", "security/keys", "app/agents/lineage"]:
        (base / d).mkdir(parents=True, exist_ok=True)
