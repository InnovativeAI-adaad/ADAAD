from pathlib import Path


def test_dork_capability_registry_defines_required_plugins() -> None:
    js = Path("ui/developer/ADAADdev/dork_capability_registry.js").read_text(encoding="utf-8")
    for plugin in (
        "replay_health",
        "governance_summary",
        "agent_triad_diagnostics",
        "oracle_projection_explainer",
        "release_readiness_audit",
        "epoch_delta_interpreter",
    ):
        assert f"id: '{plugin}'" in js


def test_whaledic_wires_capability_registry_cards_and_chips() -> None:
    html = Path("ui/developer/ADAADdev/whaledic.html").read_text(encoding="utf-8")
    assert 'script src="./dork_capability_registry.js"' in html
    assert 'id="dork-capability-cards"' in html
    assert "window.DORK_CAPABILITY_REGISTRY" in html
