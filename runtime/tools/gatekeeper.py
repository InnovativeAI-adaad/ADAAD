from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Dict, List

from runtime.logger import get_logger
from runtime.tools.agent_validator import validate_agents
from security.cryovant import Cryovant

logger = get_logger(component="gatekeeper")


def _run_tests() -> bool:
    try:
        subprocess.check_call(["python", "-m", "unittest"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except subprocess.CalledProcessError:
        return False


def process_review_tickets(review_dir: Path = Path("data/work/02_review")) -> List[Path]:
    review_dir.mkdir(parents=True, exist_ok=True)
    inbox = Path("data/work/00_inbox")
    done = Path("data/work/03_done")
    inbox.mkdir(parents=True, exist_ok=True)
    done.mkdir(parents=True, exist_ok=True)

    cryo = Cryovant(Path("security/ledger"), Path("security/keys"))
    promoted: List[Path] = []

    for ticket_path in review_dir.glob("*.json"):
        try:
            ticket = json.loads(ticket_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            logger.error("ticket parse failed", error=exc, ticket=str(ticket_path))
            ticket_path.rename(inbox / ticket_path.name)
            continue

        ticket_id = ticket.get("id", ticket_path.stem)
        logger.info("review start", ticket=ticket_id)

        if not _run_tests():
            logger.error("tests failed", ticket=ticket_id)
            ticket_path.rename(inbox / ticket_path.name)
            continue

        ok_agents, bad_agents = validate_agents(Path("app/agents/active"))
        if bad_agents:
            logger.error("agent validation failed", ticket=ticket_id, missing=[r.missing for r in bad_agents])
            ticket_path.rename(inbox / ticket_path.name)
            continue

        for result in ok_agents:
            cryo.certify(agent_id=result.path.name, lineage_hash=result.lineage_hash or "", outcome="accepted")

        shutil.move(str(ticket_path), done / ticket_path.name)
        promoted.append(done / ticket_path.name)
        logger.audit("promotion", actor="gatekeeper", outcome="ok", ticket=ticket_id)

    return promoted
