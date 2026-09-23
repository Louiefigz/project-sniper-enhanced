"""Desktop presenter-hole asset contracts."""
import os
import tempfile
import unittest
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from palmier.presenter_asset import (PresenterRequest, _filter_graph,
                                     _source_slices, fill_presenter_assets,
                                     fill_presenter_entry)


def _entry():
    return {"id": "hole-1", "kind": "module-ledger-dark",
            "anchor": "own-screen", "outStart": 1.0, "outEnd": 4.0,
            "faceCx": 0.53, "spec": {"presenterFrame": True}}


class PresenterSliceTests(unittest.TestCase):
    def test_output_window_maps_across_speed_adjusted_cuts(self):
        plan = {"cutTrack": [
            {"sourceId": "src", "start": 10.0, "end": 12.0, "speed": 1.0},
            {"sourceId": "src", "start": 20.0, "end": 24.0, "speed": 2.0},
        ]}
        entry = {**_entry(), "outStart": 1.0, "outEnd": 3.0}
        self.assertEqual(_source_slices(plan, entry), [
            {"sourceId": "src", "speed": 1.0, "start": 11.0, "end": 12.0},
            {"sourceId": "src", "speed": 2.0, "start": 20.0, "end": 22.0},
        ])

    def test_non_hole_graphics_are_byte_stable(self):
        graphics = {0: "/cache/card.mov"}
        plan = {"graphicsTrack": [{"kind": "statement-card",
                                    "spec": {"text": "Hello"}}]}
        self.assertEqual(
            fill_presenter_assets(plan, {}, graphics, "/cache"), graphics)


class PresenterRenderTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.source_path = os.path.join(self.tmp.name, "source.mp4")
        self.alpha_path = os.path.join(self.tmp.name, "alpha.mov")
        for path in (self.source_path, self.alpha_path):
            with open(path, "wb") as handle:
                handle.write(b"fixture")
        self.plan = {"cutTrack": [
            {"sourceId": "src", "start": 0.0, "end": 10.0, "speed": 1.0},
        ]}
        self.source = {"id": "src", "path": self.source_path,
                       "contentHash": "source-hash",
                       "resolution": [1920, 1080]}
        self.rendered = {"path": self.alpha_path, "proof": {"asset": {
            "sha256": "card-hash", "frameCount": 90, "durationS": 3.0}}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_hole_asset_renders_only_the_mapped_presenter_window(self):
        request = PresenterRequest(
            self.plan, self.source, _entry(), self.rendered, self.tmp.name)

        def fake_render(_request, output, _graph, _frames, _fps):
            with open(output, "wb") as handle:
                handle.write(b"filled")

        proof = {"schemaVersion": 1, "asset": {"sha256": "filled-hash"}}
        with patch("palmier.presenter_asset._render", side_effect=fake_render) as run, \
                patch("palmier.presenter_asset.prove_rendered_asset",
                      return_value=proof):
            result = fill_presenter_entry(request)
        self.assertEqual(run.call_count, 1)
        self.assertEqual(result["presenterFill"]["sourceSlices"], [{
            "sourceId": "src", "speed": 1.0, "start": 1.0, "end": 4.0}])
        self.assertEqual(result["presenterFill"]["hole"], [1344, 60, 534, 960])
        self.assertTrue(os.path.isfile(result["path"]))

    def test_filter_places_presenter_beneath_the_alpha_card(self):
        request = PresenterRequest(
            self.plan, self.source, _entry(), self.rendered, self.tmp.name)
        slices = _source_slices(self.plan, _entry())
        graph = _filter_graph(
            request, slices, (600, 1080, 418, 0), 30.0, 3.0)
        self.assertIn("overlay=x=1344:y=60", graph)
        self.assertIn("[under][0:v]overlay=x=0:y=0", graph)


if __name__ == "__main__":
    unittest.main()
