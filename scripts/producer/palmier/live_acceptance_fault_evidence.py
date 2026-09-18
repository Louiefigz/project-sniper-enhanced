"""Persisted evidence for apply-then-response-loss acceptance cohorts."""
from __future__ import annotations

from typing import Any

from palmier.live_acceptance_runtime import AcceptanceClient


def fault_client(deadline: Any, inventory: Any) -> AcceptanceClient:
    """Create a client that loses every mutation response by construction."""
    client = AcceptanceClient(deadline, inventory)
    client.enable_boundary_faults()
    return client


def combined_receipts(*groups: list[dict]) -> list[dict]:
    """Preserve mutation order across prior, main, and cleanup clients."""
    return [receipt for group in groups for receipt in group]


def response_loss_evidence(
        inventory: Any, receipts: list[dict]) -> dict:
    """Build the explicit transport-fault claim and full proof bodies."""
    rows = inventory.rows
    return {
        "kind": "apply-then-withhold-response-v1",
        "scope": "every connected MCP mutation boundary",
        "everyMutationResponseLost": bool(rows) and all(
            row.get("outcome") == "response-lost-after-apply"
            for row in rows),
        "everyAmbiguityReconciled": bool(rows) and all(
            row.get("journalEvent") == "operation_reconciled"
            if row.get("disposition") == "desktop-journal"
            else row.get("reconciliationBound") is True
            for row in rows),
        "nonJournalReceiptCount": len(receipts),
        "receipts": receipts,
        "literalProcessKillResumeClaimed": False,
    }
