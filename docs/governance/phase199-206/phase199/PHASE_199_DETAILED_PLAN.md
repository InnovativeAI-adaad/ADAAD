# Phase 199 Detailed Execution Plan
**Phase:** 199  
**Epoch:** A — CMCE Proliferation & Hardening  
**Innovation Focus:** CMCE Core Integration Foundation  
**Target Version:** v10.10.0  
**Track Preference:** Primarily Track A (ADAAD)  
**Status:** Draft — awaiting ratification

---

## 1. Phase Objective

Establish CMCE as the **mandatory, non-bypassable consensus gate** for the primary mutation proposal and CEL entry pathway in the `EvolutionKernel`.

This is the foundational technical integration upon which the rest of Epoch A (and future epochs) will be built.

### Success Criteria
- No non-exempt mutation can reach the CEL without a recorded CMCE consensus decision.
- The integration is clean, well-tested, and does not degrade existing mutation performance or determinism.
- New Hard-class invariants are properly registered and enforced.
- Full governance artifact set is produced to constitutional standards.

---

## 2. Scope

### In Scope
- Integration of CMCE into `runtime/evolution/evolution_kernel.py`
- Creation of a dedicated CMCE gate module (`runtime/governance/cmce/cmce_gate.py`)
- Definition and enforcement of exemption policy (minimal at first)
- New invariants (CMCE-GATE-0 and supporting)
- Comprehensive test coverage (unit + integration)
- Full governance artifacts for Phase 199

### Out of Scope (Deferred to later phases)
- DORK-specific CMCE integration (Phase 200)
- SPIE integration (Phase 201)
- Large-scale historical stress testing (Phase 202)
- Advanced challenge escalation UI/logic (Phase 203)

---

## 3. Detailed Deliverables

### 3.1 Core Code Changes
1. **`runtime/governance/cmce/cmce_gate.py`** (new)
   - Clean adapter between `EvolutionKernel` and the existing `constitutional_mutation_consensus_engine.py`
   - Handles round creation, voting orchestration (for agent proposals), quorum evaluation
   - Exemption checking

2. **Modification to `EvolutionKernel`**
   - Add CMCE gate call before CEL entry
   - Proper error handling and ledger correlation

3. **Exemption Framework (minimal viable)**
   - `governance/cmce_exemptions.json` or equivalent
   - Policy for when exemptions are allowed (very restrictive initially)

### 3.2 Testing
- Unit tests for the gate module
- Integration test that a mutation proposal flows through CMCE before reaching CEL
- Performance regression test (CMCE should not add unacceptable latency to the happy path)

### 3.3 Governance Artifacts (Required)
- `ila.json`
- `sign_off.json`
- `tier_summary.json`
- `invariant_register.json` (new CMCE-GATE invariants)
- Evidence matrix / replay linkage

---

## 4. New Invariants (Proposed)

| ID | Class | Description |
|----|-------|-------------|
| CMCE-GATE-0 | Hard | No mutation may enter the CEL without either a PASSED CMCE consensus record or an active, logged exemption. |
| CMCE-EXEMPT-0 | Hard | Exemptions must be explicitly declared, time-bounded where possible, and recorded in the CMCE ledger before use. |

---

## 5. Strategic Implementation Approach

This phase will be executed with maximum leverage of current tooling:

- **Grok (this session)** will act as primary implementation partner and evidence generator.
- Heavy use of the existing CMCE module (`dorkllm/constitutional_mutation_consensus_engine.py`) — we will **not** rewrite it.
- Focus on clean adapter patterns rather than invasive changes.
- All changes must preserve full deterministic replay capability.

---

## 6. Risks & Mitigations

| Risk | Mitigation |
|------|------------|
| Breaking existing mutation flows | Extremely conservative integration + comprehensive integration tests |
| Performance regression | Benchmark before/after; design for async/off-path consensus where safe |
| Exemption abuse | Extremely narrow exemption policy in this phase + strong auditing |

---

## 7. Recommended Execution Sequence

1. **Week 1**: Design the adapter interface + exemption model. Produce draft `cmce_gate.py` skeleton.
2. **Week 2**: Wire into `EvolutionKernel`. Write integration tests.
3. **Week 3**: Full test suite + governance artifact production.
4. **Week 4**: Review, evidence finalization, and merge under appropriate track.

---

**Next Step Recommendation:**

Once you approve this Phase 199 plan (and ideally after confirming Phase 198 GPG status), I recommend we immediately begin the **detailed implementation work** for Phase 199, starting with the adapter design and skeleton.

Would you like me to:

A. Proceed to draft the actual code structure and first implementation artifacts for Phase 199 right now?
B. First produce a full set of governance artifact templates for Phase 199?
C. Wait for your explicit ratification of the Epoch A plan before going deeper on Phase 199?

Please give clear direction. I am ready to execute.