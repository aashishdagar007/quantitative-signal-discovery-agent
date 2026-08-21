"""
AI Trading System — Blockchain Audit REST API
FastAPI router exposing the ImmutableLedger as HTTP endpoints.
Mounted at /audit in the main app.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from blockchain_audit.ledger import ImmutableLedger

# ── Ledger singleton ──────────────────────────────────────────────────────────
_ledger: Optional[ImmutableLedger] = None


def get_ledger() -> ImmutableLedger:
    global _ledger
    if _ledger is None:
        db_path = os.environ.get("BLOCKCHAIN_DB_PATH", "./data/blockchain_audit.db")
        _ledger = ImmutableLedger(db_path)
    return _ledger


# ── FastAPI micro-app (mountable) ─────────────────────────────────────────────
app = FastAPI(
    title="Blockchain Audit API",
    description="Immutable Merkle-chain ledger for AI Trading System audit trail",
    version="1.0.0",
)


# ── Pydantic schemas ──────────────────────────────────────────────────────────

class TradePayload(BaseModel):
    id:       Optional[str] = None
    symbol:   str
    side:     str
    quantity: float
    price:    float
    exchange: str = "binance"


class ConsensusPayload(BaseModel):
    symbol:     str
    direction:  str
    confidence: float
    signature:  Optional[str] = None


class StateChangePayload(BaseModel):
    component: str
    from_state: str
    to_state:   str
    reason:     str = ""


class BlockResponse(BaseModel):
    block_index:   int
    timestamp:     float
    event_type:    str
    tx_id:         str
    block_hash:    str
    merkle_root:   str
    previous_hash: str
    payload:       Dict[str, Any]


# ── Endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health")
def health():
    ledger = get_ledger()
    return {"status": "ok", "block_count": ledger.block_count()}


@app.get("/blocks", response_model=List[BlockResponse])
def list_blocks(
    event_type: Optional[str] = Query(None),
    limit:      int = Query(50, ge=1, le=200),
    offset:     int = Query(0, ge=0),
):
    """List blockchain blocks, newest first."""
    return get_ledger().get_blocks(event_type=event_type, limit=limit, offset=offset)


@app.get("/verify")
def verify_chain():
    """Full chain integrity verification."""
    valid, message = get_ledger().verify_chain()
    return {"valid": valid, "message": message, "block_count": get_ledger().block_count()}


@app.get("/proof/{tx_id}")
def get_proof(tx_id: str):
    """Return Merkle inclusion proof for a transaction."""
    proof = get_ledger().get_proof(tx_id)
    if proof is None:
        raise HTTPException(status_code=404, detail=f"Transaction {tx_id} not found")
    return proof.to_dict()


@app.post("/log/trade", response_model=BlockResponse)
def log_trade(payload: TradePayload):
    """Log an executed trade to the blockchain."""
    block = get_ledger().log_trade(payload.dict())
    return block.to_dict()


@app.post("/log/consensus", response_model=BlockResponse)
def log_consensus(payload: ConsensusPayload):
    """Log an AI consensus decision."""
    block = get_ledger().log_ai_consensus(payload.dict())
    return block.to_dict()


@app.post("/log/state", response_model=BlockResponse)
def log_state(payload: StateChangePayload):
    """Log a system state change."""
    block = get_ledger().log_state_change(payload.dict())
    return block.to_dict()


@app.get("/stats")
def stats():
    ledger = get_ledger()
    valid, msg = ledger.verify_chain()
    return {
        "block_count": ledger.block_count(),
        "merkle_root": ledger._merkle.root,
        "chain_valid": valid,
        "integrity_message": msg,
    }
