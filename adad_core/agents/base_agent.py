"""Reference agent implementing the ADAAD-required surface."""
from __future__ import annotations

from adad_core.evolve.mutator import mutate_source


INFO = {
    "id": "base_agent",
    "version": 1,
    "description": "Baseline agent that echoes input and stays deterministic.",
}


def info() -> dict:
    return INFO


def run(input=None) -> dict:
    message = str(input) if input is not None else "pong"
    return {"status": "ok", "echo": message}


def mutate(src: str) -> str:
    return mutate_source(src)


def score(output: dict) -> float:
    return 1.0 if output.get("status") == "ok" else 0.0


if __name__ == "__main__":
    run()
