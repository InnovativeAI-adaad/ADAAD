from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).parent.parent.absolute()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.tools.agent_validator import validate_agents
from security.cryovant import Cryovant


REQUIRED_ROOTS = [
    "app",
    "runtime",
    "security",
    "tests",
    "docs",
    "data",
    "reports",
    "releases",
    "experiments",
    "scripts",
    "ui",
    "tools",
    "archives",
]
FORBIDDEN_DIRS = {"core", "engines", "engine", "legacy", "protocols"}
CANONICAL_IMPORT_ROOTS = {"app", "runtime", "security", "data", "reports"}

PKG_INITS = ["app", "runtime", "security", "ui", "tests", "reports"]


def check_roots() -> Tuple[bool, List[str]]:
    missing = [r for r in REQUIRED_ROOTS if not Path(r).exists()]
    forbidden = [p.name for p in ROOT.iterdir() if p.is_dir() and p.name in FORBIDDEN_DIRS]
    extras = [
        p.name
        for p in ROOT.iterdir()
        if p.is_dir()
        and p.name not in REQUIRED_ROOTS
        and p.name not in {".git", ".github", "__pycache__", ".venv", ".pytest_cache"}
    ]
    return not (missing or forbidden or extras), missing + forbidden + extras


def check_namespace_inits() -> Tuple[bool, List[str]]:
    missing = []
    for pkg in PKG_INITS:
        init_path = Path(pkg) / "__init__.py"
        if not init_path.exists():
            missing.append(str(init_path))
    return not missing, missing


def check_print_violations() -> Tuple[bool, List[str]]:
    import ast

    violations: List[str] = []
    for root in ["app", "runtime"]:
        for path in Path(root).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and getattr(getattr(node, "func", None), "id", None) == "print":
                    violations.append(str(path))
                    break
    return not violations, violations


def check_canonical_imports() -> Tuple[bool, List[str]]:
    import ast

    violations: List[str] = []
    for root in ["app", "runtime"]:
        for path in Path(root).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    if isinstance(func, ast.Attribute):
                        val = func.value
                        if (
                            isinstance(val, ast.Attribute)
                            and getattr(val.value, "id", None) == "sys"
                            and val.attr == "path"
                            and func.attr in {"append", "insert", "extend"}
                        ):
                            violations.append(str(path))
                            break
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root_name = alias.name.split(".")[0]
                        if root_name in FORBIDDEN_DIRS or (
                            root_name not in CANONICAL_IMPORT_ROOTS and (ROOT / root_name).exists()
                        ):
                            violations.append(str(path))
                            break
                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    root_name = module.split(".")[0]
                    if root_name in FORBIDDEN_DIRS or (
                        root_name not in CANONICAL_IMPORT_ROOTS and (ROOT / root_name).exists()
                    ):
                        violations.append(str(path))
                        break
    return not violations, sorted(set(violations))


def check_cryovant() -> Tuple[bool, str]:
    cryo = Cryovant(Path("security/ledger"), Path("security/keys"))
    try:
        ledger_dir = cryo.touch_ledger().parent
        probe = ledger_dir / ".doctor_probe"
        probe.write_text("probe", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return True, str(ledger_dir)
    except Exception as exc:  # pragma: no cover
        return False, str(exc)


def check_agents() -> Tuple[bool, List[str]]:
    _, failed = validate_agents(Path("app/agents/active"))
    messages = [f"{res.path}: missing {','.join(res.missing)}" for res in failed]
    return not messages, messages


def run_tests() -> Tuple[bool, str]:
    import subprocess

    try:
        subprocess.check_call(["pytest", "-q"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, "pytest -q"
    except subprocess.CalledProcessError as exc:
        return False, f"tests failed: {exc}"


def main() -> None:
    checks: Dict[str, object] = {}
    ok_roots, missing_roots = check_roots()
    checks["structure_ok"] = ok_roots
    checks["missing_roots"] = missing_roots

    ok_inits, missing_inits = check_namespace_inits()
    checks["namespace_ok"] = ok_inits
    checks["missing_inits"] = missing_inits

    ok_prints, violations = check_print_violations()
    checks["logging_ok"] = ok_prints
    checks["print_violations"] = violations

    ok_imports, import_violations = check_canonical_imports()
    checks["imports_ok"] = ok_imports
    checks["import_violations"] = import_violations

    ok_cryo, cryo_detail = check_cryovant()
    checks["cryovant_ok"] = ok_cryo
    checks["cryovant_detail"] = cryo_detail

    ok_agents, agent_messages = check_agents()
    checks["agents_valid"] = ok_agents
    checks["agent_issues"] = agent_messages

    ok_tests, test_detail = run_tests()
    checks["tests_ok"] = ok_tests
    checks["tests_detail"] = test_detail

    checks["mutation_enabled"] = all([ok_roots, ok_inits, ok_prints, ok_imports, ok_cryo, ok_agents, ok_tests])

    print(json.dumps(checks, indent=2))
    if not all([ok_roots, ok_inits, ok_prints, ok_imports, ok_cryo, ok_agents, ok_tests]):
        sys.exit(1)


if __name__ == "__main__":
    main()
