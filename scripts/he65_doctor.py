from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path
from typing import Dict, List, Tuple

ROOT = Path(__file__).parent.parent.absolute()
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from runtime.tools.agent_validator import validate_agents
from security.cryovant import Cryovant, KEYS_DIR, LEDGER_PATH, LEDGER_SCHEMA_VERSION

REQUIRED_ROOTS = [
    "app",
    "runtime",
    "security",
    "tests",
    "docs",
    "data",
    "logs",
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
    problems = missing + forbidden + extras
    return not problems, problems


def check_namespace_inits() -> Tuple[bool, List[str]]:
    missing: List[str] = []
    for pkg in PKG_INITS:
        init_path = Path(pkg) / "__init__.py"
        if not init_path.exists():
            missing.append(str(init_path))
    return not missing, missing


def check_print_violations() -> Tuple[bool, List[str]]:
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
    violations = sorted(set(violations))
    return not violations, violations


def check_canonical_imports() -> Tuple[bool, List[str]]:
    violations: List[str] = []
    for root in ["app", "runtime"]:
        for path in Path(root).rglob("*.py"):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue

            bad = False
            for node in ast.walk(tree):
                # sys.path mutation
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
                            bad = True
                            break

                # imports from forbidden or non-canonical roots
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        root_name = alias.name.split(".")[0]
                        if root_name in FORBIDDEN_DIRS:
                            bad = True
                            break
                        if root_name not in CANONICAL_IMPORT_ROOTS and (ROOT / root_name).exists():
                            bad = True
                            break

                if isinstance(node, ast.ImportFrom):
                    module = node.module or ""
                    root_name = module.split(".")[0]
                    if root_name in FORBIDDEN_DIRS:
                        bad = True
                        break
                    if root_name and root_name not in CANONICAL_IMPORT_ROOTS and (ROOT / root_name).exists():
                        bad = True
                        break

            if bad:
                violations.append(str(path))

    return not violations, sorted(set(violations))


def check_runtime_logging_file_io() -> Tuple[bool, List[str]]:
    p = Path("runtime/logging.py")
    if not p.exists():
        return False, ["runtime/logging.py missing"]

    text = p.read_text(encoding="utf-8")
    patterns = ["open(", ".open(", ".write_text(", ".write_bytes(", ".touch("]
    hits = [pat for pat in patterns if pat in text]
    return not hits, hits


def check_boot_two_line_rule() -> Tuple[bool, str]:
    main_path = Path("app/main.py")
    if not main_path.exists():
        return False, "app/main.py missing"

    tree = ast.parse(main_path.read_text(encoding="utf-8"))
    logger_calls = {"normal": 0, "exception": 0}

    class BootVisitor(ast.NodeVisitor):
        def __init__(self) -> None:
            self.in_except = False

        def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
            prev = self.in_except
            self.in_except = True
            self.generic_visit(node)
            self.in_except = prev

        def visit_Call(self, node: ast.Call) -> None:
            func = node.func
            if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name) and func.value.id == "logger":
                key = "exception" if self.in_except else "normal"
                logger_calls[key] += 1
            self.generic_visit(node)

    BootVisitor().visit(tree)
    ok = (logger_calls["normal"] == 2) and (logger_calls["exception"] == 1)
    return ok, json.dumps(logger_calls, sort_keys=True)


def check_ledger_path_constant() -> Tuple[bool, str]:
    expected = Path("security/ledger/events.jsonl")
    return LEDGER_PATH == expected, str(LEDGER_PATH)


def check_keys_keep() -> Tuple[bool, str]:
    keep = KEYS_DIR / ".keep"
    return keep.exists(), str(keep)


def check_cryovant() -> Tuple[bool, str]:
    try:
        cryo = Cryovant()
        ledger_path = cryo.touch_ledger()
        cryo.ledger_probe(actor="doctor")
        return True, str(ledger_path)
    except Exception as exc:  # pragma: no cover
        return False, str(exc)


def check_agents() -> Tuple[bool, List[str]]:
    _, failed = validate_agents(Path("app/agents/active"))
    messages = [
        f"{res.path}: missing {','.join(res.missing)} schema:{','.join(res.schema_violations)}" for res in failed
    ]
    return not messages, messages


def check_direct_ledger_writer_block() -> Tuple[bool, str]:
    try:
        from security.ledger import ledger as direct_ledger

        try:
            direct_ledger.append_record(Path("security/ledger"), {"action": "probe"})
            return False, "direct ledger writer accepted a write"
        except RuntimeError:
            return True, "direct ledger writer blocked"
    except Exception as exc:
        return False, str(exc)


def check_ledger_schema_version() -> Tuple[bool, str]:
    ledger_path = LEDGER_PATH
    if not ledger_path.exists():
        return False, "ledger missing"
    events = [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not events:
        return False, "ledger empty"
    missing = [idx for idx, event in enumerate(events) if event.get("schema_version") != LEDGER_SCHEMA_VERSION]
    return not missing, f"{len(missing)} events missing or mismatching schema_version"


def run_tests() -> Tuple[bool, str]:
    try:
        subprocess.check_call(["python", "-m", "unittest"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True, "python -m unittest"
    except subprocess.CalledProcessError as exc:
        return False, f"tests failed: {exc}"


def main() -> None:
    checks: Dict[str, object] = {}

    ok_roots, roots_detail = check_roots()
    checks["structure_ok"] = ok_roots
    checks["structure_detail"] = roots_detail

    ok_inits, inits_detail = check_namespace_inits()
    checks["namespace_ok"] = ok_inits
    checks["namespace_detail"] = inits_detail

    ok_prints, prints_detail = check_print_violations()
    checks["no_print_ok"] = ok_prints
    checks["print_violations"] = prints_detail

    ok_imports, imports_detail = check_canonical_imports()
    checks["imports_ok"] = ok_imports
    checks["import_violations"] = imports_detail

    ok_runtime_logging, runtime_logging_detail = check_runtime_logging_file_io()
    checks["runtime_logging_ok"] = ok_runtime_logging
    checks["runtime_logging_detail"] = runtime_logging_detail

    ok_boot, boot_detail = check_boot_two_line_rule()
    checks["boot_rule_ok"] = ok_boot
    checks["boot_rule_detail"] = boot_detail

    ok_ledger_path, ledger_path_detail = check_ledger_path_constant()
    checks["ledger_path_ok"] = ok_ledger_path
    checks["ledger_path_detail"] = ledger_path_detail

    ok_keep, keep_detail = check_keys_keep()
    checks["keys_keep_ok"] = ok_keep
    checks["keys_keep_detail"] = keep_detail

    ok_cryo, cryo_detail = check_cryovant()
    checks["cryovant_ok"] = ok_cryo
    checks["cryovant_detail"] = cryo_detail

    ok_direct_writer, direct_writer_detail = check_direct_ledger_writer_block()
    checks["direct_writer_blocked"] = ok_direct_writer
    checks["direct_writer_detail"] = direct_writer_detail

    ok_schema_version, schema_version_detail = check_ledger_schema_version()
    checks["ledger_schema_version_ok"] = ok_schema_version
    checks["ledger_schema_version_detail"] = schema_version_detail

    ok_agents, agent_detail = check_agents()
    checks["agents_valid"] = ok_agents
    checks["agent_issues"] = agent_detail

    ok_tests, test_detail = run_tests()
    checks["tests_ok"] = ok_tests
    checks["tests_detail"] = test_detail

    checks["branding"] = {
        "asset": "ui/assets/innovativeai_llc.svg",
        "footer": "InnovativeAI LLC · ADAAD Autonomous Systems · © 2025 InnovativeAI LLC. All rights reserved.",
    }

    required_pass = [
        ok_roots,
        ok_inits,
        ok_prints,
        ok_imports,
        ok_runtime_logging,
        ok_boot,
        ok_ledger_path,
        ok_keep,
        ok_cryo,
        ok_direct_writer,
        ok_schema_version,
        ok_agents,
        ok_tests,
    ]
    checks["all_ok"] = all(required_pass)
    checks["mutation_enabled"] = checks["all_ok"]

    print(json.dumps(checks, indent=2))
    if not checks["all_ok"]:
        sys.exit(1)


if __name__ == "__main__":
    main()
