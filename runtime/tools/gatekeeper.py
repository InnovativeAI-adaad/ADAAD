from __future__ import annotations

import json
import shutil
import subprocess
import hashlib
from pathlib import Path
from typing import Dict, List, Tuple

from runtime.logger import get_logger
from runtime.tools.agent_validator import validate_agents
from security.cryovant import Cryovant

logger = get_logger(component="gatekeeper")


def _run_tests() -> Tuple[bool, str]:
    try:
        result = subprocess.run(
            ["python", "-m", "unittest"], capture_output=True, text=True, check=True  # noqa: S603
        )
        summary_hash = hashlib.sha256((result.stdout + result.stderr).encode("utf-8")).hexdigest()
        return True, summary_hash
    except subprocess.CalledProcessError as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        summary_hash = hashlib.sha256((stdout + stderr).encode("utf-8")).hexdigest()
        return False, summary_hash


def _rejection_lineage(ticket_id: str, agent_id: str, reason: str, test_summary_hash: str) -> str:
    seed = f"{ticket_id}|{agent_id}|{reason}|{test_summary_hash}"
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def _emit_rejection(
    cryo: Cryovant, ticket_id: str, deliverable: str, agent_id: str, reason: str, test_summary_hash: str
) -> None:
    lineage_hash = _rejection_lineage(ticket_id, agent_id, reason, test_summary_hash)
    cryo.promotion(
        ticket_id=ticket_id,
        deliverable=deliverable,
        agent_id=agent_id,
        lineage_hash=lineage_hash,
        outcome="rejected",
        detail={
            "rejection_reason": reason,
            "test_summary_hash": test_summary_hash,
        },
    )


def process_review_tickets(review_dir: Path = Path("data/work/02_review")) -> List[Path]:
    review_dir.mkdir(parents=True, exist_ok=True)
    inbox = Path("data/work/00_inbox")
    done = Path("data/work/03_done")
    inbox.mkdir(parents=True, exist_ok=True)
    done.mkdir(parents=True, exist_ok=True)

    cryo = Cryovant()
    promoted: List[Path] = []

    for ticket_path in review_dir.glob("*.json"):
        try:
            ticket = json.loads(ticket_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover - defensive
            ticket_id = ticket_path.stem
            logger.error("ticket parse failed", error=exc, ticket=str(ticket_path))
            summary_hash = hashlib.sha256(str(exc).encode("utf-8")).hexdigest()
            _emit_rejection(
                cryo=cryo,
                ticket_id=ticket_id,
                deliverable="",
                agent_id="unknown",
                reason="ticket_parse_failed",
                test_summary_hash=summary_hash,
            )
            ticket_path.rename(inbox / ticket_path.name)
            continue

        ticket_id = ticket.get("id", ticket_path.stem)
        logger.info("review start", ticket=ticket_id)

        tests_ok, test_hash = _run_tests()
        if not tests_ok:
            logger.error("tests failed", ticket=ticket_id)
            _emit_rejection(
                cryo=cryo,
                ticket_id=ticket_id,
                deliverable=ticket.get("title", ""),
                agent_id="unknown",
                reason="tests_failed",
                test_summary_hash=test_hash,
            )
            ticket_path.rename(inbox / ticket_path.name)
            continue

        ok_agents, bad_agents = validate_agents(Path("app/agents/active"))
        if bad_agents:
            validation_detail = {
                "missing": [r.missing for r in bad_agents],
                "schema_violations": [r.schema_violations for r in bad_agents],
                "agents": [r.path.name for r in bad_agents],
            }
            validation_hash = hashlib.sha256(json.dumps(validation_detail, sort_keys=True).encode("utf-8")).hexdigest()
            logger.error("agent validation failed", ticket=ticket_id, detail=validation_detail)
            _emit_rejection(
                cryo=cryo,
                ticket_id=ticket_id,
                deliverable=ticket.get("title", ""),
                agent_id="invalid_agents",
                reason="agent_validation_failed",
                test_summary_hash=validation_hash,
            )
            ticket_path.rename(inbox / ticket_path.name)
            continue

        for result in ok_agents:
            cryo.promotion(
                ticket_id=ticket_id,
                deliverable=ticket.get("title", ""),
                agent_id=result.path.name,
                lineage_hash=result.lineage_hash or "",
                outcome="accepted",
                detail={"rejection_reason": None, "test_summary_hash": test_hash},
            )

        shutil.move(str(ticket_path), done / ticket_path.name)
        promoted.append(done / ticket_path.name)
        logger.audit("promotion", actor="gatekeeper", outcome="ok", ticket=ticket_id)

    return promoted
