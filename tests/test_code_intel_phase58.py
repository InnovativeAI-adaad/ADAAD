# SPDX-License-Identifier: Apache-2.0
"""
tests/test_code_intel_phase58.py
================================
Phase 58 — Code Intelligence Model — T58-INTEL-01..12

Coverage
--------
T58-INTEL-01  FunctionCallGraph.from_source — basic call extraction
T58-INTEL-02  FunctionCallGraph graph_hash is deterministic (INTEL-DET-0)
T58-INTEL-03  FunctionCallGraph.from_source_files — multi-file merge
T58-INTEL-04  FunctionCallGraph callees_of / callers_of helpers
T58-INTEL-05  HotspotMap scores bounded [0.0, 1.0]
T58-INTEL-06  HotspotMap map_hash is deterministic (INTEL-DET-0)
T58-INTEL-07  HotspotMap churn integration via churn_map param
T58-INTEL-08  MutationHistory append + hash chain integrity (INTEL-TS-0)
T58-INTEL-09  MutationHistory IntegrityError on tampered record
T58-INTEL-10  INTEL-ISO-0: code_intel modules do not import governance/ledger paths
T58-INTEL-11  CodeIntelModel.build — frozen snapshot, model_hash stability
T58-INTEL-12  CodeIntelModel enrichment helpers (hotspot_score_for, callers_of, etc.)
"""

from __future__ import annotations

import ast
import hashlib
import importlib
import inspect
import json
import os
import sys
import tempfile
import textwrap
from pathlib import Path
from typing import List

import pytest

# ---------------------------------------------------------------------------
# Ensure repo root on path
# ---------------------------------------------------------------------------
REPO_ROOT = Path(__file__).parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from runtime.mutation.code_intel.function_graph import FunctionCallGraph
from runtime.mutation.code_intel.hotspot_map import HotspotMap, FileHotspotEntry
from runtime.mutation.code_intel.mutation_history import MutationHistory, IntegrityError
from runtime.mutation.code_intel.code_intel_model import CodeIntelModel


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

SIMPLE_SOURCE = textwrap.dedent("""\
    def alpha():
        beta()
        gamma()

    def beta():
        gamma()

    def gamma():
        pass
""")

BRANCH_SOURCE = textwrap.dedent("""\
    def process(x):
        if x > 0:
            for i in range(x):
                pass
        try:
            risky()
        except ValueError:
            pass
        return x

    def risky():
        pass
""")


# ===========================================================================
# T58-INTEL-01  FunctionCallGraph.from_source — basic call extraction
# ===========================================================================

class TestT58Intel01FunctionGraphFromSource:

    def test_discovers_all_functions(self):
        g = FunctionCallGraph.from_source(SIMPLE_SOURCE)
        assert set(g.functions) == {"alpha", "beta", "gamma"}

    def test_adjacency_alpha_calls_beta_gamma(self):
        g = FunctionCallGraph.from_source(SIMPLE_SOURCE)
        assert "beta" in g.adjacency["alpha"]
        assert "gamma" in g.adjacency["alpha"]

    def test_adjacency_beta_calls_gamma(self):
        g = FunctionCallGraph.from_source(SIMPLE_SOURCE)
        assert g.adjacency["beta"] == ["gamma"]

    def test_graph_hash_is_hexdigest(self):
        g = FunctionCallGraph.from_source(SIMPLE_SOURCE)
        assert len(g.graph_hash) == 64
        int(g.graph_hash, 16)  # must be valid hex

    def test_syntax_error_returns_empty_graph(self):
        g = FunctionCallGraph.from_source("def :(")
        assert g.adjacency == {}
        assert g.functions == []

    def test_to_dict_serialisable(self):
        g = FunctionCallGraph.from_source(SIMPLE_SOURCE)
        d = g.to_dict()
        assert json.dumps(d)  # must not raise


# ===========================================================================
# T58-INTEL-02  Deterministic graph_hash (INTEL-DET-0)
# ===========================================================================

class TestT58Intel02GraphHashDeterminism:

    def test_same_source_same_hash(self):
        h1 = FunctionCallGraph.from_source(SIMPLE_SOURCE).graph_hash
        h2 = FunctionCallGraph.from_source(SIMPLE_SOURCE).graph_hash
        assert h1 == h2

    def test_different_source_different_hash(self):
        h1 = FunctionCallGraph.from_source(SIMPLE_SOURCE).graph_hash
        h2 = FunctionCallGraph.from_source(BRANCH_SOURCE).graph_hash
        assert h1 != h2

    def test_hash_uses_sha256_not_builtin_hash(self):
        # Verify graph_hash length == 64 (sha256 hexdigest), not Python hash length
        g = FunctionCallGraph.from_source(SIMPLE_SOURCE)
        assert len(g.graph_hash) == 64

    def test_hash_matches_manual_computation(self):
        g = FunctionCallGraph.from_source(SIMPLE_SOURCE)
        canonical = json.dumps(g.adjacency, sort_keys=True, default=str)
        expected = hashlib.sha256(canonical.encode()).hexdigest()
        assert g.graph_hash == expected


# ===========================================================================
# T58-INTEL-03  FunctionCallGraph.from_source_files — multi-file merge
# ===========================================================================

class TestT58Intel03MultiFileMerge:

    def test_merges_functions_across_files(self, tmp_path):
        f1 = tmp_path / "a.py"
        f2 = tmp_path / "b.py"
        f1.write_text("def foo():\n    bar()\n")
        f2.write_text("def bar():\n    pass\n")
        g = FunctionCallGraph.from_source_files([str(f1), str(f2)])
        assert "foo" in g.functions
        assert "bar" in g.functions

    def test_missing_file_is_skipped(self, tmp_path):
        f1 = tmp_path / "real.py"
        f1.write_text("def real(): pass\n")
        g = FunctionCallGraph.from_source_files([str(f1), "/nonexistent/fake.py"])
        assert "real" in g.functions

    def test_from_source_tree_finds_py_files(self, tmp_path):
        (tmp_path / "sub").mkdir()
        (tmp_path / "sub" / "m.py").write_text("def baz(): pass\n")
        g = FunctionCallGraph.from_source_tree(str(tmp_path))
        assert "baz" in g.functions

    def test_source_files_list_populated(self, tmp_path):
        f = tmp_path / "x.py"
        f.write_text("def x(): pass\n")
        g = FunctionCallGraph.from_source_files([str(f)])
        assert str(f) in g.source_files


# ===========================================================================
# T58-INTEL-04  callees_of / callers_of helpers
# ===========================================================================

class TestT58Intel04GraphHelpers:

    def setup_method(self):
        self.g = FunctionCallGraph.from_source(SIMPLE_SOURCE)

    def test_callees_of_alpha(self):
        assert set(self.g.callees_of("alpha")) == {"beta", "gamma"}

    def test_callees_of_gamma_empty(self):
        assert self.g.callees_of("gamma") == []

    def test_callers_of_gamma(self):
        callers = set(self.g.callers_of("gamma"))
        assert "alpha" in callers
        assert "beta" in callers

    def test_callers_of_unknown_empty(self):
        assert self.g.callers_of("nonexistent") == []


# ===========================================================================
# T58-INTEL-05  HotspotMap scores bounded [0.0, 1.0]
# ===========================================================================

class TestT58Intel05HotspotScoresBounded:

    def test_all_scores_in_unit_interval(self, tmp_path):
        f = tmp_path / "s.py"
        f.write_text(BRANCH_SOURCE)
        hm = HotspotMap.from_source_files([str(f)])
        for e in hm.entries:
            assert 0.0 <= e.complexity_score <= 1.0
            assert 0.0 <= e.fragility_score <= 1.0
            assert 0.0 <= e.churn_score <= 1.0
            assert 0.0 <= e.hotspot_score <= 1.0

    def test_entries_sorted_descending(self, tmp_path):
        for i in range(3):
            (tmp_path / f"f{i}.py").write_text("def fn(): pass\n" * (i + 1))
        hm = HotspotMap.from_source_files([str(p) for p in tmp_path.glob("*.py")])
        scores = [e.hotspot_score for e in hm.entries]
        assert scores == sorted(scores, reverse=True)

    def test_top_hotspots_respects_top_n(self, tmp_path):
        for i in range(5):
            (tmp_path / f"g{i}.py").write_text("def fn(): pass\n")
        hm = HotspotMap.from_source_files([str(p) for p in tmp_path.glob("*.py")], top_n=3)
        assert len(hm.top_hotspots) <= 3

    def test_missing_file_gets_zero_scores(self, tmp_path):
        hm = HotspotMap.from_source_files(["/nonexistent/bad.py"])
        assert hm.entries[0].hotspot_score == 0.0


# ===========================================================================
# T58-INTEL-06  HotspotMap map_hash determinism (INTEL-DET-0)
# ===========================================================================

class TestT58Intel06HotspotHashDeterminism:

    def test_same_files_same_hash(self, tmp_path):
        f = tmp_path / "d.py"
        f.write_text(BRANCH_SOURCE)
        h1 = HotspotMap.from_source_files([str(f)]).map_hash
        h2 = HotspotMap.from_source_files([str(f)]).map_hash
        assert h1 == h2

    def test_different_content_different_hash(self, tmp_path):
        f1 = tmp_path / "e1.py"
        f2 = tmp_path / "e2.py"
        f1.write_text("def a(): pass\n")
        f2.write_text(BRANCH_SOURCE)
        h1 = HotspotMap.from_source_files([str(f1)]).map_hash
        h2 = HotspotMap.from_source_files([str(f2)]).map_hash
        assert h1 != h2

    def test_map_hash_is_64_char_hex(self, tmp_path):
        f = tmp_path / "h.py"
        f.write_text("def x(): pass\n")
        hm = HotspotMap.from_source_files([str(f)])
        assert len(hm.map_hash) == 64
        int(hm.map_hash, 16)


# ===========================================================================
# T58-INTEL-07  HotspotMap churn integration
# ===========================================================================

class TestT58Intel07ChurnIntegration:

    def test_churn_increases_hotspot_score(self, tmp_path):
        f = tmp_path / "c.py"
        f.write_text("def simple(): pass\n")
        path = str(f)
        hm_no_churn = HotspotMap.from_source_files([path])
        hm_churn = HotspotMap.from_source_files([path], churn_map={path: 1.0})
        e_no = hm_no_churn.entry_for(path)
        e_ch = hm_churn.entry_for(path)
        assert e_ch.hotspot_score > e_no.hotspot_score

    def test_churn_clamped_to_one(self, tmp_path):
        f = tmp_path / "cc.py"
        f.write_text("def fn(): pass\n")
        path = str(f)
        hm = HotspotMap.from_source_files([path], churn_map={path: 999.0})
        assert hm.entry_for(path).churn_score == 1.0

    def test_entry_for_unknown_returns_none(self, tmp_path):
        hm = HotspotMap.from_source_files([])
        assert hm.entry_for("/does/not/exist.py") is None


# ===========================================================================
# T58-INTEL-08  MutationHistory append + hash chain (INTEL-TS-0)
# ===========================================================================

class TestT58Intel08MutationHistoryChain:

    def test_append_increments_count(self):
        h = MutationHistory()
        h.append("a.py", "refactor", "desc")
        h.append("b.py", "hotfix", "desc2")
        assert h.count == 2

    def test_chain_hash_links_records(self):
        h = MutationHistory()
        r0 = h.append("a.py", "refactor", "first")
        r1 = h.append("b.py", "hotfix", "second")
        assert r1.prior_hash == r0.chain_hash

    def test_first_record_prior_hash_is_zeros(self):
        h = MutationHistory()
        r = h.append("a.py", "refactor", "first")
        assert r.prior_hash == "0" * 64

    def test_verify_integrity_passes_clean_chain(self):
        h = MutationHistory()
        for i in range(5):
            h.append(f"file{i}.py", "generated", f"mutation {i}")
        assert h.verify_integrity() is True

    def test_timestamp_is_string(self):
        h = MutationHistory()
        r = h.append("a.py", "refactor", "desc")
        assert isinstance(r.timestamp, str)
        assert len(r.timestamp) > 0

    def test_records_for_file_filters_correctly(self):
        h = MutationHistory()
        h.append("a.py", "refactor", "one")
        h.append("b.py", "hotfix", "two")
        h.append("a.py", "generated", "three")
        assert len(h.records_for_file("a.py")) == 2
        assert len(h.records_for_file("b.py")) == 1

    def test_churn_map_counts_per_file(self):
        h = MutationHistory()
        h.append("a.py", "refactor", "one")
        h.append("a.py", "hotfix", "two")
        h.append("b.py", "refactor", "three")
        cm = h.churn_map()
        assert cm["a.py"] == 2
        assert cm["b.py"] == 1

    def test_normalised_churn_map_max_is_one(self):
        h = MutationHistory()
        h.append("a.py", "refactor", "x")
        h.append("a.py", "refactor", "y")
        h.append("b.py", "refactor", "z")
        ncm = h.normalised_churn_map()
        assert max(ncm.values()) == 1.0

    def test_persistence_roundtrip(self, tmp_path):
        path = str(tmp_path / "ledger.jsonl")
        h1 = MutationHistory(path)
        h1.append("a.py", "refactor", "persisted")
        h2 = MutationHistory(path)
        assert h2.count == 1
        assert h2.records[0].target_file == "a.py"


# ===========================================================================
# T58-INTEL-09  MutationHistory IntegrityError on tamper
# ===========================================================================

class TestT58Intel09IntegrityError:

    def test_tampered_chain_hash_raises(self):
        h = MutationHistory()
        h.append("a.py", "refactor", "first")
        h.append("b.py", "hotfix", "second")
        # Directly mutate the stored chain_hash of record 0
        h._records[0].chain_hash = "deadbeef" * 8
        with pytest.raises(IntegrityError):
            h.verify_integrity()

    def test_tampered_prior_hash_raises(self):
        h = MutationHistory()
        h.append("a.py", "refactor", "first")
        h.append("b.py", "hotfix", "second")
        h._records[1].prior_hash = "00" * 32
        with pytest.raises(IntegrityError):
            h.verify_integrity()


# ===========================================================================
# T58-INTEL-10  INTEL-ISO-0: no governance/ledger imports
# ===========================================================================

FORBIDDEN_IMPORT_PATTERNS = [
    "runtime.governance",
    "runtime.ledger",
]

CODE_INTEL_MODULES = [
    "runtime.mutation.code_intel.function_graph",
    "runtime.mutation.code_intel.hotspot_map",
    "runtime.mutation.code_intel.mutation_history",
    "runtime.mutation.code_intel.code_intel_model",
]


class TestT58Intel10IsoInvariant:

    def _get_imports(self, module_name: str) -> list:
        mod = importlib.import_module(module_name)
        source = inspect.getsource(mod)
        tree = ast.parse(source)
        imports = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imports.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    imports.append(node.module)
        return imports

    @pytest.mark.parametrize("module_name", CODE_INTEL_MODULES)
    def test_no_governance_imports(self, module_name):
        imports = self._get_imports(module_name)
        for imp in imports:
            for pattern in FORBIDDEN_IMPORT_PATTERNS:
                assert not imp.startswith(pattern), (
                    f"{module_name} imports forbidden path: {imp}"
                )


# ===========================================================================
# T58-INTEL-11  CodeIntelModel frozen snapshot + model_hash stability
# ===========================================================================

class TestT58Intel11CodeIntelModelBuild:

    def _build_model(self, tmp_path) -> CodeIntelModel:
        f = tmp_path / "src.py"
        f.write_text(SIMPLE_SOURCE)
        cg = FunctionCallGraph.from_source_files([str(f)])
        hm = HotspotMap.from_source_files([str(f)])
        hist = MutationHistory()
        hist.append(str(f), "refactor", "initial")
        return CodeIntelModel.build(cg, hm, hist)

    def test_returns_frozen_instance(self, tmp_path):
        m = self._build_model(tmp_path)
        with pytest.raises((AttributeError, TypeError)):
            m.model_hash = "tampered"  # type: ignore[misc]

    def test_model_hash_is_64_hex(self, tmp_path):
        m = self._build_model(tmp_path)
        assert len(m.model_hash) == 64
        int(m.model_hash, 16)

    def test_snapshot_timestamp_is_string(self, tmp_path):
        m = self._build_model(tmp_path)
        assert isinstance(m.snapshot_timestamp, str)
        assert len(m.snapshot_timestamp) > 0

    def test_graph_hash_matches_call_graph(self, tmp_path):
        m = self._build_model(tmp_path)
        assert m.graph_hash == m.call_graph.graph_hash

    def test_hotspot_hash_matches_hotspot_map(self, tmp_path):
        m = self._build_model(tmp_path)
        assert m.hotspot_hash == m.hotspot_map.map_hash

    def test_history_count_reflects_ledger(self, tmp_path):
        m = self._build_model(tmp_path)
        assert m.history_count == 1

    def test_top_hotspots_is_tuple(self, tmp_path):
        m = self._build_model(tmp_path)
        assert isinstance(m.top_hotspots, tuple)

    def test_to_dict_json_serialisable(self, tmp_path):
        m = self._build_model(tmp_path)
        assert json.dumps(m.to_dict())

    def test_to_json_string(self, tmp_path):
        m = self._build_model(tmp_path)
        parsed = json.loads(m.to_json())
        assert parsed["model_hash"] == m.model_hash

    def test_build_without_history(self, tmp_path):
        f = tmp_path / "nh.py"
        f.write_text("def fn(): pass\n")
        cg = FunctionCallGraph.from_source_files([str(f)])
        hm = HotspotMap.from_source_files([str(f)])
        m = CodeIntelModel.build(cg, hm)
        assert m.history_count == 0
        assert m.churn_map == {}


# ===========================================================================
# T58-INTEL-12  CodeIntelModel enrichment helpers
# ===========================================================================

class TestT58Intel12EnrichmentHelpers:

    def setup_method(self, method):
        import tempfile
        self._tmpdir = tempfile.mkdtemp()
        self.tmp = Path(self._tmpdir)
        f = self.tmp / "enrich.py"
        f.write_text(SIMPLE_SOURCE)
        self.path = str(f)
        cg = FunctionCallGraph.from_source_files([self.path])
        hm = HotspotMap.from_source_files([self.path])
        hist = MutationHistory()
        hist.append(self.path, "refactor", "one")
        hist.append(self.path, "hotfix", "two")
        self.model = CodeIntelModel.build(cg, hm, hist)

    def test_hotspot_score_for_known_file(self):
        score = self.model.hotspot_score_for(self.path)
        assert 0.0 <= score <= 1.0

    def test_hotspot_score_for_unknown_file(self):
        assert self.model.hotspot_score_for("/unknown/x.py") == 0.0

    def test_callers_of_gamma(self):
        callers = set(self.model.callers_of("gamma"))
        assert "alpha" in callers

    def test_callees_of_alpha(self):
        callees = set(self.model.callees_of("alpha"))
        assert "beta" in callees

    def test_is_top_hotspot(self):
        # The one file we have should appear in top_hotspots
        assert self.model.is_top_hotspot(self.path)

    def test_churn_score_for_known_file(self):
        score = self.model.churn_score_for(self.path)
        assert score == 1.0  # only one file, so it's the max → normalised to 1.0

    def test_churn_score_for_unknown_file(self):
        assert self.model.churn_score_for("/nope/x.py") == 0.0
