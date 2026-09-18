"""Strong held-byte readback for the opt-in sealed CSS geometry observation."""
from __future__ import annotations

import hashlib
import json
import math
import os
import stat
from collections.abc import Callable
from dataclasses import dataclass

from headless.container_io import SealedInput
from headless.render_layout_contract import (
    MAX_RESULT_BYTES, bounded_bytes, encoded_request, role_inventory,
    sealed_documents, sha,
)
from headless.render_layout_result import validate_observation
from headless.runtime_receipt import validate_runtime_attestation

Guard = Callable[[], None]


@dataclass(frozen=True)
class LayoutReadExpectation:
    """Independent actual return references, not facts discovered in a sidecar."""

    request: dict
    media_sha256: str
    observation_sha256: str
    proof_sha256: str
    image_id: str
    observer_sources: list[dict]


def _held_json(path: str, expected: str, limit: int) -> tuple[bytes, dict]:
    """Hold exactly the originally returned raw bytes before interpreting them."""
    sha(expected)
    raw = bounded_bytes(path, limit)
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("layout retained raw evidence hash differs")
    return raw, json.loads(raw)


def _media(path: str, guard: Guard) -> dict:
    """Stream the exact current regular media within the caller's original cap."""
    guard()
    fd = os.open(path, os.O_RDONLY | os.O_NONBLOCK | os.O_NOFOLLOW)
    try:
        before = os.fstat(fd)
        if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1 \
                or before.st_uid != os.geteuid() or not 0 < before.st_size <= 512 * 1024 * 1024:
            raise ValueError("layout observed media is not one bounded owned file")
        digest, size = hashlib.sha256(), 0
        while chunk := os.read(fd, 1024 * 1024):
            guard()
            size += len(chunk)
            if size > before.st_size or size > 512 * 1024 * 1024:
                raise ValueError("layout media exceeded held byte limit while streaming")
            digest.update(chunk)
        after = os.fstat(fd)
        keys = ("st_dev", "st_ino", "st_size", "st_mtime_ns", "st_ctime_ns", "st_mode")
        if size != before.st_size or any(getattr(before, key) != getattr(after, key) for key in keys):
            raise ValueError("layout media changed while streaming")
        return {"sha256": digest.hexdigest(), "sizeBytes": size}
    finally:
        os.close(fd)


def _runtime(proof: dict, expected: LayoutReadExpectation, path: str) -> dict:
    """Reuse actual network/container/archive proof, with exact observer launch."""
    runtime = proof["runtimeAttestation"]
    validate_runtime_attestation(runtime, path, expected.media_sha256, expected.image_id)
    if runtime["snapshotSha256"] != expected.request["snapshotSha256"]:
        raise ValueError("layout runtime used a different sealed input")
    for name in ("containerBeforeOutput", "containerAfterOutput"):
        env = dict(row.split("=", 1) for row in runtime[name]["Config"]["Env"])
        if env.get("SNIPER_LAYOUT_REQUEST") != encoded_request(expected.request):
            raise ValueError("layout runtime omitted/changed explicit observer admission")
    layout = runtime.get("layoutObservation")
    if type(layout) is not dict or layout.get("sha256") != expected.observation_sha256:
        raise ValueError("layout raw observation is not bound to owned runtime return")
    return runtime


def read_observation(path: str, expected: LayoutReadExpectation, guard: Guard) -> tuple[dict, dict]:
    """Read immutable actual output facts; does not launch, decode or approve."""
    guard()
    if not os.path.isabs(path) or os.path.realpath(path) != path:
        raise ValueError("layout readback path must be canonical")
    raw, value = _held_json(path + ".layout.json", expected.observation_sha256, MAX_RESULT_BYTES)
    proof_raw, proof = _held_json(path + ".proof.json", expected.proof_sha256, 4 * 1024 * 1024)
    media = _media(path, guard)
    if media["sha256"] != expected.media_sha256:
        raise ValueError("layout current media differs from actual owned completion")
    runtime = _runtime(proof, expected, path)
    snapshot = SealedInput(path + ".input.tar", runtime["snapshotSha256"], tuple(runtime["snapshotManifest"]))
    documents = sealed_documents(snapshot, expected.request)
    validate_observation(value, expected.request, {"observerSources": expected.observer_sources,
                        "media": media, "roleInventory": role_inventory(documents, expected.request["profile"])})
    guard()
    if _media(path, guard) != media or bounded_bytes(path + ".proof.json", 4 * 1024 * 1024) != proof_raw:
        raise ValueError("layout media/proof changed during final readback")
    if bounded_bytes(path + ".layout.json", MAX_RESULT_BYTES) != raw:
        raise ValueError("layout observation changed during final readback")
    guard()
    return {"path": path + ".layout.json", "sha256": expected.observation_sha256}, value


def screening_envelopes(observation: dict) -> list[dict]:
    """Project already strongly held all-frame CSS bounds, never serial authority.

    No current reader calls this automatically. The owner must independently
    bind this graphic's full-program occurrence/declaration and unchanged source
    closure. These boxes screen CSS envelopes, NOT pixel ink/creative quality.
    """
    if observation["status"] != "observed":
        raise ValueError("unqualified layout cannot become a screening observation")
    rows = []
    for role in observation["roleInventory"]:
        boxes = [item["bounds"] for frame in observation["frames"] for item in frame["roles"]
                 if item["id"] == role["id"] and item["bounds"] is not None]
        if not boxes:
            raise ValueError("required layout role was never visible")
        box = [math.floor(min(item[0] for item in boxes)), math.floor(min(item[1] for item in boxes)),
               math.ceil(max(item[2] for item in boxes)), math.ceil(max(item[3] for item in boxes))]
        rows.append({"id": role["id"], "bounds": box, "overflow": False})
    return rows
