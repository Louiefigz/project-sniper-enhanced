"""P4 catalog graphics bind target FPS through cache, render, and proof."""
from __future__ import annotations

import unittest
from unittest import mock

from graphics import graphics_render as gr
from graphics import graphics_stage as stage
from headless.container_io import SealedInput


def _work(fps: float, snapshot: SealedInput | None = None) -> gr._RenderWork:
    return gr._RenderWork(
        entry={"kind": "synthetic", "anchor": "free-band", "spec": {},
               "outStart": 0, "outEnd": 1},
        fmt="mov", dimensions=(1920, 1080), duration=1.0, key="a" * 40,
        temp_rel="compositions/synthetic.html", temp_abs="",
        comp_html="<html></html>", spec={}, snapshot=snapshot,
        capability_probe=False, fps=fps)


class GraphicsTargetFpsTests(unittest.TestCase):
    def test_fps_changes_live_and_sealed_cache_identity(self) -> None:
        html = "<html data-composition-variables='[]'></html>"
        with mock.patch.object(gr, "discover_root_sources", return_value={}), \
             mock.patch.object(gr, "live_tools_identity", return_value=b"tools"):
            at_24 = gr.content_hash("synthetic", {}, 1.0, html, 24.0)
            at_30 = gr.content_hash("synthetic", {}, 1.0, html, 30.0)
        self.assertNotEqual(at_24, at_30)
        snapshot = SealedInput("/sealed.tar", "b" * 64, ())
        with mock.patch.object(gr, "container_cache_identity",
                               return_value=b"image"):
            sealed_24 = gr._sealed_hash("synthetic", snapshot, 24.0)
            sealed_30 = gr._sealed_hash("synthetic", snapshot, 30.0)
        self.assertNotEqual(sealed_24, sealed_30)

    def test_live_invocation_receives_fractional_target_rate(self) -> None:
        with mock.patch.object(gr, "render_composition") as render:
            gr._render_to(
                "compositions/card.html", "mov", {}, "/tmp/card.mov",
                30000 / 1001)
        invocation = render.call_args.args[0]
        self.assertAlmostEqual(invocation.fps, 30000 / 1001)

    def test_container_request_and_media_proof_receive_target_rate(self) -> None:
        snapshot = SealedInput("/sealed.tar", "b" * 64, ())
        work = _work(24000 / 1001, snapshot)
        with mock.patch.object(gr, "render_in_container") as render:
            gr._render_candidate(work, "/tmp/candidate.mov")
        request = render.call_args.args[0]
        self.assertAlmostEqual(request.fps, 24000 / 1001)
        live = _work(24000 / 1001)
        with mock.patch.object(
                gr, "prove_rendered_asset",
                return_value={"schemaVersion": 1, "asset": {}}) as prove:
            gr._prove_candidate(live, "/tmp/candidate.mov")
        proof_request = prove.call_args.args[0]
        self.assertAlmostEqual(proof_request.expected_fps, 24000 / 1001)

    def test_graphics_stage_probes_base_rate_and_passes_it_to_renderer(self) -> None:
        rendered = {
            "path": "unit.mov", "cached": True, "key": "k",
            "kind": "chip-row", "fmt": "mov",
        }
        entry = {
            "kind": "chip-row", "anchor": "free-band",
            "outStart": 1.0, "outEnd": 2.0, "spec": {},
        }
        geometry = {"anchor": "free-band", "region": None}
        with mock.patch.object(stage, "_clip_fps",
                               return_value=30000 / 1001), \
             mock.patch.object(stage, "_clip_dims",
                               return_value=(1920, 1080)), \
             mock.patch.object(stage, "render_entry",
                               return_value=rendered) as render, \
             mock.patch.object(stage, "resolve_placement",
                               return_value=(0, 0, geometry)), \
             mock.patch.object(stage, "_delivery_geometry",
                               return_value=(0, 0, geometry)), \
             mock.patch.object(stage, "_fallback_placement_evidence",
                               return_value=geometry), \
             mock.patch.object(stage, "placement_row",
                               return_value={"gazeDistFrac": 0.1}), \
             mock.patch.object(stage, "emit"):
            stage._render_all(stage.GraphicsJob("base.mov", "unused.mov", [entry]))
        self.assertAlmostEqual(render.call_args.args[2], 30000 / 1001)

    def test_invalid_rates_fail_before_render_or_cache_use(self) -> None:
        html = "<html data-composition-variables='[]'></html>"
        for value in (0.0, -1.0, float("inf"), float("nan")):
            with self.subTest(fps=value), self.assertRaisesRegex(
                    ValueError, "FPS"):
                gr.content_hash("synthetic", {}, 1.0, html, value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
