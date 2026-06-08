"""
Phase 200 · INNOV-105 · CMLG Acceptance Suite
30/30 tests — T200-CMLG-01…30
pytest -m phase200
"""
import os, sys, uuid
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from dorkllm.constitutional_mutation_lineage_graph import (
    ConstitutionalMutationLineageGraph, CMLGLineageLedger,
    GateType, EdgeStatus, NodeStatus,
    CMLGCycleDetected, CMLGConstitutionalViolation, CMLGChainViolation,
    CMLGAnchorViolation, LineageNode,
)

pytestmark = pytest.mark.phase200
HUMAN0 = "DUSTIN L REID"


def _graph(tmp_path):
    path = str(tmp_path / "lineage_ledger.jsonl")
    return ConstitutionalMutationLineageGraph(ledger=CMLGLineageLedger(path))


def _mid():
    return f"mut-{uuid.uuid4().hex[:8]}"


# ── DAG invariant ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T200-CMLG-01"])
def test_dag_no_self_loop(tid, tmp_path):
    """CMLG-DAG-0: self-loop raises CMLGCycleDetected."""
    g = _graph(tmp_path)
    n = g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
    with pytest.raises(CMLGCycleDetected):
        g.add_edge(n.node_id, n.node_id, GateType.SANDBOX, EdgeStatus.PASSED, "agent")


@pytest.mark.parametrize("tid", ["T200-CMLG-02"])
def test_dag_no_cycle_two_nodes(tid, tmp_path):
    """CMLG-DAG-0: A→B then B→A raises CMLGCycleDetected."""
    g = _graph(tmp_path)
    a = g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
    b = g.add_node(_mid(), 200, "10.11.0", GateType.CONSENSUS, "agent")
    g.add_edge(a.node_id, b.node_id, GateType.CONSENSUS, EdgeStatus.PASSED, "agent")
    with pytest.raises(CMLGCycleDetected):
        g.add_edge(b.node_id, a.node_id, GateType.CONSENSUS, EdgeStatus.PASSED, "agent")


@pytest.mark.parametrize("tid", ["T200-CMLG-03"])
def test_dag_no_cycle_three_nodes(tid, tmp_path):
    """CMLG-DAG-0: A→B→C then C→A raises CMLGCycleDetected."""
    g = _graph(tmp_path)
    a = g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
    b = g.add_node(_mid(), 200, "10.11.0", GateType.CONSENSUS, "agent")
    c = g.add_node(_mid(), 200, "10.11.0", GateType.QUEUE, "agent")
    g.add_edge(a.node_id, b.node_id, GateType.CONSENSUS, EdgeStatus.PASSED, "agent")
    g.add_edge(b.node_id, c.node_id, GateType.QUEUE, EdgeStatus.PASSED, "agent")
    with pytest.raises(CMLGCycleDetected):
        g.add_edge(c.node_id, a.node_id, GateType.QUEUE, EdgeStatus.PASSED, "agent")


@pytest.mark.parametrize("tid", ["T200-CMLG-04"])
def test_dag_valid_forward_edges(tid, tmp_path):
    """CMLG-DAG-0: valid forward chain A→B→C→D accepted without error."""
    g = _graph(tmp_path)
    a = g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
    b = g.add_node(_mid(), 200, "10.11.0", GateType.CONSENSUS, "agent")
    c = g.add_node(_mid(), 200, "10.11.0", GateType.CEL, "agent")
    d = g.add_node(_mid(), 200, "10.11.0", GateType.PROMOTE, "agent")
    g.add_edge(a.node_id, b.node_id, GateType.CONSENSUS, EdgeStatus.PASSED, "agent")
    g.add_edge(b.node_id, c.node_id, GateType.CEL, EdgeStatus.PASSED, "agent")
    g.add_edge(c.node_id, d.node_id, GateType.PROMOTE, EdgeStatus.PASSED, "agent")
    assert len(g._dag.all_edges()) == 3


# ── Chain invariant ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T200-CMLG-05"])
def test_chain_genesis_prev_hash(tid, tmp_path):
    """CMLG-CHAIN-0: first ledger entry has prev_hash == GENESIS."""
    g = _graph(tmp_path)
    g.bootstrap_genesis(200, "10.11.0")
    entry = g._ledger.all_entries()[0]
    assert entry.prev_hash == "GENESIS"


@pytest.mark.parametrize("tid", ["T200-CMLG-06"])
def test_chain_links_correctly(tid, tmp_path):
    """CMLG-CHAIN-0: each entry prev_hash == previous entry_hash."""
    g = _graph(tmp_path)
    g.bootstrap_genesis(200, "10.11.0")
    for _ in range(3):
        g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
    entries = g._ledger.all_entries()
    for i in range(1, len(entries)):
        assert entries[i].prev_hash == entries[i-1].entry_hash


@pytest.mark.parametrize("tid", ["T200-CMLG-07"])
def test_chain_verify_clean(tid, tmp_path):
    """CMLG-CHAIN-0: verify_chain passes on unmodified ledger."""
    g = _graph(tmp_path)
    g.bootstrap_genesis(200, "10.11.0")
    g.add_node(_mid(), 200, "10.11.0", GateType.CONSENSUS, "agent")
    assert g.verify_chain() is True


# ── Anchor invariant ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T200-CMLG-08"])
def test_anchor_all_fields_required(tid, tmp_path):
    """CMLG-ANCHOR-0: missing phase raises anchor violation."""
    g = _graph(tmp_path)
    with pytest.raises(CMLGAnchorViolation):
        g.add_node(_mid(), 0, "10.11.0", GateType.SANDBOX, "agent")


@pytest.mark.parametrize("tid", ["T200-CMLG-09"])
def test_anchor_node_has_phase_version_gate(tid, tmp_path):
    """CMLG-ANCHOR-0: node carries phase, version, gate."""
    g = _graph(tmp_path)
    n = g.add_node(_mid(), 200, "10.11.0", GateType.QUEUE, "agent")
    assert n.phase == 200
    assert n.version == "10.11.0"
    assert n.gate == GateType.QUEUE


# ── Trace invariant ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T200-CMLG-10"])
def test_trace_path_to_genesis(tid, tmp_path):
    """CMLG-TRACE-0: path_to_genesis returns a path including genesis."""
    g = _graph(tmp_path)
    gen = g.bootstrap_genesis(200, "10.11.0")
    n1 = g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
    n2 = g.add_node(_mid(), 200, "10.11.0", GateType.CONSENSUS, "agent")
    g.add_edge(gen.node_id, n1.node_id, GateType.SANDBOX, EdgeStatus.PASSED, "agent")
    g.add_edge(n1.node_id, n2.node_id, GateType.CONSENSUS, EdgeStatus.PASSED, "agent")
    result = g.path_to_genesis(n2.node_id)
    assert gen.node_id in result["path_node_ids"]


@pytest.mark.parametrize("tid", ["T200-CMLG-11"])
def test_trace_ancestors_count(tid, tmp_path):
    """CMLG-TRACE-0: ancestors returns all parent nodes."""
    g = _graph(tmp_path)
    gen = g.bootstrap_genesis(200, "10.11.0")
    a = g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
    b = g.add_node(_mid(), 200, "10.11.0", GateType.CONSENSUS, "agent")
    g.add_edge(gen.node_id, a.node_id, GateType.SANDBOX, EdgeStatus.PASSED, "agent")
    g.add_edge(a.node_id, b.node_id, GateType.CONSENSUS, EdgeStatus.PASSED, "agent")
    result = g.ancestors(b.node_id)
    assert result["ancestor_count"] >= 1


@pytest.mark.parametrize("tid", ["T200-CMLG-12"])
def test_trace_determinism_same_input(tid, tmp_path):
    """CMLG-DETERM-0: path_to_genesis returns identical path on repeated calls."""
    g = _graph(tmp_path)
    gen = g.bootstrap_genesis(200, "10.11.0")
    n = g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
    g.add_edge(gen.node_id, n.node_id, GateType.SANDBOX, EdgeStatus.PASSED, "agent")
    r1 = g.path_to_genesis(n.node_id)
    r2 = g.path_to_genesis(n.node_id)
    assert r1["path_node_ids"] == r2["path_node_ids"]


# ── HUMAN-0 invariant ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T200-CMLG-13"])
def test_human0_rollback_requires_human0(tid, tmp_path):
    """CMLG-HUMAN0-0: rollback by non-HUMAN-0 raises violation."""
    g = _graph(tmp_path)
    n = g.add_node(_mid(), 200, "10.11.0", GateType.CEL, "agent")
    with pytest.raises(CMLGConstitutionalViolation):
        g.mark_rolled_back(n.node_id, "random-agent")


@pytest.mark.parametrize("tid", ["T200-CMLG-14"])
def test_human0_rollback_by_human0(tid, tmp_path):
    """CMLG-HUMAN0-0 + CMLG-ROLLBACK-0: HUMAN-0 can mark rollback."""
    g = _graph(tmp_path)
    n = g.add_node(_mid(), 200, "10.11.0", GateType.CEL, "agent")
    rb = g.mark_rolled_back(n.node_id, HUMAN0)
    assert rb.status == NodeStatus.ROLLED_BACK
    assert rb.gate == GateType.ROLLBACK


@pytest.mark.parametrize("tid", ["T200-CMLG-15"])
def test_human0_purge_ghost_requires_human0(tid, tmp_path):
    """CMLG-HUMAN0-0: purge_ghost by non-HUMAN-0 raises violation."""
    g = _graph(tmp_path)
    n = g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
    with pytest.raises(CMLGConstitutionalViolation):
        g.purge_ghost(n.node_id, "intruder")


@pytest.mark.parametrize("tid", ["T200-CMLG-16"])
def test_human0_purge_ghost_by_human0(tid, tmp_path):
    """CMLG-HUMAN0-0: HUMAN-0 can purge orphan node."""
    g = _graph(tmp_path)
    n = g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
    result = g.purge_ghost(n.node_id, HUMAN0)
    assert result["source_node_id"] == n.node_id


@pytest.mark.parametrize("tid", ["T200-CMLG-17"])
def test_human0_purge_ghost_with_edges_fails(tid, tmp_path):
    """CMLG-IMMUT-0: purge_ghost fails if node has edges."""
    g = _graph(tmp_path)
    a = g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
    b = g.add_node(_mid(), 200, "10.11.0", GateType.CONSENSUS, "agent")
    g.add_edge(a.node_id, b.node_id, GateType.CONSENSUS, EdgeStatus.PASSED, "agent")
    with pytest.raises(CMLGConstitutionalViolation):
        g.purge_ghost(a.node_id, HUMAN0)


# ── Gate invariant ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T200-CMLG-18"])
def test_gate_edge_carries_gate_type(tid, tmp_path):
    """CMLG-GATE-0: every edge has a gate_type."""
    g = _graph(tmp_path)
    a = g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
    b = g.add_node(_mid(), 200, "10.11.0", GateType.CEL, "agent")
    edge = g.add_edge(a.node_id, b.node_id, GateType.CEL, EdgeStatus.PASSED, "agent")
    assert edge.gate_type == GateType.CEL


@pytest.mark.parametrize("tid", ["T200-CMLG-19"])
def test_gate_all_types_accepted(tid, tmp_path):
    """CMLG-GATE-0: all gate types are valid edge types."""
    g = _graph(tmp_path)
    prev = g.bootstrap_genesis(200, "10.11.0")
    for gt in [GateType.SANDBOX, GateType.CONSENSUS, GateType.QUEUE, GateType.CEL, GateType.PROMOTE]:
        n = g.add_node(_mid(), 200, "10.11.0", gt, "agent")
        g.add_edge(prev.node_id, n.node_id, gt, EdgeStatus.PASSED, "agent")
        prev = n
    assert len(g._dag.all_edges()) == 5


# ── Rollback invariant ────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T200-CMLG-20"])
def test_rollback_appends_ledger_entry(tid, tmp_path):
    """CMLG-ROLLBACK-0: rollback appends a new node in ledger."""
    g = _graph(tmp_path)
    n = g.add_node(_mid(), 200, "10.11.0", GateType.CEL, "agent")
    before = len(g._ledger.all_entries())
    g.mark_rolled_back(n.node_id, HUMAN0)
    after = len(g._ledger.all_entries())
    assert after == before + 1


@pytest.mark.parametrize("tid", ["T200-CMLG-21"])
def test_rollback_missing_node_raises(tid, tmp_path):
    """CMLG-ROLLBACK-0: rolling back unknown node raises violation."""
    g = _graph(tmp_path)
    with pytest.raises(CMLGConstitutionalViolation):
        g.mark_rolled_back("nonexistent-node", HUMAN0)


# ── Immutability invariant ────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T200-CMLG-22"])
def test_immut_ledger_only_grows(tid, tmp_path):
    """CMLG-IMMUT-0: ledger entry count only increases."""
    g = _graph(tmp_path)
    counts = []
    for _ in range(5):
        g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
        counts.append(len(g._ledger.all_entries()))
    assert counts == sorted(counts)


# ── Audit invariant ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T200-CMLG-23"])
def test_audit_timestamp_on_node(tid, tmp_path):
    """CMLG-AUDIT-0: every node has ISO-8601 timestamp."""
    g = _graph(tmp_path)
    n = g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
    assert "T" in n.timestamp and "Z" in n.timestamp


@pytest.mark.parametrize("tid", ["T200-CMLG-24"])
def test_audit_actor_on_edge(tid, tmp_path):
    """CMLG-AUDIT-0: every edge has actor attribution."""
    g = _graph(tmp_path)
    a = g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent-a")
    b = g.add_node(_mid(), 200, "10.11.0", GateType.CEL, "agent-b")
    edge = g.add_edge(a.node_id, b.node_id, GateType.CEL, EdgeStatus.PASSED, "agent-c")
    assert edge.actor == "agent-c"


# ── Query / summary ───────────────────────────────────────────────────────────

@pytest.mark.parametrize("tid", ["T200-CMLG-25"])
def test_summary_structure(tid, tmp_path):
    """graph_summary returns all required keys."""
    g = _graph(tmp_path)
    g.bootstrap_genesis(200, "10.11.0")
    s = g.graph_summary()
    for k in ["total_nodes", "total_edges", "gate_distribution", "chain_tip", "invariants", "governor"]:
        assert k in s


@pytest.mark.parametrize("tid", ["T200-CMLG-26"])
def test_mutation_lineage_query(tid, tmp_path):
    """mutation_lineage returns all nodes for a given mutation_id."""
    g = _graph(tmp_path)
    mid = _mid()
    g.add_node(mid, 200, "10.11.0", GateType.SANDBOX, "agent")
    g.add_node(mid, 200, "10.11.0", GateType.CEL, "agent")
    result = g.mutation_lineage(mid)
    assert result["node_count"] == 2
    assert result["mutation_id"] == mid


@pytest.mark.parametrize("tid", ["T200-CMLG-27"])
def test_export_structure(tid, tmp_path):
    """export returns ledger, nodes, edges keys."""
    g = _graph(tmp_path)
    g.bootstrap_genesis(200, "10.11.0")
    exp = g.export()
    assert "ledger" in exp and "nodes" in exp and "edges" in exp


@pytest.mark.parametrize("tid", ["T200-CMLG-28"])
def test_genesis_singleton(tid, tmp_path):
    """bootstrap_genesis called twice returns same genesis node."""
    g = _graph(tmp_path)
    gen1 = g.bootstrap_genesis(200, "10.11.0")
    gen2 = g.bootstrap_genesis(200, "10.11.0")
    assert gen1.node_id == gen2.node_id


@pytest.mark.parametrize("tid", ["T200-CMLG-29"])
def test_edge_failed_status_recorded(tid, tmp_path):
    """CMLG-GATE-0: FAILED edge status is correctly stored in ledger."""
    g = _graph(tmp_path)
    a = g.add_node(_mid(), 200, "10.11.0", GateType.SANDBOX, "agent")
    b = g.add_node(_mid(), 200, "10.11.0", GateType.CONSENSUS, "agent")
    edge = g.add_edge(a.node_id, b.node_id, GateType.CONSENSUS, EdgeStatus.FAILED, "agent")
    assert edge.edge_status == EdgeStatus.FAILED


@pytest.mark.parametrize("tid", ["T200-CMLG-30"])
def test_invariant_ids_complete(tid, tmp_path):
    """All 10 CMLG Hard-class invariant IDs present in manifest."""
    g = _graph(tmp_path)
    expected = {
        "CMLG-DAG-0", "CMLG-CHAIN-0", "CMLG-IMMUT-0", "CMLG-ANCHOR-0",
        "CMLG-TRACE-0", "CMLG-HUMAN0-0", "CMLG-GATE-0", "CMLG-DETERM-0",
        "CMLG-AUDIT-0", "CMLG-ROLLBACK-0",
    }
    assert set(g.INVARIANT_IDS) == expected
