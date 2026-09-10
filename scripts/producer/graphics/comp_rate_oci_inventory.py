"""Exact conservatively captured implementation inventory for OCI cohort V2.

The initial runner executed as __main__ and was not captured at startup. This
list deliberately retains imported dependencies, even if later judged broader
than necessary; changing one makes this historical cohort stale.
"""
from __future__ import annotations

from pathlib import Path

_CAPTURED_MODULES = (
    "cross_runtime_canonical_json.py",
    "cut_preview_io.py",
    "fingerprints.py",
    "graphics/asset_proof.py",
    "graphics/comp_capabilities.py",
    "graphics/comp_capability_artifact.py",
    "graphics/comp_catalog_probe.py",
    "graphics/comp_rate_artifact.py",
    "graphics/comp_rate_matrix.py",
    "graphics/comp_rate_oci_inputs.py",
    "graphics/composition_transform.py",
    "graphics/frame_oracles.py",
    "graphics/frame_quantization.py",
    "graphics/glyph_metrics.py",
    "graphics/graphics_render.py",
    "graphics/hyperframes_invocation.py",
    "graphics/pip_hole.py",
    "graphics/render_cache.py",
    "graphics/render_rate.py",
    "graphics/render_tools.py",
    "graphics/template_assets.py",
    "graphics/template_catalog_contract.py",
    "graphics/template_content.py",
    "graphics/template_contract.py",
    "graphics/template_hw_contract.py",
    "graphics/template_visual_contract.py",
    "headless/container_io.py",
    "headless/container_live_policy.py",
    "headless/container_policy.py",
    "headless/container_renderer.py",
    "headless/docker_identity.py",
    "headless/network_probe.py",
    "headless/runtime_receipt.py",
    "headless/safe_source_files.py",
    "headless/sealed_archive.py",
    "headless/sealed_tar_format.py",
    "headless/source_closure.py",
)


def required_execution_paths(root: Path, requests: list[dict]) -> set[Path]:
    """Require all captured implementation and exact sealed motion dependencies."""
    result = {root / "scripts/producer" / name for name in _CAPTURED_MODULES}
    motion = root / "templates/motion"
    result.add(motion / "comp_capabilities.json")
    for request in requests:
        result.add(motion / f"compositions/{request['kind']}.html")
        result.update(motion / row["path"][7:] for row in request["manifest"]
                      if row["path"].startswith("motion/"))
    return result
