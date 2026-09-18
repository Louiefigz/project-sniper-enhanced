"""Closed current V2 build catalog; historical V1 bytes remain unchanged.

V2 adds the runtime log guard and versioned receipt verification. The V1
catalog is an immutable historical base, not a dynamically discovered closure.
Changing this released path set requires another version, not extending V2.
"""

from __future__ import annotations

from .render_build_manifest_v1_contract import RENDER_BUILD_V1_IMPLEMENTATION_PATHS

RENDER_BUILD_V2_POLICY = "sniper-headless-render-build-v3"
RENDER_BUILD_V2_DIGEST_DOMAIN = b"sniper-render-build-v3\0"
RENDER_BUILD_V2_IMPLEMENTATION_PATHS = (
    *RENDER_BUILD_V1_IMPLEMENTATION_PATHS,
    "scripts/producer/headless/render_build_manifest_semantics.py",
    "scripts/producer/headless/render_build_manifest_v2_contract.py",
    "scripts/producer/headless/render_build_manifest_v2_semantics.py",
    "scripts/producer/headless/render_build_receipt_semantics.py",
    "scripts/producer/headless/render_build_receipt_v2_semantics.py",
    "scripts/producer/headless/render_log_guard.py",
    "scripts/producer/headless/wire_identity.py",
)
