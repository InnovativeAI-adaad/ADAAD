"""
tests/test_phase168_mpg.py — INNOV-74 · Mutation Phylogeny Graph
Grade-A 30-test suite · Phase 168 · v9.101.0
Markers: T168-MPG-01 … T168-MPG-30
"""

import pytest
from dorkllm.mutation_phylogeny_graph import (
    CANONICAL_EDGE_TYPES,
    GENESIS_EPOCH,
    GENESIS_NODE_ID,
    MPG_ROLLING_WINDOW,
    MPGAnchorViolation,
    MPGAtomicError,
    MPGCycleError,
    MPGEdgeTypeError,
    MPGHuman0Flag,
    MPGTamperError,
    MutationPhylogenyGraph,
    NodeTier,
    PhylogenyEdge,
    PhylogenyNode,
)


# ── Fixtures ─────────────────────────────────────────────────────────────────


@pytest.fixture
def mpg():
    return MutationPhylogenyGraph()


@pytest.fixture
def populated_mpg():
    g = MutationPhylogenyGraph()
    g.add_node("NODE-A", "Alpha mutation", NodeTier.TIER2)
    g.add_node("NODE-B", "Beta mutation", NodeTier.TIER2)
    g.add_node("NODE-C", "Gamma mutation", NodeTier.TIER2, parent_id="NODE-A")
    return g


# ── T168-MPG-01 — Genesis node exists at construction ───────────────────────
@pytest.mark.phase168
def test_genesis_exists(mpg):
    assert GENESIS_NODE_ID in mpg._nodes


# ── T168-MPG-02 — Genesis epoch is 0 ────────────────────────────────────────
@pytest.mark.phase168
def test_genesis_epoch(mpg):
    genesis = mpg._nodes[GENESIS_NODE_ID]
    assert genesis.epoch == GENESIS_EPOCH


# ── T168-MPG-03 — Genesis parent_id is None ─────────────────────────────────
@pytest.mark.phase168
def test_genesis_parent_none(mpg):
    genesis = mpg._nodes[GENESIS_NODE_ID]
    assert genesis.parent_id is None


# ── T168-MPG-04 — Genesis parent_hash is 64 zeros ───────────────────────────
@pytest.mark.phase168
def test_genesis_parent_hash(mpg):
    genesis = mpg._nodes[GENESIS_NODE_ID]
    assert genesis.parent_hash == "0" * 64


# ── T168-MPG-05 — Genesis is pre-ratified ───────────────────────────────────
@pytest.mark.phase168
def test_genesis_ratified(mpg):
    genesis = mpg._nodes[GENESIS_NODE_ID]
    assert genesis.ratified is True


# ── T168-MPG-06 — add_node creates node with correct parent_id ──────────────
@pytest.mark.phase168
def test_add_node_parent_id(mpg):
    node = mpg.add_node("N1", "Test node", NodeTier.TIER2)
    assert node.parent_id == GENESIS_NODE_ID


# ── T168-MPG-07 — add_node chains HMAC to parent ────────────────────────────
@pytest.mark.phase168
def test_add_node_chain_valid(mpg):
    node = mpg.add_node("N1", "Test", NodeTier.TIER2)
    parent = mpg._nodes[GENESIS_NODE_ID]
    assert node.verify_chain(parent)


# ── T168-MPG-08 — MPG-HUMAN0-0: Tier-0 node without ratification raises ─────
@pytest.mark.phase168
def test_tier0_requires_ratification(mpg):
    with pytest.raises(MPGHuman0Flag):
        mpg.add_node("N-T0", "Production node", NodeTier.TIER0, ratified=False)


# ── T168-MPG-09 — MPG-HUMAN0-0: Tier-0 with ratification succeeds ───────────
@pytest.mark.phase168
def test_tier0_ratified_succeeds(mpg):
    node = mpg.add_node("N-T0", "Production node", NodeTier.TIER0, ratified=True)
    assert node.tier == NodeTier.TIER0


# ── T168-MPG-10 — MPG-PERSIST-0: duplicate node_id raises ──────────────────
@pytest.mark.phase168
def test_duplicate_node_raises(mpg):
    mpg.add_node("DUP", "First", NodeTier.TIER2)
    with pytest.raises(MPGAtomicError):
        mpg.add_node("DUP", "Second", NodeTier.TIER2)


# ── T168-MPG-11 — MPG-ACYCLIC-0: direct self-edge cycle raises ──────────────
@pytest.mark.phase168
def test_self_edge_raises(mpg):
    mpg.add_node("N1", "Node", NodeTier.TIER2)
    with pytest.raises(MPGCycleError):
        mpg.add_edge("N1", "N1", "DERIVED_FROM")


# ── T168-MPG-12 — MPG-ACYCLIC-0: indirect cycle raises ─────────────────────
@pytest.mark.phase168
def test_indirect_cycle_raises(mpg):
    mpg.add_node("A", "A", NodeTier.TIER2)
    mpg.add_node("B", "B", NodeTier.TIER2)
    mpg.add_edge("A", "B", "DERIVED_FROM")
    with pytest.raises(MPGCycleError):
        mpg.add_edge("B", "A", "DERIVED_FROM")


# ── T168-MPG-13 — MPG-SCOPE-0: unknown edge type raises ────────────────────
@pytest.mark.phase168
def test_unknown_edge_type_raises(mpg):
    mpg.add_node("A", "A", NodeTier.TIER2)
    mpg.add_node("B", "B", NodeTier.TIER2)
    with pytest.raises(MPGEdgeTypeError):
        mpg.add_edge("A", "B", "INVALID_TYPE")


# ── T168-MPG-14 — All canonical edge types are accepted ─────────────────────
@pytest.mark.phase168
def test_canonical_edge_types_accepted(mpg):
    nodes = []
    for i, et in enumerate(sorted(CANONICAL_EDGE_TYPES)):
        src_id = f"SRC-{i}"
        tgt_id = f"TGT-{i}"
        mpg.add_node(src_id, f"src {i}", NodeTier.TIER2)
        mpg.add_node(tgt_id, f"tgt {i}", NodeTier.TIER2)
        edge = mpg.add_edge(src_id, tgt_id, et)
        assert edge.edge_type == et


# ── T168-MPG-15 — MPG-TRACE-0: ancestry returns path to genesis ─────────────
@pytest.mark.phase168
def test_ancestry_to_genesis(mpg):
    mpg.add_node("C1", "Child 1", NodeTier.TIER2)
    mpg.add_node("C2", "Child 2", NodeTier.TIER2, parent_id="C1")
    path = mpg.ancestry("C2")
    assert path[-1].node_id == GENESIS_NODE_ID
    assert path[0].node_id == "C2"
    assert len(path) == 3  # C2, C1, GENESIS


# ── T168-MPG-16 — ancestry for genesis returns just genesis ─────────────────
@pytest.mark.phase168
def test_ancestry_genesis_only(mpg):
    path = mpg.ancestry(GENESIS_NODE_ID)
    assert len(path) == 1
    assert path[0].node_id == GENESIS_NODE_ID


# ── T168-MPG-17 — depth of genesis is 0 ────────────────────────────────────
@pytest.mark.phase168
def test_genesis_depth(mpg):
    assert mpg.depth(GENESIS_NODE_ID) == 0


# ── T168-MPG-18 — depth increments correctly ────────────────────────────────
@pytest.mark.phase168
def test_depth_increments(mpg):
    mpg.add_node("D1", "Depth 1", NodeTier.TIER2)
    mpg.add_node("D2", "Depth 2", NodeTier.TIER2, parent_id="D1")
    assert mpg.depth("D1") == 1
    assert mpg.depth("D2") == 2


# ── T168-MPG-19 — LCA returns correct common ancestor ───────────────────────
@pytest.mark.phase168
def test_lca(mpg):
    mpg.add_node("ROOT", "Root", NodeTier.TIER2)
    mpg.add_node("A", "A", NodeTier.TIER2, parent_id="ROOT")
    mpg.add_node("B", "B", NodeTier.TIER2, parent_id="ROOT")
    lca = mpg.lca("A", "B")
    assert lca == "ROOT"


# ── T168-MPG-20 — LCA of same node is itself ────────────────────────────────
@pytest.mark.phase168
def test_lca_same_node(mpg):
    mpg.add_node("X", "X", NodeTier.TIER2)
    assert mpg.lca("X", "X") == "X"


# ── T168-MPG-21 — verify_chain passes on clean graph ────────────────────────
@pytest.mark.phase168
def test_verify_chain_clean(populated_mpg):
    assert populated_mpg.verify_chain() is True


# ── T168-MPG-22 — MPG-CHAIN-0: tampered node_hash triggers verify failure ───
@pytest.mark.phase168
def test_verify_chain_tamper_detected(mpg):
    mpg.add_node("X", "X", NodeTier.TIER2)
    # Tamper the node hash directly
    mpg._nodes["X"].node_hash = "deadbeef" * 8  # type: ignore[attr-defined]
    with pytest.raises(MPGTamperError):
        mpg.verify_chain()


# ── T168-MPG-23 — history returns at least genesis operation ────────────────
@pytest.mark.phase168
def test_history_has_genesis_op(mpg):
    h = mpg.history()
    assert len(h) >= 1
    assert h[0]["target_id"] == GENESIS_NODE_ID


# ── T168-MPG-24 — history grows monotonically ───────────────────────────────
@pytest.mark.phase168
def test_history_grows(mpg):
    before = len(mpg.history())
    mpg.add_node("N1", "N", NodeTier.TIER2)
    assert len(mpg.history()) == before + 1


# ── T168-MPG-25 — snapshot is deterministic ─────────────────────────────────
@pytest.mark.phase168
def test_snapshot_deterministic(mpg):
    snap1 = mpg.snapshot()
    snap2 = mpg.snapshot()
    assert snap1 == snap2


# ── T168-MPG-26 — stats node count matches actual nodes ─────────────────────
@pytest.mark.phase168
def test_stats_node_count(populated_mpg):
    s = populated_mpg.stats()
    assert s["nodes"] == len(populated_mpg._nodes)


# ── T168-MPG-27 — descendants of genesis includes all non-genesis nodes ──────
@pytest.mark.phase168
def test_descendants_genesis(populated_mpg):
    desc = populated_mpg.descendants(GENESIS_NODE_ID)
    non_genesis = [nid for nid in populated_mpg._nodes if nid != GENESIS_NODE_ID]
    assert set(desc) == set(non_genesis)


# ── T168-MPG-28 — MPG-ANCHOR-0: genesis immutability constant re-checked ────
@pytest.mark.phase168
def test_genesis_hash_stable(mpg):
    h1 = mpg._genesis_hash
    mpg.add_node("N1", "N", NodeTier.TIER2)
    mpg.add_node("N2", "N", NodeTier.TIER2, parent_id="N1")
    h2 = mpg._genesis_hash
    assert h1 == h2


# ── T168-MPG-29 — MPG_ROLLING_WINDOW constant is 5 ─────────────────────────
@pytest.mark.phase168
def test_rolling_window_constant():
    assert MPG_ROLLING_WINDOW == 5


# ── T168-MPG-30 — Full constitutional workflow: build, link, trace, verify ───
@pytest.mark.phase168
def test_full_constitutional_workflow(mpg):
    # Build a short lineage
    mpg.add_node("INNO-1", "First innovation", NodeTier.TIER1)
    mpg.add_node("INNO-2", "Second innovation", NodeTier.TIER1, parent_id="INNO-1")
    mpg.add_node("INNO-3", "Third innovation", NodeTier.TIER0, ratified=True, parent_id="INNO-2")
    # Add cross-reference edge
    mpg.add_edge("INNO-3", "INNO-1", "REFERENCES")
    # Verify chain integrity
    assert mpg.verify_chain() is True
    # Trace ancestry
    path = mpg.ancestry("INNO-3")
    assert [n.node_id for n in path] == ["INNO-3", "INNO-2", "INNO-1", GENESIS_NODE_ID]
    # Stats
    s = mpg.stats()
    assert s["nodes"] == 4
    assert s["edges"] == 1
    # History
    h = mpg.history()
    assert len(h) >= 4  # genesis + 3 nodes + 1 edge
