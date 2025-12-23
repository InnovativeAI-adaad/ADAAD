from __future__ import annotations

import json
from pathlib import Path
from security.cryovant import Cryovant

def main() -> None:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("agent_dir", help="Path like app/agents/active/<agent_id>")
    ap.add_argument("--certify", action="store_true", help="Write ledger certify event and set certified true")
    ap.add_argument("--actor", default="mint_cert")
    args = ap.parse_args()

    agent_dir = Path(args.agent_dir)
    cert_path = agent_dir / "certificate.json"
    if not cert_path.exists():
        raise SystemExit(f"missing: {cert_path}")

    c = Cryovant()
    canonical = c.compute_lineage_hash(agent_dir)

    cert = json.loads(cert_path.read_text(encoding="utf-8"))
    cert["lineage_hash"] = canonical
    cert.setdefault("schema", "he65.agent.cert.v1")
    cert.setdefault("issuer", "cryovant")
    cert.setdefault("lineage_schema", "he65.lineage.v1")

    if args.certify:
        cert["certified"] = True
        c.certify(agent_dir.name, canonical, outcome="approved", actor=args.actor)

    cert_path.write_text(json.dumps(cert, indent=2, sort_keys=True), encoding="utf-8")
    print(canonical)

if __name__ == "__main__":
    main()
