# SPDX-License-Identifier: Apache-2.0
from __future__ import annotations

import json
from pathlib import Path

from app.api.schemas.dork_intents import DorkIntentRouteRequest
from app.orchestration.dork_intent_router import DorkIntentExecutor, DorkIntentRouter
from runtime.dork_event_stream import DorkEventStream
from runtime.governance.human_approval_gate import HumanApprovalGate
from runtime.oracle_ledger import OracleLedger


def test_router_maps_blockers_query_to_explain_blockers() -> None:
    request = DorkIntentRouteRequest(query="Any blockers stopping release right now?")
    decision = DorkIntentRouter().route(request)
    assert decision.intent == "explain_blockers"
    assert decision.marker.advisory_only is True
    assert decision.marker.actionable_next_step is False


def test_executor_emits_dork_event_stream_for_oracle_history(tmp_path: Path) -> None:
    event_stream_path = tmp_path / "dork_stream.jsonl"
    oracle_path = tmp_path / "oracle_history.jsonl"

    oracle_path.write_text(
        "\n".join(
            [
                json.dumps({"schema_version": "71.1", "query": "divergence", "answer": {"message": "ok"}}),
                json.dumps({"schema_version": "71.1", "query": "performance", "answer": {"message": "ok2"}}),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    executor = DorkIntentExecutor(event_stream=DorkEventStream(path=event_stream_path))
    executor._oracle_ledger = OracleLedger(path=oracle_path)
    executor._approval_gate = HumanApprovalGate(
        queue_path=tmp_path / "approvals.jsonl",
        audit_path=tmp_path / "audit.jsonl",
        index_path=tmp_path / "index.json",
    )

    request = DorkIntentRouteRequest(query="open oracle history", limit=1)
    decision = DorkIntentRouter().route(request)

    bundle = executor.execute(request=request, decision=decision)

    assert bundle.intent == "open_oracle_history"
    assert bundle.response["record_count"] == 1
    assert bundle.marker.advisory_only is True
    assert bundle.trust_metadata.mode == "retrieval"
    assert bundle.trust_metadata.snapshot_freshness == "fresh"
    assert bundle.trust_metadata.data_sources_used
    assert "since_last_10_oracle_calls" in bundle.response
    assert "since_last_10_summary" in bundle.response["since_last_10_oracle_calls"]

    lines = event_stream_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    event = json.loads(lines[0])
    assert event["event_type"] == "dork_intent_executed.v1"
    assert event["intent"] == "open_oracle_history"
    assert event["bundle_digest"] == bundle.bundle_digest
    assert event["trust_metadata"]["mode"] == "retrieval"


def test_executor_interprets_epoch_delta_and_persists_structured_event(tmp_path: Path) -> None:
    event_stream_path = tmp_path / "dork_stream.jsonl"
    executor = DorkIntentExecutor(event_stream=DorkEventStream(path=event_stream_path))

    before_snapshot = {
        "governance": {"locked": False},
        "replay": {"divergence": 0},
        "readiness": {"readiness_score": 0.92, "blockers": []},
        "mutation": {"total": 1},
    }
    after_snapshot = {
        "governance": {"locked": True},
        "replay": {"divergence": 2},
        "readiness": {"readiness_score": 0.75, "blockers": ["docs_out_of_sync"]},
        "mutation": {"total": 6},
    }

    request = DorkIntentRouteRequest(
        query="What changed since last epoch?",
        before_snapshot=before_snapshot,
        after_snapshot=after_snapshot,
    )
    decision = DorkIntentRouter().route(request)

    bundle = executor.execute(request=request, decision=decision)

    assert bundle.intent == "interpret_epoch_delta"
    assert bundle.response["card"]["title"] == "What changed since last epoch?"
    assert bundle.response["interpretation"]["risk_level"] in {"high", "critical"}

    events = [json.loads(line) for line in event_stream_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(events) == 2
    assert events[0]["event_type"] == "dork_intent_executed.v1"
    assert events[1]["event_type"] == "dork_snapshot_interpreted.v1"
    assert events[1]["interpretation"]["risk_level"] in {"high", "critical"}
