"""Authority dispatch shared by surgical-native and full-plan candidates."""
from __future__ import annotations

from palmier.live_build_qc_contract import (
    authority_from_input as live_authority_from_input,
    validate_current_authority as validate_current_live_authority)
from palmier.native_qc_contract import (
    authority_from_input as native_authority_from_input,
    validate_current_authority as validate_current_native_authority)


def authority_from_input(out_dir: str, input_path: str,
                         candidate: dict, parent: dict) -> dict:
    import json
    with open(input_path, encoding="utf-8") as handle:
        value = json.load(handle)
    if isinstance(value, dict) \
            and value.get("kind") == "palmier-live-build-qc-authority":
        return live_authority_from_input(out_dir, input_path, candidate, parent)
    return native_authority_from_input(out_dir, input_path, candidate, parent)


def validate_current_authority(receipt: dict) -> dict:
    authority = receipt.get("authority") or {}
    if authority.get("kind") == "live-build":
        return validate_current_live_authority(receipt)
    return validate_current_native_authority(receipt)
