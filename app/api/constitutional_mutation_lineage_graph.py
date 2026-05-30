"""
REST API — Constitutional Mutation Lineage Graph (CMLG) — Phase 200
"""
from __future__ import annotations
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(__file__))))

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Any, Dict, List, Optional

from dorkllm.constitutional_mutation_lineage_graph import (
    ConstitutionalMutationLineageGraph, CMLGLineageLedger,
    GateType, EdgeStatus, CMLGConstitutionalViolation, CMLGCycleDetected,
    GOVERNOR,
)

router = APIRouter(prefix="/cmlg", tags=["CMLG"])
_graph = ConstitutionalMutationLineageGraph(ledger=CMLGLineageLedger())


class BootstrapRequest(BaseModel):
    phase: int
    version: str
    actor: str = GOVERNOR


class AddNodeRequest(BaseModel):
    mutation_id: str
    phase: int
    version: str
    gate: str
    actor: str
    metadata: Optional[Dict[str, Any]] = None


class AddEdgeRequest(BaseModel):
    source_node_id: str
    target_node_id: str
    gate_type: str
    edge_status: str
    actor: str
    metadata: Optional[Dict[str, Any]] = None


class Human0Request(BaseModel):
    node_id: str
    human0_identity: str


@router.post("/genesis")
def bootstrap_genesis(req: BootstrapRequest) -> Dict[str, Any]:
    node = _graph.bootstrap_genesis(req.phase, req.version, req.actor)
    return node.to_dict()


@router.post("/node")
def add_node(req: AddNodeRequest) -> Dict[str, Any]:
    try:
        node = _graph.add_node(
            req.mutation_id, req.phase, req.version,
            GateType(req.gate), req.actor, req.metadata,
        )
        return node.to_dict()
    except CMLGConstitutionalViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/edge")
def add_edge(req: AddEdgeRequest) -> Dict[str, Any]:
    try:
        edge = _graph.add_edge(
            req.source_node_id, req.target_node_id,
            GateType(req.gate_type), EdgeStatus(req.edge_status),
            req.actor, req.metadata,
        )
        return edge.to_dict()
    except CMLGCycleDetected as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except CMLGConstitutionalViolation as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.post("/rollback")
def mark_rolled_back(req: Human0Request) -> Dict[str, Any]:
    try:
        node = _graph.mark_rolled_back(req.node_id, req.human0_identity)
        return node.to_dict()
    except CMLGConstitutionalViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.post("/ghost/purge")
def purge_ghost(req: Human0Request) -> Dict[str, Any]:
    try:
        return _graph.purge_ghost(req.node_id, req.human0_identity)
    except CMLGConstitutionalViolation as exc:
        raise HTTPException(status_code=403, detail=str(exc))


@router.get("/path/{node_id}")
def path_to_genesis(node_id: str) -> Dict[str, Any]:
    return _graph.path_to_genesis(node_id)


@router.get("/ancestors/{node_id}")
def ancestors(node_id: str) -> Dict[str, Any]:
    return _graph.ancestors(node_id)


@router.get("/mutation/{mutation_id}")
def mutation_lineage(mutation_id: str) -> Dict[str, Any]:
    return _graph.mutation_lineage(mutation_id)


@router.get("/chain/verify")
def verify_chain() -> Dict[str, Any]:
    try:
        return {"chain_valid": _graph.verify_chain(), "governor": GOVERNOR}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc))


@router.get("/summary")
def summary() -> Dict[str, Any]:
    return _graph.graph_summary()


@router.get("/export")
def export() -> Dict[str, Any]:
    return _graph.export()
