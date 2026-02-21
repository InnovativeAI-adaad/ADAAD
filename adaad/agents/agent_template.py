# SPDX-License-Identifier: Apache-2.0
"""Canonical governed agent contract template."""

from __future__ import annotations

AGENT_ID = "template.agent"
VERSION = "1.0.0"
CAPABILITIES = ["mutation.apply_ops"]
GOAL_SCHEMA = {"type": "object", "properties": {"task": {"type": "string"}}, "required": ["task"]}
OUTPUT_SCHEMA = {"type": "object", "properties": {"status": {"type": "string"}}, "required": ["status"]}
SPAWN_POLICY = {"allow_spawn": False, "max_children": 0}


def get_agent_manifest() -> dict:
    return {
        "agent_id": AGENT_ID,
        "version": VERSION,
        "capabilities": CAPABILITIES,
        "goal_schema": GOAL_SCHEMA,
        "output_schema": OUTPUT_SCHEMA,
        "spawn_policy": SPAWN_POLICY,
    }


def run_goal(goal) -> dict:
    task = str((goal or {}).get("task", ""))
    return {"status": "ok", "task": task}


def info() -> dict:
    return {"id": AGENT_ID, "version": VERSION}


def run(input=None) -> dict:
    return {"status": "ok", "input": input}


def mutate(src: str) -> str:
    return src


def score(output: dict) -> float:
    return 1.0 if output.get("status") == "ok" else 0.0
