#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
import json
from dataclasses import asdict, dataclass
from pathlib import Path

HTTP_METHOD_DECORATORS = {"get", "post", "put", "delete", "patch", "options", "head", "websocket"}


@dataclass(frozen=True)
class RouteRow:
    method: str
    path: str
    handler_module: str
    handler_name: str


def _extract_path(call: ast.Call) -> str | None:
    if call.args and isinstance(call.args[0], ast.Constant) and isinstance(call.args[0].value, str):
        return call.args[0].value
    return None


def parse_routes_from_file(file_path: Path, repo_root: Path) -> list[RouteRow]:
    tree = ast.parse(file_path.read_text(encoding="utf-8"), filename=str(file_path))
    rel = file_path.relative_to(repo_root).as_posix()
    module = rel.removesuffix(".py").replace("/", ".")
    rows: list[RouteRow] = []

    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            if not isinstance(decorator, ast.Call):
                continue
            func = decorator.func
            if not isinstance(func, ast.Attribute):
                continue
            method = func.attr.lower()
            if method not in HTTP_METHOD_DECORATORS:
                continue
            path = _extract_path(decorator)
            if path is None:
                continue
            rows.append(RouteRow(method=method.upper(), path=path, handler_module=module, handler_name=node.name))

    return rows


def build_inventory(repo_root: Path) -> list[RouteRow]:
    targets = [repo_root / "server.py"] + sorted((repo_root / "app" / "api").glob("*.py"))
    rows: list[RouteRow] = []
    for target in targets:
        rows.extend(parse_routes_from_file(target, repo_root))
    rows.sort(key=lambda r: (r.path, r.method, r.handler_module, r.handler_name))
    return rows


def find_duplicates(rows: list[RouteRow]) -> dict[tuple[str, str], list[RouteRow]]:
    grouped: dict[tuple[str, str], list[RouteRow]] = {}
    for row in rows:
        grouped.setdefault((row.method, row.path), []).append(row)
    return {k: v for k, v in grouped.items() if len(v) > 1}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--fail-on-duplicates", action="store_true")
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parents[1]
    rows = build_inventory(repo_root)
    duplicates = find_duplicates(rows)

    if args.json:
        print(json.dumps({"routes": [asdict(r) for r in rows], "duplicate_routes": {f"{m} {p}": [asdict(r) for r in rs] for (m, p), rs in sorted(duplicates.items())}}, indent=2, sort_keys=True))
    else:
        for row in rows:
            print(f"{row.method:9} {row.path:50} {row.handler_module}")
        if duplicates:
            print("\nDuplicate method/path registrations detected:")
            for (method, path), dup_rows in sorted(duplicates.items()):
                print(f"- {method} {path}")
                for dup in dup_rows:
                    print(f"    -> {dup.handler_module}.{dup.handler_name}")

    return 1 if args.fail_on_duplicates and duplicates else 0


if __name__ == "__main__":
    raise SystemExit(main())
