"""One validated read of the ACTIVE render graph, with raw pointer agreement.

Selection and retained paths must come from the same original read. The
generation directory and receipt name are derived from the validated objects'
own canonical hashes, the raw ACTIVE bytes must name exactly those hashes, the
retained graph/receipt bytes must hash back to the validated objects, and all
three files are held by the bytes that were actually read. Two separate reads
let an A->B->A generation flip pair one generation's selection with another's
files while every hash still checked. This reader grants no approval.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from current_render_graph_contract import ACTIVE_NAME, GRAPH_DIR, object_hash
from current_render_graph_store import load_active, validate_active_pointer
from cut_preview_io import read_bytes


@dataclass(frozen=True)
class HeldGeneration:
    """The validated graph/execution pair and its files held by exact read bytes."""

    graph: dict
    execution: dict
    files: dict[str, str]


def _read(path: Path) -> tuple[bytes, str]:
    """Read a bounded regular file once; hash exactly those bytes."""
    raw = read_bytes(path)
    return raw, hashlib.sha256(raw).hexdigest()


def _parsed_hash(raw: bytes) -> str:
    """Canonical hash of the object the retained bytes actually encode."""
    try:
        return object_hash(json.loads(raw))
    except ValueError as error:
        raise RuntimeError("retained render graph generation bytes are not JSON") from error


def held_active_generation(root: Path) -> HeldGeneration | None:
    """Select and hold the ACTIVE generation from one validated read, or None."""
    previous = load_active(root)
    if previous is None:
        return None
    graph, execution = previous
    graph_hash, receipt_hash = object_hash(graph), object_hash(execution)
    store = root / GRAPH_DIR
    generation = store / "generations" / graph_hash
    paths = {"active": store / ACTIVE_NAME, "graph": generation / "graph.json",
             "receipt": generation / "receipts" / f"{receipt_hash}.json"}
    raw = {key: _read(path) for key, path in paths.items()}
    try:
        active = json.loads(raw["active"][0])
    except ValueError as error:
        raise RuntimeError("active render graph pointer bytes are not JSON") from error
    if validate_active_pointer(active) != (graph_hash, receipt_hash):   # same closed v1 shape as load_active
        raise RuntimeError("active render graph pointer no longer names the validated generation")
    if _parsed_hash(raw["graph"][0]) != graph_hash or _parsed_hash(raw["receipt"][0]) != receipt_hash:
        raise RuntimeError("retained render graph generation bytes differ from the validated read")
    return HeldGeneration(graph, execution, {str(path): raw[key][1] for key, path in paths.items()})
