from __future__ import annotations

import ast
import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Set

try:
    from security import cryovant
except Exception:  # pragma: no cover - defensive import guard
    cryovant = None  # type: ignore

FORBIDDEN_TOKENS: Set[str] = {"os.system(", "subprocess.Popen", "eval(", "exec(", "socket."}
BANNED_IMPORTS: Set[str] = {"subprocess", "socket"}


def _imports_in_tree(tree: ast.AST) -> Set[str]:
    found: Set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                found.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                found.add(node.module.split(".")[0])
    return found


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class GateCertifier:
    forbidden_tokens: Set[str] = field(default_factory=lambda: set(FORBIDDEN_TOKENS))
    banned_imports: Set[str] = field(default_factory=lambda: set(BANNED_IMPORTS))

    def certify(self, file_path: Path, metadata: Dict[str, str] | None = None) -> Dict[str, object]:
        metadata = dict(metadata or {})
        if not file_path.exists() or file_path.is_dir():
            return self._result(False, metadata, error="missing_file", file=str(file_path))
        content = file_path.read_text(encoding="utf-8")

        try:
            tree = ast.parse(content)
        except SyntaxError as exc:
            return self._result(False, metadata, error=f"syntax_error:{exc}", file=str(file_path))

        found_imports = _imports_in_tree(tree)
        import_ok = not any(bad in found_imports for bad in self.banned_imports)
        token_ok = not any(tok in content for tok in self.forbidden_tokens)

        token = (metadata.get("cryovant_token") or "").strip()
        auth_ok = False
        if token and cryovant is not None:
            try:
                auth_ok = bool(cryovant.verify_session(token))
            except Exception:
                auth_ok = False

        passed = import_ok and token_ok and auth_ok
        metadata.pop("cryovant_token", None)
        return self._result(
            passed,
            metadata,
            file=str(file_path),
            hash=_sha256_text(content),
            checks={
                "imports": sorted(found_imports),
                "import_ok": import_ok,
                "token_ok": token_ok,
                "auth_ok": auth_ok,
            },
        )

    def _result(self, passed: bool, metadata: Dict[str, str], **kwargs: object) -> Dict[str, object]:
        return {
            "status": "CERTIFIED" if passed else "REJECTED",
            "passed": passed,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata,
            **kwargs,
        }


__all__ = ["GateCertifier"]
