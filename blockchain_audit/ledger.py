"""
AI Trading System — Immutable Blockchain Audit Ledger
SQLite-backed Merkle chain. Append-only. Every write is tamper-evident.

Schema:
  blocks(id, timestamp, event_type, payload_json, tx_id, previous_hash, merkle_root, block_hash)

Usage:
    ledger = ImmutableLedger("./data/audit.db")
    ledger.log_trade({"symbol": "BTCUSDT", "price": 65000, "side": "buy", "qty": 0.01})
    ledger.verify_chain()   # → True
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from blockchain_audit.merkle import MerkleProof, MerkleTree

# ══════════════════════════════════════════════════════════════════════════════
#  Block data class
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class Block:
    index:         int
    timestamp:     float
    event_type:    str
    payload:       Dict[str, Any]
    tx_id:         str
    previous_hash: str
    merkle_root:   str
    block_hash:    str = field(init=False)

    def __post_init__(self) -> None:
        self.block_hash = self._compute_hash()

    def _compute_hash(self) -> str:
        record = {
            "index":         self.index,
            "timestamp":     self.timestamp,
            "event_type":    self.event_type,
            "payload":       self.payload,
            "tx_id":         self.tx_id,
            "previous_hash": self.previous_hash,
            "merkle_root":   self.merkle_root,
        }
        raw = json.dumps(record, sort_keys=True, ensure_ascii=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def is_valid(self) -> bool:
        return self.block_hash == self._compute_hash()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "index":         self.index,
            "timestamp":     self.timestamp,
            "event_type":    self.event_type,
            "tx_id":         self.tx_id,
            "previous_hash": self.previous_hash,
            "merkle_root":   self.merkle_root,
            "block_hash":    self.block_hash,
            "payload":       self.payload,
        }


# ══════════════════════════════════════════════════════════════════════════════
#  Immutable Ledger
# ══════════════════════════════════════════════════════════════════════════════

GENESIS_HASH = "0" * 64

class ImmutableLedger:
    """
    Append-only blockchain backed by SQLite.
    Blocks are linked via previous_hash and each contains a Merkle root
    of all transaction IDs in the chain up to that point.
    """

    def __init__(self, db_path: str = "") -> None:
        self._db_path = db_path or os.environ.get("BLOCKCHAIN_DB_PATH", "./data/blockchain_audit.db")

        # Ensure directory exists (unless in-memory)
        if self._db_path != ":memory:":
            Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._merkle = MerkleTree()
        self._init_db()
        self._rebuild_merkle()

    # ── Schema ─────────────────────────────────────────────────────────────────

    def _init_db(self) -> None:
        cur = self._conn.cursor()
        cur.executescript("""
            CREATE TABLE IF NOT EXISTS blocks (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                block_index     INTEGER NOT NULL UNIQUE,
                timestamp       REAL    NOT NULL,
                event_type      TEXT    NOT NULL,
                payload_json    TEXT    NOT NULL,
                tx_id           TEXT    NOT NULL UNIQUE,
                previous_hash   TEXT    NOT NULL,
                merkle_root     TEXT    NOT NULL,
                block_hash      TEXT    NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_blocks_event_type ON blocks (event_type);
            CREATE INDEX IF NOT EXISTS idx_blocks_timestamp   ON blocks (timestamp DESC);
        """)

        # Genesis block
        if cur.execute("SELECT COUNT(*) FROM blocks").fetchone()[0] == 0:
            self._append_block(
                event_type="genesis",
                payload={"message": "AI Trading System Blockchain Initialized"},
                previous_hash=GENESIS_HASH,
            )
        self._conn.commit()

    def _rebuild_merkle(self) -> None:
        """Rebuild in-memory Merkle tree from stored tx_ids."""
        rows = self._conn.execute("SELECT tx_id FROM blocks ORDER BY block_index ASC").fetchall()
        for row in rows:
            self._merkle.append(row["tx_id"])

    # ── Internal block creation ────────────────────────────────────────────────

    def _get_last_block(self) -> Optional[sqlite3.Row]:
        return self._conn.execute(
            "SELECT * FROM blocks ORDER BY block_index DESC LIMIT 1"
        ).fetchone()

    def _append_block(
        self,
        event_type: str,
        payload: Dict[str, Any],
        previous_hash: str,
    ) -> Block:
        last = self._get_last_block()
        index = (last["block_index"] + 1) if last else 0

        tx_id = str(uuid.uuid4())
        ts    = time.time()

        # Add tx_id to Merkle tree
        self._merkle.append(tx_id)
        merkle_root = self._merkle.root

        block = Block(
            index         = index,
            timestamp     = ts,
            event_type    = event_type,
            payload       = payload,
            tx_id         = tx_id,
            previous_hash = previous_hash,
            merkle_root   = merkle_root,
        )

        self._conn.execute(
            """INSERT INTO blocks
               (block_index, timestamp, event_type, payload_json, tx_id,
                previous_hash, merkle_root, block_hash)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                block.index,
                block.timestamp,
                block.event_type,
                json.dumps(block.payload, ensure_ascii=True),
                block.tx_id,
                block.previous_hash,
                block.merkle_root,
                block.block_hash,
            ),
        )
        self._conn.commit()
        return block

    def _log(self, event_type: str, payload: Dict[str, Any]) -> Block:
        last = self._get_last_block()
        previous_hash = last["block_hash"] if last else GENESIS_HASH
        return self._append_block(event_type, payload, previous_hash)

    # ── Public logging API ────────────────────────────────────────────────────

    def log_trade(self, trade: Dict[str, Any]) -> Block:
        """Record an executed trade."""
        payload = {
            "event":     "trade",
            "trade_id":  trade.get("id", str(uuid.uuid4())),
            "symbol":    trade.get("symbol", ""),
            "side":      trade.get("side", ""),
            "quantity":  trade.get("quantity", 0),
            "price":     trade.get("price", 0),
            "exchange":  trade.get("exchange", ""),
            "timestamp": trade.get("timestamp", datetime.utcnow().isoformat()),
        }
        return self._log("trade", payload)

    def log_ai_consensus(self, consensus: Dict[str, Any]) -> Block:
        """Record an AI desk consensus decision."""
        payload = {
            "event":     "consensus",
            "symbol":    consensus.get("symbol", ""),
            "direction": consensus.get("direction", ""),
            "confidence": consensus.get("confidence", 0),
            "signature": consensus.get("signature", ""),
            "timestamp": datetime.utcnow().isoformat(),
        }
        return self._log("consensus", payload)

    def log_state_change(self, change: Dict[str, Any]) -> Block:
        """Record a system state change."""
        payload = {
            "event":     "state_change",
            "component": change.get("component", ""),
            "from_state": change.get("from", ""),
            "to_state":  change.get("to", ""),
            "reason":    change.get("reason", ""),
            "timestamp": datetime.utcnow().isoformat(),
        }
        return self._log("state_change", payload)

    def log_order(self, order: Dict[str, Any]) -> Block:
        """Record an order submission."""
        return self._log("order", {**order, "event": "order",
                                   "timestamp": datetime.utcnow().isoformat()})

    def log_system(self, message: str, details: Optional[Dict] = None) -> Block:
        """Record a system event."""
        return self._log("system", {
            "event":   "system",
            "message": message,
            "details": details or {},
            "timestamp": datetime.utcnow().isoformat(),
        })

    # ── Chain integrity ────────────────────────────────────────────────────────

    def verify_chain(self) -> Tuple[bool, str]:
        """
        Walk the entire chain and verify:
        1. Each block's hash is valid
        2. Each block references the correct previous_hash
        Returns (is_valid, message).
        """
        rows = self._conn.execute(
            "SELECT * FROM blocks ORDER BY block_index ASC"
        ).fetchall()

        if not rows:
            return False, "Empty chain"

        prev_hash = GENESIS_HASH

        for row in rows:
            block = Block(
                index         = row["block_index"],
                timestamp     = row["timestamp"],
                event_type    = row["event_type"],
                payload       = json.loads(row["payload_json"]),
                tx_id         = row["tx_id"],
                previous_hash = row["previous_hash"],
                merkle_root   = row["merkle_root"],
            )

            # Re-derive and check block hash
            if not block.is_valid():
                return False, f"Block {row['block_index']} has invalid hash"

            if block.block_hash != row["block_hash"]:
                return False, f"Block {row['block_index']} stored hash mismatch"

            # Skip genesis previous_hash check
            if row["block_index"] == 0:
                prev_hash = block.block_hash
                continue

            if block.previous_hash != prev_hash:
                return False, f"Block {row['block_index']} breaks chain link"

            prev_hash = block.block_hash

        return True, f"Chain valid — {len(rows)} blocks verified"

    # ── Merkle proof ───────────────────────────────────────────────────────────

    def get_proof(self, tx_id: str) -> Optional[MerkleProof]:
        """Get Merkle inclusion proof for a specific transaction ID."""
        rows = self._conn.execute(
            "SELECT tx_id FROM blocks ORDER BY block_index ASC"
        ).fetchall()
        tx_ids = [r["tx_id"] for r in rows]
        try:
            idx = tx_ids.index(tx_id)
            return self._merkle.get_proof(idx)
        except (ValueError, IndexError):
            return None

    # ── Query ──────────────────────────────────────────────────────────────────

    def get_blocks(
        self,
        event_type: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        if event_type:
            rows = self._conn.execute(
                "SELECT * FROM blocks WHERE event_type=? ORDER BY block_index DESC LIMIT ? OFFSET ?",
                (event_type, limit, offset),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "SELECT * FROM blocks ORDER BY block_index DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()

        result = []
        for row in rows:
            result.append({
                "block_index":  row["block_index"],
                "timestamp":    row["timestamp"],
                "event_type":   row["event_type"],
                "tx_id":        row["tx_id"],
                "block_hash":   row["block_hash"],
                "merkle_root":  row["merkle_root"],
                "previous_hash": row["previous_hash"],
                "payload":      json.loads(row["payload_json"]),
            })
        return result

    def block_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM blocks").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
