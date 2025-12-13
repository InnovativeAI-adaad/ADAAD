from pathlib import Path
from security.cryovant import Cryovant

def test_ledger(tmp_path: Path):
    c = Cryovant(tmp_path / "ledger", tmp_path / "keys")
    c.touch_ledger()
    c.append_event({"event": "x"})
    assert (tmp_path / "ledger" / "events.jsonl").exists()
