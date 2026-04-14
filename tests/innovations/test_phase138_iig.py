# SPDX-License-Identifier: Apache-2.0
# tests/innovations/test_phase138_iig.py
# Phase 138 · INNOV-45 · Invariant Interaction Graph (IIG)
# 30 tests — must pass 30/30

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path

import pytest

from runtime.innovations30.invariant_interaction_graph import (
    CONSTITUTIONAL_INVARIANTS,
    GENESIS_PREV_HASH,
    INNOV_ID,
    PHASE,
    VERSION,
    WORLD_FIRST,
    IIGAuthorizationViolation,
    IIGChainViolation,
    InvariantInteractionGraph,
    InvariantNode,
    InteractionEdge,
    CoFireObservation,
    _compute_graph_digest,
    _compute_observation_hash,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────
@pytest.fixture
def tmp_iig(tmp_path):
    """Fresh IIG backed by a temp file."""
    return InvariantInteractionGraph(path=tmp_path / "iig.jsonl")


@pytest.fixture
def seeded_iig(tmp_path):
    """IIG with two epoch observations recorded."""
    iig = InvariantInteractionGraph(path=tmp_path / "iig.jsonl")
    iig.record_epoch_firings("epoch-001", ["AUDIT-0", "GOV-SOLE-0", "REPLAY-0"], "2026-04-11T00:00:00Z")
    iig.record_epoch_firings("epoch-002", ["AUDIT-0", "HUMAN-0", "GOV-SOLE-0"], "2026-04-11T00:01:00Z")
    return iig


# ── Metadata ──────────────────────────────────────────────────────────────────
def test_iig_01_innov_id():
    assert INNOV_ID == "INNOV-45"


def test_iig_02_phase():
    assert PHASE == 138


def test_iig_03_version():
    assert VERSION == "9.71.0"


def test_iig_04_world_first_nonempty():
    assert len(WORLD_FIRST) > 20


def test_iig_05_constitutional_invariants_count():
    assert len(CONSTITUTIONAL_INVARIANTS) == 5


def test_iig_06_all_iig_invariants_present():
    expected = {"IIG-COFIRE-0", "IIG-DETERM-0", "IIG-PERSIST-0", "IIG-CLUSTER-0", "IIG-HUMAN0-0"}
    assert set(CONSTITUTIONAL_INVARIANTS) == expected


# ── Node / edge construction ──────────────────────────────────────────────────
def test_iig_07_nodes_created_on_record(tmp_iig):
    tmp_iig.record_epoch_firings("e1", ["INV-A", "INV-B", "INV-C"], "2026-04-11T00:00:00Z")
    assert "INV-A" in tmp_iig._nodes
    assert "INV-B" in tmp_iig._nodes
    assert "INV-C" in tmp_iig._nodes


def test_iig_08_edges_created_on_record(tmp_iig):
    tmp_iig.record_epoch_firings("e1", ["INV-A", "INV-B"], "2026-04-11T00:00:00Z")
    assert tmp_iig.co_fire_count("INV-A", "INV-B") == 1


def test_iig_09_co_fire_accumulates(tmp_iig):
    tmp_iig.record_epoch_firings("e1", ["INV-A", "INV-B"], "2026-04-11T00:00:00Z")
    tmp_iig.record_epoch_firings("e2", ["INV-A", "INV-B"], "2026-04-11T00:01:00Z")
    assert tmp_iig.co_fire_count("INV-A", "INV-B") == 2


def test_iig_10_co_fire_count_symmetric(tmp_iig):
    tmp_iig.record_epoch_firings("e1", ["INV-X", "INV-Y"], "2026-04-11T00:00:00Z")
    assert tmp_iig.co_fire_count("INV-X", "INV-Y") == tmp_iig.co_fire_count("INV-Y", "INV-X")


def test_iig_11_fire_count_per_node(tmp_iig):
    tmp_iig.record_epoch_firings("e1", ["INV-A", "INV-B"], "2026-04-11T00:00:00Z")
    tmp_iig.record_epoch_firings("e2", ["INV-A"], "2026-04-11T00:01:00Z")
    assert tmp_iig._nodes["INV-A"].fire_count == 2
    assert tmp_iig._nodes["INV-B"].fire_count == 1


def test_iig_12_pairwise_combinations(tmp_iig):
    """3 invariants → 3 pairs."""
    tmp_iig.record_epoch_firings("e1", ["A", "B", "C"], "2026-04-11T00:00:00Z")
    assert tmp_iig.co_fire_count("A", "B") == 1
    assert tmp_iig.co_fire_count("A", "C") == 1
    assert tmp_iig.co_fire_count("B", "C") == 1


# ── IIG-COFIRE-0: hash chain integrity ───────────────────────────────────────
def test_iig_13_chain_valid_after_records(tmp_iig):
    tmp_iig.record_epoch_firings("e1", ["INV-A", "INV-B"], "2026-04-11T00:00:00Z")
    tmp_iig.record_epoch_firings("e2", ["INV-A", "INV-C"], "2026-04-11T00:01:00Z")
    assert tmp_iig.verify_chain() is True


def test_iig_14_chain_broken_raises(tmp_iig):
    tmp_iig.record_epoch_firings("e1", ["INV-A", "INV-B"], "2026-04-11T00:00:00Z")
    # Tamper the first observation's prev_hash
    tmp_iig._observations[0].prev_hash = "tampered"
    with pytest.raises(IIGChainViolation):
        tmp_iig.verify_chain()


def test_iig_15_genesis_prev_hash_is_zeros():
    assert GENESIS_PREV_HASH == "0" * 64


def test_iig_16_observation_hash_includes_seq():
    obs = CoFireObservation(
        epoch_id="e1", inv_a="A", inv_b="B", timestamp="t", seq=0,
        prev_hash=GENESIS_PREV_HASH,
    )
    payload = json.dumps(
        {"seq": 0, "epoch_id": "e1", "inv_a": "A", "inv_b": "B",
         "timestamp": "t", "prev_hash": GENESIS_PREV_HASH},
        sort_keys=True,
    )
    expected = "sha256:" + hashlib.sha256(payload.encode()).hexdigest()
    assert obs.entry_hash == expected


# ── IIG-DETERM-0: determinism ─────────────────────────────────────────────────
def test_iig_17_graph_digest_deterministic(tmp_path):
    iig1 = InvariantInteractionGraph(path=tmp_path / "a.jsonl")
    iig2 = InvariantInteractionGraph(path=tmp_path / "b.jsonl")
    for iig in (iig1, iig2):
        iig.record_epoch_firings("e1", ["INV-A", "INV-B"], "2026-04-11T00:00:00Z")
        iig.record_epoch_firings("e2", ["INV-A", "INV-C"], "2026-04-11T00:01:00Z")
    assert iig1.graph_digest == iig2.graph_digest


def test_iig_18_digest_changes_on_new_observation(tmp_iig):
    d1 = tmp_iig.graph_digest
    tmp_iig.record_epoch_firings("e1", ["INV-A", "INV-B"], "2026-04-11T00:00:00Z")
    d2 = tmp_iig.graph_digest
    assert d1 != d2


def test_iig_19_digest_is_sha256_prefixed(tmp_iig):
    assert tmp_iig.graph_digest.startswith("sha256:")


# ── IIG-PERSIST-0: round-trip ─────────────────────────────────────────────────
def test_iig_20_persist_roundtrip(tmp_path):
    path = tmp_path / "iig.jsonl"
    iig1 = InvariantInteractionGraph(path=path)
    iig1.record_epoch_firings("e1", ["AUDIT-0", "GOV-SOLE-0"], "2026-04-11T00:00:00Z")
    digest1 = iig1.graph_digest

    iig2 = InvariantInteractionGraph(path=path)
    assert iig2.graph_digest == digest1


def test_iig_21_persist_preserves_co_fire_count(tmp_path):
    path = tmp_path / "iig.jsonl"
    iig1 = InvariantInteractionGraph(path=path)
    iig1.record_epoch_firings("e1", ["A", "B"], "2026-04-11T00:00:00Z")
    iig1.record_epoch_firings("e2", ["A", "B"], "2026-04-11T00:01:00Z")

    iig2 = InvariantInteractionGraph(path=path)
    assert iig2.co_fire_count("A", "B") == 2


# ── IIG-CLUSTER-0: greedy clustering ─────────────────────────────────────────
def test_iig_22_cluster_deterministic(tmp_path):
    def build(p):
        iig = InvariantInteractionGraph(path=p)
        iig.record_epoch_firings("e1", ["A", "B", "C"], "2026-04-11T00:00:00Z")
        iig.record_epoch_firings("e2", ["D", "E"], "2026-04-11T00:01:00Z")
        return iig.greedy_clusters()

    c1 = build(tmp_path / "a.jsonl")
    c2 = build(tmp_path / "b.jsonl")
    assert c1 == c2


def test_iig_23_cluster_members_cover_all_nodes(seeded_iig):
    clusters = seeded_iig.greedy_clusters()
    all_members = [m for members in clusters.values() for m in members]
    assert set(all_members) == set(seeded_iig._nodes.keys())


def test_iig_24_orphan_is_own_cluster(tmp_iig):
    """An invariant that never co-fires should be its own singleton cluster."""
    tmp_iig.record_epoch_firings("e1", ["SOLO"], "2026-04-11T00:00:00Z")
    clusters = tmp_iig.greedy_clusters()
    all_members = [m for members in clusters.values() for m in members]
    assert "SOLO" in all_members


# ── IIG-HUMAN0-0: remove_node gate ───────────────────────────────────────────
def test_iig_25_remove_node_requires_human_auth(seeded_iig):
    with pytest.raises(IIGAuthorizationViolation, match="IIG-HUMAN0-0"):
        seeded_iig.remove_node("AUDIT-0")


def test_iig_26_remove_node_with_auth_succeeds(seeded_iig):
    seeded_iig.remove_node("AUDIT-0", human_auth=True)
    assert "AUDIT-0" not in seeded_iig._nodes


def test_iig_27_remove_node_clears_edges(seeded_iig):
    seeded_iig.remove_node("AUDIT-0", human_auth=True)
    remaining_edges = list(seeded_iig._edges.keys())
    assert all("AUDIT-0" not in k for k in remaining_edges)


# ── Analysis API ──────────────────────────────────────────────────────────────
def test_iig_28_neighbors_returns_co_firers(seeded_iig):
    nbrs = seeded_iig.neighbors("AUDIT-0")
    assert "GOV-SOLE-0" in nbrs


def test_iig_29_strongest_pairs_ordered(seeded_iig):
    # AUDIT-0 and GOV-SOLE-0 co-fired in both epochs → count=2
    pairs = seeded_iig.strongest_pairs(top_n=5)
    assert pairs[0][2] >= pairs[-1][2]  # descending weight


def test_iig_30_to_dict_has_required_keys(seeded_iig):
    d = seeded_iig.to_dict()
    for key in ("innov_id", "phase", "version", "graph_digest",
                "node_count", "edge_count", "observation_count", "nodes", "edges"):
        assert key in d, f"Missing key: {key}"
    assert d["innov_id"] == "INNOV-45"
    assert d["phase"] == 138
