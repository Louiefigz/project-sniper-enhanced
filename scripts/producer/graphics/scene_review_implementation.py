"""Frozen source closure recorded by private scene-review receipts."""
from __future__ import annotations

import hashlib
from pathlib import Path

from current_render_toolchain import current_toolchain_hash
from fingerprints import file_sha256
from graphics.scene_contract import canonical_json

_IMPLEMENTATION = (
    "graphics/scene_review_repair.py",
    "graphics/scene_review_project.py",
    "graphics/scene_review_implementation.py",
    "graphics/scene_review_media.py",
    "graphics/scene_review_repair_cli.py",
    "graphics/scene_package_render.py",
    "graphics/scene_package_contract.py",
    "graphics/scene_render.py",
    "graphics/scene_contract.py",
    "graphics/render_tools.py",
    "palmier/scene_bindings.py",
    "palmier/scene_binding_reader.py",
    "audio/channel_normalization.py",
    "audio/channel_normalization_receipt.py",
    "edit/exact_timing.py",
    "cross_runtime_canonical_json.py",
    "fingerprints.py",
)


def implementation_closure() -> dict:
    """Hash the complete bounded-review implementation surface."""
    root = Path(__file__).resolve().parents[1]
    files = {
        name: file_sha256(str(root / name))
        for name in _IMPLEMENTATION
    }
    return {
        "files": files,
        "closureHash": hashlib.sha256(canonical_json(files)).hexdigest(),
        "producerRenderToolchainHash": current_toolchain_hash(),
    }
