"""Closed current render V3 catalog; historical V1/V2 path sets are frozen.

Wire V3 adds layout/deadline dependencies. Policy/domain numbering retains the
historical offset: wire V3 uses policy v4. Future path additions need a version.
"""
from __future__ import annotations

from .render_build_manifest_v2_contract import RENDER_BUILD_V2_IMPLEMENTATION_PATHS

RENDER_BUILD_V3_POLICY = "sniper-headless-render-build-v4"
RENDER_BUILD_V3_DIGEST_DOMAIN = b"sniper-render-build-v4\0"
RENDER_BUILD_V3_IMPLEMENTATION_PATHS = (
    *RENDER_BUILD_V2_IMPLEMENTATION_PATHS,
    "scripts/producer/color/deadline.py",
    "scripts/producer/graphics/template_layout_contract.py",
    "scripts/producer/headless/render_layout_contract.py",
    "scripts/producer/headless/render_layout_result.py",
    "scripts/producer/headless/render_layout_transport.py",
    "scripts/producer/headless/render_layout_worker.py",
    "scripts/producer/headless/render_build_manifest_v3_contract.py",
    "scripts/producer/headless/render_build_manifest_v3_semantics.py",
    "scripts/producer/headless/render_build_receipt_v3_semantics.py",
)
