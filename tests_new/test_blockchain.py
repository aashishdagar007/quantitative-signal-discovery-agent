"""
tests_new/test_blockchain.py
Coverage for blockchain_audit/merkle.py and blockchain_audit/ledger.py:
  - Append events → verify_chain() True
  - Merkle proof verification
  - Tamper detection: mutate payload_json in SQLite → verify_chain() False
"""

from __future__ import annotations

import json
import os
import sqlite3
import tempfile

import pytest

from blockchain_audit.merkle import MerkleTree, MerkleProof
from blockchain_audit.ledger import ImmutableLedger, Block


# ══════════════════════════════════════════════════════════════════════════════
#  Merkle Tree unit tests
# ══════════════════════════════════════════════════════════════════════════════

class TestMerkleTree:
    def test_single_leaf_root_not_empty(self) -> None:
        tree = MerkleTree(["tx1"])
        assert tree.root != ""
        assert len(tree.root) == 64  # SHA-256 hex

    def test_two_leaves_different_root(self) -> None:
        tree = MerkleTree(["tx1"])
        root1 = tree.root
        tree.append("tx2")
        root2 = tree.root
        assert root1 != root2

    def test_leaf_count(self) -> None:
        tree = MerkleTree(["a", "b", "c"])
        assert tree.leaf_count == 3

    def test_get_leaf_hash_valid(self) -> None:
        tree = MerkleTree(["hello", "world"])
        h = tree.get_leaf_hash(0)
        assert len(h) == 64

    def test_get_leaf_hash_out_of_range(self) -> None:
        tree = MerkleTree(["x"])
        with pytest.raises(IndexError):
            tree.get_leaf_hash(99)

    def test_proof_verifies(self) -> None:
        items = ["tx1", "tx2", "tx3", "tx4"]
        tree = MerkleTree(items)
        for i in range(len(items)):
            proof = tree.get_proof(i)
            assert proof.verify(), f"Proof failed for leaf {i}"

    def test_proof_invalid_after_tamper(self) -> None:
        """Modifying the root breaks proof verification."""
        tree = MerkleTree(["a", "b", "c"])
        proof = tree.get_proof(0)
        tampered = MerkleProof(
            leaf_hash=proof.leaf_hash,
            proof=proof.proof,
            root="0" * 64,   # wrong root
        )
        assert not tampered.verify()

    def test_odd_number_of_leaves(self) -> None:
        """Odd-length layer duplicates last node — must not crash."""
        tree = MerkleTree(["a", "b", "c", "d", "e"])
        assert tree.leaf_count == 5
        # All proofs must verify
        for i in range(5):
            assert tree.get_proof(i).verify()

    def test_to_dict(self) -> None:
        tree = MerkleTree(["x", "y"])
        d = tree.to_dict()
        assert "root" in d
        assert "leaf_count" in d
        assert d["leaf_count"] == 2


# ══════════════════════════════════════════════════════════════════════════════
#  ImmutableLedger — in-memory tests
# ══════════════════════════════════════════════════════════════════════════════

class TestImmutableLedgerInMemory:
    @pytest.fixture()
    def ledger(self) -> ImmutableLedger:
        """Fresh in-memory ledger (genesis block already written)."""
        return ImmutableLedger(":memory:")

    def test_genesis_block_present(self, ledger) -> None:
        assert ledger.block_count() >= 1

    def test_verify_fresh_chain(self, ledger) -> None:
        ok, msg = ledger.verify_chain()
        assert ok, f"Fresh chain failed: {msg}"

    def test_append_trade_and_verify(self, ledger) -> None:
        ledger.log_trade({
            "symbol": "BTCUSDT", "side": "buy",
            "quantity": 0.01, "price": 65000,
        })
        ok, msg = ledger.verify_chain()
        assert ok, msg

    def test_append_multiple_events_and_verify(self, ledger) -> None:
        ledger.log_trade({"symbol": "ETHUSDT", "side": "sell", "quantity": 0.1, "price": 3200})
        ledger.log_ai_consensus({"symbol": "BTCUSDT", "direction": "long", "confidence": 0.75})
        ledger.log_state_change({"component": "engine", "from": "PAPER", "to": "LIVE"})
        ledger.log_system("Test system event")
        ok, msg = ledger.verify_chain()
        assert ok, msg
        assert ledger.block_count() >= 5  # genesis + 4

    def test_block_count_increases(self, ledger) -> None:
        before = ledger.block_count()
        ledger.log_system("event 1")
        ledger.log_system("event 2")
        assert ledger.block_count() == before + 2

    def test_merkle_proof_for_tx(self, ledger) -> None:
        block = ledger.log_trade({"symbol": "SOLUSDT", "side": "buy", "quantity": 5.0, "price": 150})
        proof = ledger.get_proof(block.tx_id)
        assert proof is not None
        assert proof.verify()

    def test_state_change_logged_correctly(self, ledger) -> None:
        block = ledger.log_state_change({
            "component": "trading_mode",
            "from": "PAPER",
            "to": "LIVE",
            "reason": "admin toggle",
        })
        assert block.event_type == "state_change"
        assert block.payload["to_state"] == "LIVE"

    def test_get_blocks_filter_by_event_type(self, ledger) -> None:
        ledger.log_trade({"symbol": "BTCUSDT", "side": "buy", "quantity": 1, "price": 60000})
        ledger.log_system("background event")
        trades = ledger.get_blocks(event_type="trade")
        assert all(b["event_type"] == "trade" for b in trades)


# ══════════════════════════════════════════════════════════════════════════════
#  Tamper detection — file-backed SQLite
# ══════════════════════════════════════════════════════════════════════════════

class TestTamperDetection:
    def test_tamper_breaks_chain(self, tmp_path) -> None:
        """
        Directly mutating payload_json in the SQLite file must cause
        verify_chain() to return (False, ...) because the stored block_hash
        was computed from the original payload.
        """
        db_path = str(tmp_path / "audit.db")

        # Build a 3-event chain
        ledger = ImmutableLedger(db_path)
        ledger.log_trade({"symbol": "BTCUSDT", "side": "buy", "quantity": 0.01, "price": 65000})
        ledger.log_trade({"symbol": "ETHUSDT", "side": "sell", "quantity": 0.5, "price": 3200})
        ledger.close()

        # Verify chain is intact before tampering
        fresh = ImmutableLedger(db_path)
        ok, msg = fresh.verify_chain()
        assert ok, f"Pre-tamper check failed: {msg}"
        fresh.close()

        # Directly mutate the payload of block 1 (first real trade)
        conn = sqlite3.connect(db_path)
        row = conn.execute(
            "SELECT id, payload_json FROM blocks WHERE block_index = 1"
        ).fetchone()
        assert row is not None, "Block at index 1 not found"
        original_payload = json.loads(row[1])
        original_payload["price"] = 999999  # tamper
        conn.execute(
            "UPDATE blocks SET payload_json = ? WHERE id = ?",
            (json.dumps(original_payload), row[0]),
        )
        conn.commit()
        conn.close()

        # Now re-open the ledger and verify — must detect tampering
        tampered = ImmutableLedger(db_path)
        ok, msg = tampered.verify_chain()
        tampered.close()
        assert not ok, "verify_chain() should have detected the tampered payload"
        assert "invalid hash" in msg.lower() or "mismatch" in msg.lower(), (
            f"Expected a hash-related error message, got: {msg}"
        )

    def test_chain_link_break_detected(self, tmp_path) -> None:
        """Zeroing previous_hash of block 2 must break chain link detection."""
        db_path = str(tmp_path / "link_test.db")
        ledger = ImmutableLedger(db_path)
        ledger.log_system("event A")
        ledger.log_system("event B")
        ledger.close()

        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE blocks SET previous_hash = ? WHERE block_index = 2",
            ("0" * 64,),
        )
        conn.commit()
        conn.close()

        reopened = ImmutableLedger(db_path)
        ok, msg = reopened.verify_chain()
        reopened.close()
        assert not ok, "Chain link break should be detected"
