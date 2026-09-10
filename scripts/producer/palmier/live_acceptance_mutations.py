"""Mutation inventory and proof binding for connected Palmier acceptance."""
from __future__ import annotations

import hashlib
import json
from collections import Counter
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

from palmier.mcp_client import PalmierError

_TERMINAL_EVENTS = {"operation_verified", "operation_reconciled"}
_DISPOSITIONS = {
    "project-lifecycle", "bootstrap-authority", "candidate-fork",
    "desktop-journal", "qc-export", "manual-preservation",
    "cleanup-restore",
}


class AppliedResponseLost(PalmierError):
    """Injected transport ambiguity after the server applied a mutation."""


@dataclass(frozen=True)
class MutationCall:
    """One completed non-read MCP call awaiting inventory persistence."""

    tool: str
    args: dict
    session_id: str
    outcome: str


def digest(value: object) -> str:
    """Return the canonical JSON SHA-256 used by all live receipts."""
    blob = json.dumps(value, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()


class MutationInventory:
    """Account for every non-read MCP tool call and its disposition."""

    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = [dict(row) for row in (rows or [])]
        self.disposition: str | None = None

    @contextmanager
    def phase(self, disposition: str) -> Iterator[None]:
        if disposition not in _DISPOSITIONS:
            raise PalmierError(
                f"unknown live mutation disposition {disposition!r}")
        previous = self.disposition
        self.disposition = disposition
        try:
            yield
        finally:
            self.disposition = previous

    def record(self, call: MutationCall) -> dict:
        disposition = self.disposition
        if disposition is None:
            raise PalmierError(
                f"unclassified live Palmier mutation {call.tool!r}")
        row = {
            "sequence": len(self.rows) + 1, "tool": call.tool,
            "argsHash": digest(call.args), "sessionId": call.session_id,
            "disposition": disposition, "outcome": call.outcome,
        }
        self.rows.append(row)
        return row

    def require_classified(self, tool: str) -> None:
        """Reject a mutation before transport when no disposition is active."""
        if self.disposition is None:
            raise PalmierError(
                f"unclassified live Palmier mutation {tool!r}")

    def bind_reconciliation(self, row: dict, proof: dict) -> None:
        """Bind one non-journal ambiguity to tool-specific fresh readback."""
        if not isinstance(proof, dict) or not isinstance(
                proof.get("kind"), str):
            raise PalmierError("live response-loss proof is malformed")
        row.update({
            "reconciliationBound": True,
            "reconciliationKind": proof["kind"],
            "reconciliationHash": digest(proof),
        })

    def bind_desktop_journal(self, path: str) -> None:
        try:
            values = [json.loads(line) for line in Path(path).read_text(
                encoding="utf-8").splitlines() if line.strip()]
        except (OSError, json.JSONDecodeError) as exc:
            raise PalmierError(
                f"live mutation journal is unreadable: {exc}") from exc
        expected = [
            (row.get("tool"), row.get("argsHash"), row.get("event"))
            for row in values if row.get("event") in _TERMINAL_EVENTS
        ]
        governed = [
            (row["tool"], row["argsHash"]) for row in self.rows
            if row["disposition"] == "desktop-journal"
        ]
        if governed != [(tool, value) for tool, value, _event in expected]:
            raise PalmierError(
                "live governed mutation inventory differs from Desktop journal")
        rows = [
            row for row in self.rows
            if row["disposition"] == "desktop-journal"
        ]
        for row, (_tool, _value, event) in zip(rows, expected):
            row.update({"journalBound": True, "journalEvent": event})

    def bind_proof(self, disposition: str, proof: dict) -> None:
        """Bind every newly completed phase mutation to fresh readback/QC."""
        if disposition not in _DISPOSITIONS \
                or not isinstance(proof, dict) \
                or not isinstance(proof.get("kind"), str):
            raise PalmierError("live mutation proof binding is malformed")
        proof_hash = digest(proof)
        for row in self.rows:
            if row["disposition"] == disposition \
                    and row.get("proofBound") is not True:
                row.update({
                    "proofBound": True, "proofKind": proof["kind"],
                    "proofHash": proof_hash,
                })

    @staticmethod
    def _response_loss_proved(row: dict) -> bool:
        if row["outcome"] != "response-lost-after-apply":
            return True
        if row["disposition"] == "desktop-journal":
            return row.get("journalEvent") == "operation_reconciled"
        return row.get("reconciliationBound") is True

    def assert_response_loss_receipts(self, receipts: list[dict]) -> None:
        """Require exact persisted proof bodies for every non-journal fault."""
        rows = [
            row for row in self.rows
            if row["disposition"] != "desktop-journal"
        ]
        if not isinstance(receipts, list) or len(receipts) != len(rows):
            raise PalmierError(
                "live response-loss receipt count differs from inventory")
        for row, receipt in zip(rows, receipts):
            proof = receipt.get("proof") if isinstance(receipt, dict) else None
            expected = {
                key: row.get(key) for key in (
                    "sequence", "tool", "argsHash", "sessionId",
                    "disposition", "outcome",
                )
            }
            actual = {
                key: receipt.get(key) for key in expected
            } if isinstance(receipt, dict) else {}
            valid = (
                actual == expected
                and isinstance(proof, dict)
                and digest(proof) == row.get("reconciliationHash")
                and receipt.get("proofHash") == row.get("reconciliationHash")
            )
            if not valid:
                raise PalmierError(
                    "live response-loss receipt differs from inventory")

    def assert_complete(
            self, required: set[str] | None = None,
            require_response_loss: bool = False) -> None:
        accepted = {"succeeded", "response-lost-after-apply"}
        if any(row["outcome"] not in accepted for row in self.rows):
            raise PalmierError("live mutation inventory contains failed calls")
        if require_response_loss and any(
                row["outcome"] != "response-lost-after-apply"
                for row in self.rows):
            raise PalmierError(
                "live fault cohort contains an ordinary mutation response")
        if any(not self._response_loss_proved(row) for row in self.rows):
            raise PalmierError(
                "ambiguous applied mutation lacks reconciliation proof")
        if any(row["disposition"] == "desktop-journal"
               and row.get("journalBound") is not True for row in self.rows):
            raise PalmierError("live governed mutation lacks journal disposition")
        if any(row.get("proofBound") is not True for row in self.rows):
            raise PalmierError(
                "live mutation lacks fresh readback or QC proof")
        sessions = [row["sessionId"] for row in self.rows]
        if len(sessions) != len(set(sessions)):
            raise PalmierError(
                "live mutation boundaries reused an MCP session")
        observed = Counter(row["disposition"] for row in self.rows)
        expected = required or {
            "project-lifecycle", "bootstrap-authority",
            "desktop-journal",
        }
        if any(not observed[name] for name in expected):
            raise PalmierError("live mutation inventory is incomplete")

    def snapshot(self) -> dict:
        return {
            "schemaVersion": 1, "mutationCount": len(self.rows),
            "rows": list(self.rows),
        }
