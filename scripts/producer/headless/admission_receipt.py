"""One reader for external-media admission receipts, native and historical.

New admissions are made by the native macOS jail and carry policy
``sniper-external-media-probe-v4-native`` with a ``runtime`` identity and an
attested ``isolation`` record. Receipts written earlier by the container probe
(``sniper-external-media-probe-v3``: ``image``/``isolation``/``network``) stay
readable exactly as before, so existing projects keep verifying. Every reader of
a retained receipt goes through ``validate_admission_receipt``.
"""
from __future__ import annotations

import re

from headless.external_media_probe_document import validate_probe_document
from headless.external_media_probe_policy import MediaProbeLimits
from headless.external_media_probe_native import POLICY_VERSION as NATIVE_POLICY
from headless.native_media_runtime import POLICY as JAIL_POLICY, approved_pair

CONTAINER_POLICY = "sniper-external-media-probe-v3"
NATIVE_KEYS = frozenset({"schemaVersion", "policy", "snapshot", "limits", "runtime", "isolation", "decoded"})
CONTAINER_KEYS = frozenset({"schemaVersion", "policy", "snapshot", "limits", "image", "isolation", "network", "decoded"})
_SHA256 = re.compile(r"[0-9a-f]{64}")
_JAIL_MEMORY_MIB = 768
_NOT_DECODED = {"font", "svg"}


class AdmissionReceiptError(RuntimeError):
    """A retained admission receipt is malformed or not from an accepted runtime."""


def _sha(value: object) -> bool:
    return type(value) is str and _SHA256.fullmatch(value) is not None


def parse_limits(receipt: dict) -> MediaProbeLimits:
    """Recorded ceilings, with the decode timeout inside the accepted range."""
    try:
        limits = MediaProbeLimits(**receipt["limits"])
    except (TypeError, KeyError) as error:
        raise AdmissionReceiptError("external-media admission decode proof is malformed (limits)") from error
    if type(limits.max_decode_seconds) is not int or not 90 <= limits.max_decode_seconds <= 3600:
        raise AdmissionReceiptError("external-media admission decode proof is malformed (decode timeout)")
    return limits


def _runtime_valid(runtime: object) -> bool:
    """The native identity names an approved jail and hashed decoders."""
    if type(runtime) is not dict or runtime.get("kind") != "macos-seatbelt" or runtime.get("policy") != JAIL_POLICY:
        return False
    tools = runtime.get("tools")
    tools_ok = type(tools) is dict and set(tools) == {"ffprobe", "ffmpeg"} and all(
        type(row) is dict and type(row.get("path")) is str and row["path"].startswith("/") and _sha(row.get("sha256"))
        and type(row.get("version")) is str for row in tools.values())
    return (tools_ok and _sha(runtime.get("profileSha256")) and _sha(runtime.get("launcherSha256"))
            and _sha(runtime.get("closureSha256")) and type(runtime.get("closureCount")) is int
            and runtime["closureCount"] > 0 and approved_pair(runtime["profileSha256"], runtime["launcherSha256"]))


def _run_valid(run: object, decoder: str, runtime: dict) -> bool:
    """One launcher attestation: confined, capped and naming the expected decoder."""
    return (type(run) is dict and run.get("sandboxed") is True and run.get("decoder") == decoder
            and run.get("profileSha256") == runtime["profileSha256"] and run.get("memoryMiB") == _JAIL_MEMORY_MIB
            and (run.get("rlimits") or {}).get("RLIMIT_FSIZE") == [0, 0]
            and (run.get("rlimits") or {}).get("RLIMIT_CORE") == [0, 0])


def _isolation_valid(isolation: object, runtime: dict, kind: str) -> bool:
    """Decoded media needs attested ffprobe and ffmpeg runs; fonts/SVG need none."""
    fixed = {"kind": "macos-seatbelt", "policy": JAIL_POLICY, "network": "denied",
             "processCreation": "denied", "writes": "/dev/null only"}
    if type(isolation) is not dict or any(isolation.get(key) != value for key, value in fixed.items()):
        return False
    if isolation.get("profileSha256") != runtime["profileSha256"]:
        return False
    runs = isolation.get("decoderRuns")
    if kind in _NOT_DECODED:
        return runs == []
    tools = runtime["tools"]
    return (type(runs) is list and len(runs) == 2 and _run_valid(runs[0], tools["ffprobe"]["path"], runtime)
            and _run_valid(runs[1], tools["ffmpeg"]["path"], runtime)
            and isolation.get("memoryMiB") == _JAIL_MEMORY_MIB)


def validate_admission_receipt(receipt: object) -> tuple[MediaProbeLimits, dict]:
    """Validate a retained receipt's authority and decode proof.

    Args:
        receipt: The parsed receipt document.

    Returns:
        The recorded limits and the validated ``decoded`` document.

    Raises:
        AdmissionReceiptError: The receipt is malformed, from an unknown policy,
            or (native) not attested by the approved jail.
    """
    if type(receipt) is not dict or type(receipt.get("schemaVersion")) is not int or receipt["schemaVersion"] != 1:
        raise AdmissionReceiptError("external-media admission receipt is malformed")
    policy = receipt.get("policy")
    expected = {NATIVE_POLICY: NATIVE_KEYS, CONTAINER_POLICY: CONTAINER_KEYS}.get(policy)
    if expected is None or set(receipt) != expected:
        raise AdmissionReceiptError("external-media admission receipt has wrong authority")
    limits = parse_limits(receipt)
    try:
        decoded = validate_probe_document(receipt["decoded"], limits)
    except (TypeError, RuntimeError) as error:
        raise AdmissionReceiptError("external-media admission decode proof is malformed") from error
    if policy == NATIVE_POLICY:
        kind = decoded["facts"]["mediaKind"]
        if not _runtime_valid(receipt["runtime"]) or not _isolation_valid(receipt["isolation"], receipt["runtime"], kind):
            raise AdmissionReceiptError("native admission receipt is not attested by the approved jail")
    return limits, decoded
