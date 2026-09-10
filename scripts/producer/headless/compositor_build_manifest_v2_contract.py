"""Closed current compositor V2 catalog; the historical V1 path set is frozen.

V2 binds the presenter/layout dependencies and its independent receipt parser.
Extending this released ordered path set requires another wire version.
"""
from __future__ import annotations

from .compositor_build_manifest_v1_contract import COMPOSITOR_BUILD_V1_IMPLEMENTATION_PATHS

COMPOSITOR_BUILD_V2_POLICY = "sniper-prebound-compositor-build-v2"
COMPOSITOR_BUILD_V2_DIGEST_DOMAIN = b"sniper-prebound-compositor-build-v2\0"
COMPOSITOR_BUILD_V2_IMPLEMENTATION_PATHS = (
    *COMPOSITOR_BUILD_V1_IMPLEMENTATION_PATHS,
    "scripts/producer/cut_preview_io.py",
    "scripts/producer/graphics/composite_layers.py",
    "scripts/producer/graphics/presenter_layout_contract.py",
    "scripts/producer/graphics/presenter_layout_geometry.py",
    "scripts/producer/graphics/presenter_layout_graph.py",
    "scripts/producer/graphics/template_layout_contract.py",
    "scripts/producer/guided_presenter_assets.py",
    "scripts/producer/guided_presenter_observation.py",
    "scripts/producer/guided_presenter_png.py",
    "scripts/producer/guided_presenter_probe_contract.py",
    "scripts/producer/guided_presenter_probe_identity.py",
    "scripts/producer/opening_prefix_contract.py",
    "scripts/producer/opening_prefix_graphs.py",
    "scripts/producer/opening_prefix_presenter.py",
    "scripts/producer/headless/compositor_build_manifest_semantics.py",
    "scripts/producer/headless/compositor_build_receipt_semantics.py",
    "scripts/producer/headless/compositor_build_manifest_v2_contract.py",
    "scripts/producer/headless/compositor_build_manifest_v2_semantics.py",
    "scripts/producer/headless/compositor_build_receipt_v2_semantics.py",
)
