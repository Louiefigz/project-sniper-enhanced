"""Closed NPL dispatch and actual sealed metadata, not a native media test."""
from __future__ import annotations

import copy
import tempfile
import time
import unittest
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import guided_caption_graphic_observation as observer
from guided_caption_profile import CAPTION_PROFILE, SCREENED_CAPTION_PROFILE
from guided_caption_screen import admit_screen, screen_intent_preflight, supported_layout
from guided_caption_screen_read import validate_graphic_request
from guided_opening_execution import OpeningExecutionClock
from guided_opening_graphic_proof import intent_record
from headless.container_io import CompositionInput, create_snapshot
from headless.render_layout_contract import PIPELINE_POLICY, role_inventory, sealed_documents
from test_guided_caption_graphic_observation import H, intent, request
from test_guided_caption_screen import admission_context

ROOT = Path(__file__).resolve().parents[3]
COMPOSITION = "compositions/module-pipeline.html"


def pipeline_intent(changes: dict | None = None) -> object:
    """TEST endpoints retain original order/full span, never resize to an opening."""
    original = intent()
    spec = {"layout": "caption-safe-upper-v1", "nodes": "01~One|02~Two", "eyebrow": "",
        "headlineLines": "", "explainer": "", "footChip": "", "presenterFrame": False, "exit": "hold"}
    entry = {"kind": "module-pipeline", "anchor": "own-screen", "spec": {**spec, **(changes or {})}}
    return replace(original, row={**original.row, "order": 2, "entry": entry})


class PipelineObservationTests(unittest.TestCase):
    def test_exact_original_kind_selects_separate_policy_and_full_ntsc_span(self) -> None:
        """Hold the complete native animation under its distinct owner policy."""
        held = pipeline_intent()
        actual = observer.observed_execution_request({**request(), "intent": intent_record(held)}, held)
        self.assertEqual(actual["captionLayoutPolicy"], observer.PIPELINE_GRAPHIC_POLICY)
        self.assertEqual(actual["layoutRequest"]["profile"], PIPELINE_POLICY)
        self.assertEqual(actual["layoutRequest"]["composition"], COMPOSITION)
        self.assertEqual(actual["layoutRequest"]["totalFrames"], 120)
        self.assertEqual(actual["layoutRequest"]["frameRate"], "30000/1001")
        validate_graphic_request(actual, {"captionLayoutObservation": {}}, SCREENED_CAPTION_PROFILE, "opening")

    def test_kind_composition_policy_and_legacy_transplants_fail_closed(self) -> None:
        """Reject mixing independently held agenda, pipeline and legacy classes."""
        held = pipeline_intent()
        actual = observer.observed_execution_request({**request(), "intent": intent_record(held)}, held)
        for mutate in (lambda value: value.update(captionLayoutPolicy=observer.GRAPHIC_POLICY),
                       lambda value: value["layoutRequest"].update(profile="sealed-agenda-css-layout-v1"),
                       lambda value: value["layoutRequest"].update(composition="compositions/agenda-slide.html"),
                       lambda value: value["intent"]["entry"].update(kind="agenda-slide")):
            changed = copy.deepcopy(actual)
            mutate(changed)
            with self.assertRaises((RuntimeError, ValueError)):
                validate_graphic_request(changed, {"captionLayoutObservation": {}}, SCREENED_CAPTION_PROFILE, "opening")
        with self.assertRaises(RuntimeError):
            validate_graphic_request(actual, {"captionLayoutObservation": {}}, CAPTION_PROFILE, "opening")

    def test_actual_sealed_input_derives_all_three_roles_and_rejects_wrong_profile(self) -> None:
        """Read original HTML and variables from the actual newly sealed archive."""
        actual = pipeline_intent()
        with tempfile.TemporaryDirectory(prefix="TEST-pipeline-screen-seal-") as root:
            held = self._seal(actual, Path(root).resolve())
            local = observer.observation_request(intent_record(held))
            data = sealed_documents(held.snapshot, local)
            self.assertEqual([row["id"] for row in role_inventory(data, local["profile"])],
                             ["connector-1", "node-1", "node-2"])
            with self.assertRaises((KeyError, ValueError)):
                role_inventory(data, "sealed-agenda-css-layout-v1")

    def test_malformed_cells_presenter_and_exit_reject_before_actual_render(self) -> None:
        """Unsupported role content cannot trigger a native renderer invocation."""
        for changed in ({"nodes": "01~One|02~"}, {"presenterFrame": True}, {"presenterFrame": 0},
                        {"exit": "blur-recede"}, {"headlineLines": "One||Two"}):
            with tempfile.TemporaryDirectory(prefix="TEST-pipeline-screen-reject-") as root:
                actual = self._seal(pipeline_intent(changed), Path(root).resolve())
                clock = OpeningExecutionClock(time.monotonic() + 10)
                runtime = SimpleNamespace(timeout_seconds=90, image_id="sha256:" + H)
                with patch.object(observer, "render_to", side_effect=AssertionError("native must not launch")) as render:
                    with self.assertRaises(ValueError):
                        observer.render_observed_graphic(actual, Path(root) / "new.mp4", (clock, runtime, "TEST"))
                    render.assert_not_called()

    def test_default_pipeline_requires_actual_cue_gap_and_upper_class_is_bounded(self) -> None:
        """Never infer compatibility for the unchanged default or portrait class."""
        row = pipeline_intent().row
        context = admission_context([row])
        self.assertTrue(supported_layout(row, context.inputs.documents["authority"]))
        with patch("guided_caption_screen.held_cues", return_value=[{"startFrame": 682, "endFrameExclusive": 684}]):
            context = replace(context, coverage={"startFrame": 0, "endFrameExclusive": 1000})
            self.assertEqual(admit_screen(context, lambda: None), {2})
            row["entry"]["spec"]["layout"] = "full-canvas"
            with self.assertRaises(RuntimeError):
                admit_screen(context, lambda: None)
        row["entry"]["spec"]["layout"] = "caption-safe-upper-v1"
        context.inputs.documents["authority"]["target"] = {"width": 1080, "height": 1920}
        with self.assertRaisesRegex(RuntimeError, "class"):
            screen_intent_preflight(context.inputs, [row])

    @staticmethod
    def _seal(actual: object, root: Path) -> object:
        """Use real ordinary local closure capture, with no Docker/cache identity."""
        html = (ROOT / "templates/motion" / COMPOSITION).read_text()
        snapshot = create_snapshot(str(ROOT), CompositionInput(COMPOSITION, html, duration=4.004),
                                   actual.row["entry"]["spec"], str(root))
        return replace(actual, snapshot=snapshot)
