"""Shared quality contract for governed Desktop Palmier worklists."""

import os

from fingerprints import file_sha256
from palmier.desktop_audio_authority import (require_audio_authority,
                                             validate_audio_authority_receipt)
from palmier.desktop_audio_declaration import read_audio_authority_declaration
from palmier.desktop_state import read_record
from palmier.mcp_client import PalmierError
from palmier.native_qc_contract import stable_hash


def quality_contract() -> dict:
    """Return the operator-visible visual and editorial acceptance contract."""
    return {
        "readbackCadence": "after every risky/dependency-producing batch",
        "framing": "face must remain in the measured clear region at payoff",
        "typography": "consistent family/scale; no text-background camouflage",
        "contrast": {"normalTextMin": 4.5, "largeTextMin": 3.0},
        "graphics": "vary information anatomy; never repeat a form when a compatible form fits",
        "faceBridge": {
            "authority": "copy the plan's informationForm→kind→chassis tuple exactly",
            "cream": "left rail with measured presenter-safe right-side footage",
            "dark": "own-screen canvas with the registered persistent right presenter hole",
            "forbidden": "generic lower-third, payoff, or glass fallback",
        },
        "transitions": "use only earned, supported seam punctuation; hard cuts need rationale",
        "color": ("inspect exposure, contrast, saturation, temperature, "
                  "skin tone, and shot matching"),
        "final": "exact candidate export + deterministic Audit B + composition/editorial reviews",
    }


def _current_ref(state: dict, key: str) -> dict:
    value = state.get(key)
    path = value.get("path") if isinstance(value, dict) else None
    digest = value.get("hash") if isinstance(value, dict) else None
    if not isinstance(path, str) or not isinstance(digest, str) \
            or not os.path.isfile(path) or os.path.islink(path) \
            or file_sha256(path) != digest:
        raise PalmierError(f"Desktop Palmier {key} authority changed")
    return value


def qc_authority(state: dict) -> dict:
    """Recompute a stable Desktop authority from current immutable artifacts."""
    plan = _current_ref(state, "plan")
    manifest = _current_ref(state, "manifest")
    gates = _current_ref(state, "gates")
    operations = _current_ref(state, "operations")
    audio = read_audio_authority_declaration(state)
    authority = {
        "schemaVersion": 1, "kind": "desktop-build",
        "planHash": plan["hash"], "manifestHash": manifest["hash"],
        "gatesHash": gates["hash"], "operationsHash": operations["hash"],
        "candidateFingerprint": state.get("expectedFingerprint"),
        "audioAuthorityDeclaration": audio,
        "audioAuthorityBindingDigest": stable_hash(
            state.get("audioAuthority")),
        "editPlan": read_record(plan["path"], "plan"),
    }
    revision = state.get("revision")
    if isinstance(revision, dict):
        ref = _current_ref(state, "revision")
        authority["revisionSet"] = read_record(ref["path"], "revision")
    return {**authority, "inputDigest": stable_hash(authority)}


def export_desktop_candidate(client: object, state: dict,
                             found: object) -> dict:
    """Block before export unless one exact audible route is proved."""
    audio = require_audio_authority(state, found)
    from palmier.native_qc_export import export_candidate
    export = export_candidate(client, state["outDir"], found)
    return {**export, "audioRouteAuthority": audio}


def validate_current_desktop_qc(state: dict, found: object) -> dict:
    """Re-read export, audit, parity, and input bytes before approval."""
    qc = state.get("qc")
    if not isinstance(qc, dict):
        raise PalmierError("Desktop Palmier QC evidence is missing")
    authority = qc_authority(state)
    if qc.get("authority") != authority:
        raise PalmierError("Desktop Palmier QC input authority is stale")
    audio = require_audio_authority(state, found)
    if qc.get("audioRouteAuthority") != audio:
        raise PalmierError("Desktop Palmier audio-route authority is stale")
    receipt = {
        "outDir": state["outDir"], "export": qc.get("export"),
        "authority": authority, "deterministic": qc.get("audit"),
    }
    from palmier.native_qc import validate_current_audit
    from palmier.native_qc_contract import validate_export
    validate_export(receipt)
    validate_audio_authority_receipt(
        (qc.get("export") or {}).get("audioRouteAuthority"),
        found.fingerprint)
    validate_current_audit(receipt, found)
    return qc
