"""Run-global deadline, fresh MCP sessions, and mutation accounting."""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Any, Callable, Iterator

from palmier.desktop_hook import READ_TOOLS
from palmier.live_acceptance_mutations import (
    AppliedResponseLost, MutationCall, MutationInventory)
from palmier.mcp_client import PalmierClient, PalmierError


class Deadline:
    """One monotonic deadline shared by every phase and MCP request."""

    def __init__(self, timeout_s: float):
        if timeout_s <= 0:
            raise PalmierError("live acceptance deadline must be positive")
        self.timeout_s = float(timeout_s)
        self.started = time.monotonic()

    def remaining(self) -> float:
        value = self.timeout_s - (time.monotonic() - self.started)
        if value <= 0:
            raise PalmierError(
                f"live acceptance exceeded {self.timeout_s:g}s wall-clock deadline")
        return value

    def check(self) -> None:
        self.remaining()


class AcceptanceClient:
    """Palmier facade that terminates and reconnects every mutation session."""

    def __init__(
            self, deadline: Deadline, inventory: MutationInventory,
            factory: Callable[[float], Any] | None = None):
        self.deadline, self.inventory = deadline, inventory
        self.factory = factory or (
            lambda timeout: PalmierClient(timeout_s=timeout))
        self.session: Any | None = None
        self.last_session_id: str | None = None
        self.connections: list[dict] = []
        self.response_loss_armed = False
        self.boundary_faults = False
        self.response_reconciler: Callable | None = None
        self.response_loss_receipts: list[dict] = []

    @contextmanager
    def phase(self, disposition: str) -> Iterator[None]:
        with self.inventory.phase(disposition):
            yield

    def bind_proof(self, disposition: str, proof: dict) -> None:
        """Attach phase evidence to every unbound mutation in a class."""
        self.inventory.bind_proof(disposition, proof)

    def arm_response_loss(self) -> None:
        """Withhold the next mutation response after the server applies it."""
        if self.response_loss_armed:
            raise PalmierError("mutation response-loss fault is already armed")
        self.response_loss_armed = True

    def enable_boundary_faults(self) -> None:
        """Withhold and reconcile every non-journal mutation response."""
        from palmier.live_response_reconciliation import \
            reconcile_response_loss
        self.boundary_faults = True
        self.response_reconciler = reconcile_response_loss

    def _connect(self) -> Any:
        if self.session is not None:
            return self.session
        client = self.factory(self.deadline.remaining())
        setter = getattr(client, "set_timeout_provider", None)
        if callable(setter):
            setter(self.deadline.remaining)
        client.handshake()
        ident = getattr(client, "session_id", None)
        if not isinstance(ident, str) or not ident \
                or ident == self.last_session_id:
            raise PalmierError("fresh Palmier MCP session identity was not proved")
        self.session = client
        self.last_session_id = ident
        self.connections.append({"sessionId": ident, "connectedAt": time.time()})
        return client

    def _disconnect(self) -> None:
        if self.session is None:
            return
        ident, client = self.last_session_id, self.session
        self.session = None
        client.close()
        self.connections[-1].update({
            "disconnectedAt": time.time(), "terminated": True,
            "sessionId": ident,
        })

    def _invoke(self, tool: str, args: dict) -> str:
        mutation = tool not in READ_TOOLS
        automatic = mutation and self.boundary_faults \
            and self.inventory.disposition != "desktop-journal"
        if mutation:
            self.inventory.require_classified(tool)
            self._disconnect()
            if automatic:
                self.response_loss_armed = True
        client = self._connect()
        mutation_session = str(self.last_session_id)
        if hasattr(client, "timeout_s"):
            client.timeout_s = min(
                float(client.timeout_s), self.deadline.remaining())
        outcome = "succeeded"
        reconciliation: dict | None = None
        try:
            raw = client.call(tool, args)
            if mutation and self.response_loss_armed:
                self.response_loss_armed = False
                outcome = "response-lost-after-apply"
                if automatic and callable(self.response_reconciler):
                    self._disconnect()
                    raw, reconciliation = self.response_reconciler(
                        self, tool, args, str(self.inventory.disposition))
                    return raw
                raise AppliedResponseLost(
                    f"{tool}: response withheld after server application")
            return raw
        except BaseException:
            if outcome == "succeeded":
                outcome = "failed"
                if mutation:
                    self.response_loss_armed = False
            raise
        finally:
            if mutation:
                row = self.inventory.record(MutationCall(
                    tool, args, mutation_session, outcome))
                if reconciliation is not None:
                    self.inventory.bind_reconciliation(row, reconciliation)
                    self.response_loss_receipts.append({
                        **{key: row[key] for key in (
                            "sequence", "tool", "argsHash", "sessionId",
                            "disposition", "outcome",
                        )},
                        "proofHash": row["reconciliationHash"],
                        "proof": reconciliation,
                    })
                self._disconnect()

    def call(self, tool: str, args: dict | None = None) -> str:
        return self._invoke(tool, args or {})

    def call_json(self, tool: str, args: dict | None = None) -> object:
        raw = self.call(tool, args)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as exc:
            raise PalmierError(f"{tool}: result is not JSON") from exc

    def wait_media(self, media_ref: str) -> dict:
        while True:
            value = self.call_json("get_media", {"ids": [media_ref]})
            assets = value.get("assets", value if isinstance(value, list) else [])
            row = next((item for item in assets
                        if item.get("id") == media_ref),
                       assets[0] if len(assets) == 1 else None)
            if not isinstance(row, dict):
                raise PalmierError(f"get_media: {media_ref} not in library")
            status = row.get("generationStatus")
            if status is None:
                return row
            if status == "failed":
                raise PalmierError(f"import failed for {media_ref}")
            time.sleep(min(1.0, self.deadline.remaining()))

    def close(
            self, timeout_s: float | None = None,
            deadline: Deadline | None = None) -> None:
        if self.session is not None and timeout_s is not None \
                and hasattr(self.session, "timeout_s"):
            self.session.timeout_s = max(0.001, float(timeout_s))
        setter = getattr(self.session, "set_timeout_provider", None)
        if callable(setter) and deadline is not None:
            setter(deadline.remaining)
        self._disconnect()
