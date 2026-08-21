"""
AI Trading System — Merkle Tree Implementation
SHA-256 based binary Merkle tree for tamper-proof audit proofs.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import List, Optional, Tuple


def _sha256(data: str | bytes) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _pair_hash(left: str, right: str) -> str:
    """Hash a pair of child nodes (always left || right, sorted for consistency)."""
    return _sha256(left + right)


@dataclass
class MerkleProof:
    """
    Inclusion proof for a leaf in the Merkle tree.
    Each step is (sibling_hash, is_left_sibling).
    """
    leaf_hash: str
    proof:     List[Tuple[str, bool]]  # (sibling_hash, sibling_is_left)
    root:      str

    def verify(self) -> bool:
        """Verify this proof against the stored root."""
        current = self.leaf_hash
        for sibling, sibling_is_left in self.proof:
            if sibling_is_left:
                current = _pair_hash(sibling, current)
            else:
                current = _pair_hash(current, sibling)
        return current == self.root

    def to_dict(self) -> dict:
        return {
            "leaf_hash": self.leaf_hash,
            "proof":     [(s, l) for s, l in self.proof],
            "root":      self.root,
            "valid":     self.verify(),
        }


class MerkleTree:
    """
    Binary Merkle tree with SHA-256 hashing.

    - Leaves are hashed data items (strings or bytes)
    - Interior nodes are hash(left_child + right_child)
    - Odd-length levels duplicate the last node
    - Root is the single hash representing all data

    Usage:
        tree = MerkleTree(["tx1", "tx2", "tx3"])
        root = tree.root
        proof = tree.get_proof(0)      # proof for leaf at index 0
        proof.verify()                 # True
    """

    def __init__(self, items: Optional[List[str]] = None) -> None:
        self._leaves:  List[str] = []   # raw (pre-hash) data
        self._hashes:  List[str] = []   # leaf hashes
        self._layers:  List[List[str]] = []
        self._root:    str = ""

        if items:
            for item in items:
                self.append(item)

    # ── Building ───────────────────────────────────────────────────────────────

    def append(self, data: str) -> str:
        """Add a new leaf and rebuild the tree. Returns the leaf hash."""
        leaf_hash = _sha256(data)
        self._leaves.append(data)
        self._hashes.append(leaf_hash)
        self._build()
        return leaf_hash

    def _build(self) -> None:
        """Rebuild all layers from the current leaf hashes."""
        if not self._hashes:
            self._layers = []
            self._root   = ""
            return

        layer = list(self._hashes)
        self._layers = [layer]

        while len(layer) > 1:
            next_layer: List[str] = []
            for i in range(0, len(layer), 2):
                left  = layer[i]
                right = layer[i + 1] if i + 1 < len(layer) else left  # duplicate last
                next_layer.append(_pair_hash(left, right))
            self._layers.append(next_layer)
            layer = next_layer

        self._root = self._layers[-1][0]

    # ── Accessors ──────────────────────────────────────────────────────────────

    @property
    def root(self) -> str:
        return self._root

    @property
    def leaf_count(self) -> int:
        return len(self._hashes)

    def get_leaf_hash(self, index: int) -> str:
        if index < 0 or index >= len(self._hashes):
            raise IndexError(f"Leaf index {index} out of range [0, {len(self._hashes)})")
        return self._hashes[index]

    # ── Proof generation ───────────────────────────────────────────────────────

    def get_proof(self, index: int) -> MerkleProof:
        """
        Generate a Merkle inclusion proof for the leaf at `index`.
        Raises IndexError if index is out of range.
        """
        if index < 0 or index >= len(self._hashes):
            raise IndexError(f"Leaf index {index} out of range")
        if not self._layers:
            raise ValueError("Empty tree")

        proof: List[Tuple[str, bool]] = []
        current_index = index

        for layer in self._layers[:-1]:  # skip the root layer
            if current_index % 2 == 0:
                # current is left child — sibling is right
                sibling_idx = current_index + 1
                sibling_is_left = False
            else:
                # current is right child — sibling is left
                sibling_idx = current_index - 1
                sibling_is_left = True

            if sibling_idx < len(layer):
                sibling_hash = layer[sibling_idx]
            else:
                sibling_hash = layer[current_index]  # duplicate

            proof.append((sibling_hash, sibling_is_left))
            current_index //= 2

        return MerkleProof(
            leaf_hash=self._hashes[index],
            proof=proof,
            root=self._root,
        )

    def verify_proof(self, proof: MerkleProof) -> bool:
        return proof.verify()

    # ── Serialization ──────────────────────────────────────────────────────────

    def to_dict(self) -> dict:
        return {
            "root":       self._root,
            "leaf_count": self.leaf_count,
            "leaves":     self._hashes,
        }

    def __repr__(self) -> str:
        return f"MerkleTree(leaves={self.leaf_count}, root={self._root[:16]}…)"
