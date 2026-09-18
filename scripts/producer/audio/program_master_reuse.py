"""Reuse a retained full-program master only when a held selection proves it.

A graphics-copy or caption revision must not rebuild unchanged audio. The public
``program_audio.v2.json`` pointer merely names a candidate; the prior ACTIVE
render graph's ``node-final`` program receipt is the independently held
selection (the same authority picture reuse uses), and ``load_program_master``
then re-proves the bus binding, the plan's requested music and finishing
settings, the consumed asset bytes, policy versions and the exact code closure.
Without a held selection nothing is reused. Terminal deadline or cancellation
errors propagate; only a genuinely stale or invalid receipt rebuilds. Held body
preparation still wins. Nothing here grants approval.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

from audio.held_render_graph import held_active_generation
from audio.program_master_bus import ProgramMaster
from audio.program_master_cache import load_program_master
from audio.render_audio_authority import SOURCE_FLOAT_POLICY_V2
from color.deadline import WallBudgetExceeded
from cut_preview_io import read_bytes
from headless.process_runner import ProcessDeadlineError
from palmier.mcp_client import PalmierError

PROGRAM_AUDIO_POINTER = "program_audio.v2.json"
# Cancellation is terminal: it may never become a cache miss that starts a rebuild.
CANCELLATION = (WallBudgetExceeded, ProcessDeadlineError, PalmierError, TimeoutError,
                subprocess.TimeoutExpired)


def held_program_selection(root: Path, output: Path) -> tuple[str, dict[str, str]] | None:
    """The prior ACTIVE graph's node-final program receipt for this exact output, held by one read."""
    generation = held_active_generation(root)
    if generation is None:
        return None
    final = next(row for row in generation.graph["nodes"] if row["nodeId"] == "node-final")
    artifact = next(row for row in generation.execution["artifacts"] if row["nodeId"] == "node-final")
    held = final["inputDigests"].get("audio.programReceipt")
    if artifact["path"] != str(output) or type(held) is not str:
        return None
    return held, dict(generation.files)


def _pointer_bytes(root: Path) -> tuple[bytes, str]:
    """Read the pointer once; the hash of exactly those bytes is what gets held."""
    raw = read_bytes(root / PROGRAM_AUDIO_POINTER)
    return raw, hashlib.sha256(raw).hexdigest()


def _pointer(root: Path) -> tuple[dict | None, str | None, str | None]:
    """(pointer, decline reason, sha256 of the parsed bytes): a candidate name, never authority."""
    path = root / PROGRAM_AUDIO_POINTER
    if not path.exists():
        return None, "no retained program-audio pointer", None
    raw, digest = _pointer_bytes(root)
    try:
        pointer = json.loads(raw)
    except ValueError:
        return None, "retained pointer is not JSON", None
    if type(pointer) is not dict or pointer.get("schemaVersion") != 2 \
            or pointer.get("kind") != "ordinary-program-audio-pointer" \
            or pointer.get("audioClockPolicy") != SOURCE_FLOAT_POLICY_V2 \
            or any(type(pointer.get(key)) is not str
                   for key in ("programMasterReceiptPath", "programMasterReceiptHash")):
        return None, "retained pointer is not a v2 program-audio pointer", None
    return pointer, None, digest


def retained_program_master(job: Any, bus: Any, root: Path) -> tuple[ProgramMaster | None, str | None, dict[str, str]]:
    """(master, decline reason, held files): reuse only a held, re-proved master.

    The pointer bytes are hashed BEFORE the loader and rechecked after it; a pointer
    that changes during selection is a fail-closed error, never a late re-hold."""
    pointer, reason, digest = _pointer(root)
    if pointer is None:
        return None, reason, {}
    selection = held_program_selection(root, Path(job.out).absolute())
    if selection is None:
        return None, "no held prior render graph selects a program master for this output", {}
    held, files = selection
    if pointer["programMasterReceiptHash"] != held:
        return None, "retained pointer differs from the held render-graph selection", {}
    try:
        master = load_program_master(bus, job.plan, (pointer["programMasterReceiptPath"], held))
    except CANCELLATION:
        raise
    except (OSError, ValueError, RuntimeError) as error:
        return None, str(error), {}
    if _pointer_bytes(root)[1] != digest:
        raise RuntimeError("program-audio pointer changed during master selection")
    files[str(root / PROGRAM_AUDIO_POINTER)] = digest
    return master, None, files


def select_program_master(job: Any, bus: Any, preparation: Any,
                          build: Callable[[Any, dict], ProgramMaster]) -> tuple[ProgramMaster, bool, dict[str, str]]:
    """Held preparation wins; otherwise a held, proved retained master; else one fresh ``build``.

    The caller passes its own ``build_program_master`` reference so the existing
    held-preparation tests can still prove that a held body never remasters."""
    from assemble import emit
    if preparation:
        return preparation.selection.master, False, {}
    master, reason, files = retained_program_master(job, bus, Path(job.out).absolute().parent)
    if master is not None:
        emit(status="program_master_reused", receiptHash=master.receipt["receiptHash"])
        return master, True, files
    emit(status="program_master_rebuilt", reason=reason)
    return build(bus, job.plan), False, {}
