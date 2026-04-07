from __future__ import annotations

import subprocess
import sys
from pathlib import Path


SCRIPT = Path("scripts/validate_release_git_refs.py")


def _run(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )


def _init_repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)
    (repo / "README.md").write_text("ok\n", encoding="utf-8")
    subprocess.run(["git", "add", "README.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True, text=True)
    sha = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()
    script_src = Path(__file__).resolve().parents[1] / SCRIPT
    script_dst = repo / SCRIPT
    script_dst.parent.mkdir(parents=True, exist_ok=True)
    script_dst.write_text(script_src.read_text(encoding="utf-8"), encoding="utf-8")
    return repo, sha


def test_validator_passes_with_resolvable_sha(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    rel = repo / "docs" / "releases"
    rel.mkdir(parents=True)
    (rel / "1.0.0.md").write_text(f"Release SHA: `{sha}`\n", encoding="utf-8")

    result = _run(repo, "--mode", "roots", "--roots", "docs/releases")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "all referenced Git SHAs are resolvable" in result.stdout


def test_validator_fails_with_unresolvable_sha(tmp_path: Path) -> None:
    repo, _sha = _init_repo(tmp_path)
    rel = repo / "artifacts" / "governance"
    rel.mkdir(parents=True)
    (rel / "phase126_sign_off.json").write_text(
        '{"phase":126,"release_sha":"9af28a1"}\n',
        encoding="utf-8",
    )

    result = _run(repo, "--mode", "roots", "--roots", "artifacts/governance")

    assert result.returncode == 1
    assert "9af28a1" in result.stdout


def test_validator_ignores_sha256_digests(tmp_path: Path) -> None:
    repo, _sha = _init_repo(tmp_path)
    rel = repo / "artifacts" / "governance"
    rel.mkdir(parents=True)
    (rel / "phase126_sign_off.json").write_text(
        '{"evidence_hash":"sha256:0123456789abcdef0123456789abcdef0123456789abcdef0123456789abcdef"}\n',
        encoding="utf-8",
    )

    result = _run(repo, "--mode", "roots", "--roots", "artifacts/governance")

    assert result.returncode == 0, result.stdout + result.stderr


def test_changed_mode_hard_fails_when_git_diff_fails(tmp_path: Path) -> None:
    repo, _sha = _init_repo(tmp_path)

    result = _run(repo, "--mode", "changed", "--base-ref", "totally-invalid-ref...HEAD")

    assert result.returncode == 1
    assert "git diff failed while discovering changed release artifacts" in result.stdout
    assert "totally-invalid-ref...HEAD" in result.stdout
    assert "fatal:" in result.stdout


def test_changed_mode_empty_diff_is_valid_noop(tmp_path: Path) -> None:
    repo, _sha = _init_repo(tmp_path)

    result = _run(repo, "--mode", "changed", "--base-ref", "HEAD..HEAD")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "no changed release artifact files detected; skipping Git SHA resolution check" in result.stdout


def test_changed_mode_validates_refs_for_changed_files(tmp_path: Path) -> None:
    repo, sha = _init_repo(tmp_path)
    rel = repo / "docs" / "releases"
    rel.mkdir(parents=True)
    (rel / "2.0.0.md").write_text(f"Release SHA: `{sha}`\n", encoding="utf-8")
    subprocess.run(["git", "add", "docs/releases/2.0.0.md"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "add release note"], cwd=repo, check=True, capture_output=True, text=True)

    result = _run(repo, "--mode", "changed", "--base-ref", "HEAD~1..HEAD")

    assert result.returncode == 0, result.stdout + result.stderr
    assert "all referenced Git SHAs are resolvable" in result.stdout
