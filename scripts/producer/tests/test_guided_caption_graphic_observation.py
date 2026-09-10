"""No-daemon tests of the production render/read seam and original clock."""
from __future__ import annotations

import copy
import signal
import time
import unittest
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import guided_caption_graphic_observation as observer
from graphics.render_rate import RenderRate
from guided_caption_profile import CAPTION_PROFILE, SCREENED_CAPTION_PROFILE
from guided_caption_screen_read import observation_reader, validate_graphic_request
from guided_opening_execution import OpeningExecutionClock
from guided_opening_graphic_proof import OpeningGraphicIntent, intent_record
from guided_opening_graphics import _render_asset
from headless.container_io import SealedInput

H = "a" * 64


def runtime_return() -> dict:
    """Synthetic live-return protocol; not a Docker attestation."""
    return {"outputSha256": H, "layoutObservation": {"sha256": H}}


def intent() -> OpeningGraphicIntent:
    """Deliberately synthetic pre-spawn metadata; no snapshot bytes are claimed."""
    row = {"graphicId": "TEST-agenda", "entryHash": H, "startFrame": 682, "endFrameExclusive": 802,
        "entry": {"kind": "agenda-slide", "anchor": "own-screen", "spec": {"layout": "caption-safe-upper-v1"}}}
    return OpeningGraphicIntent(row, RenderRate(30000, 1001), SealedInput("/TEST/input.tar", H, ()),
                                (1920, 1080), ("TEST title",), H)


def request(phase: str = "opening") -> dict:
    """Build exact ordinary invocation shape before additive observation request."""
    identity = {"executionInputHash": H} if phase == "opening" else {"inputSha256": H, "executionActivationSha256": H}
    return {"schemaVersion": 1, "kind": f"private-{phase}-ordinary-at-rate-oci",
        "scope": "not-fixed30-presealed-v2-not-approval", **identity, "containerName": "TEST-name",
        "imageId": "sha256:" + H, "build": {}, "intent": intent_record(intent())}


def mocked_render(stack: ExitStack) -> tuple:
    """Mock external/media sinks only; keep actual deadline/request code running."""
    documents = {"motion/compositions/agenda-slide.html": b"TEST not rendered"}
    for name, value in (("sealed_documents", documents), ("role_inventory", []),
                        ("required_runtime", SimpleNamespace(image_id="sha256:" + H)),
                        ("approved_sources", []), ("file_hash", H),
                        ("_asset", {"asset": {"sha256": H}, "runtimeAttestation": {
                            **runtime_return(), "retainedInputArchive": {"TEST": "not actual"}}})):
        stack.enter_context(patch.object(observer, name, return_value=value))
    returned = stack.enter_context(patch.object(observer, "read_observation", return_value=({}, {"status": "observed"})))
    render = stack.enter_context(patch.object(observer, "render_to", return_value=runtime_return()))
    return render, returned


class ObservedRequestTests(unittest.TestCase):
    def test_local_ntsc_request_is_full_original_animation_not_opening_trim(self) -> None:
        old = request()
        new = observer.observed_execution_request(old, intent())
        self.assertEqual(new["layoutRequest"]["totalFrames"], 120)
        self.assertEqual(new["layoutRequest"]["frameRate"], "30000/1001")
        self.assertEqual(old["schemaVersion"], 1)
        validate_graphic_request(new, {"captionLayoutObservation": {}}, SCREENED_CAPTION_PROFILE, "opening")
        with self.assertRaises(RuntimeError):
            validate_graphic_request(new, {"captionLayoutObservation": {}}, CAPTION_PROFILE, "opening")

    def test_exact_request_fields_version_and_owner_class_are_closed(self) -> None:
        for phase in ("opening", "body"):
            old = request(phase)
            validate_graphic_request(old, {}, CAPTION_PROFILE, phase)
            observed = observer.observed_execution_request(old, intent())
            for mutate in (lambda value: value.update(schemaVersion=True),
                           lambda value: value.update(unexpected="TEST"),
                           lambda value: value.update(scope=old["scope"]),
                           lambda value: value["layoutRequest"].update(totalFrames=119)):
                value = copy.deepcopy(observed)
                mutate(value)
                with self.assertRaises(RuntimeError):
                    validate_graphic_request(value, {"captionLayoutObservation": {}}, SCREENED_CAPTION_PROFILE, phase)
            with self.assertRaises(RuntimeError):
                validate_graphic_request(observed, {}, SCREENED_CAPTION_PROFILE, phase)

    def test_partial_or_invented_animation_span_rejects(self) -> None:
        value = intent_record(intent())
        value["fullAnimationFrames"] = 60
        with self.assertRaises(RuntimeError):
            observer.observation_request(value)

    def test_ordinary_path_keeps_legacy_stage_and_does_not_import_observer_call(self) -> None:
        clock = SimpleNamespace(phase=lambda stage, call, limit: (stage, call(), limit))
        runtime = SimpleNamespace(timeout_seconds=90)
        with patch("guided_opening_graphics.graphics_render.render_entry_at_rate", return_value="TEST") as old, \
                patch.object(observer, "render_observed_graphic", side_effect=AssertionError("new observer")):
            value, observed = _render_asset(intent(), Path("/TEST"), (clock, runtime, "TEST", "body-actual-ordinary-at-rate-oci"), False)
        self.assertEqual(value, ("body-actual-ordinary-at-rate-oci", "TEST", 90))
        self.assertIsNone(observed)
        old.assert_called_once()


class ObservedOwnerTests(unittest.TestCase):
    def test_render_owns_timer_cleanup_and_receives_one_original_deadline(self) -> None:
        clock = OpeningExecutionClock(time.monotonic() + 20)
        runtime = SimpleNamespace(timeout_seconds=90, image_id="sha256:" + H)
        with ExitStack() as stack:
            render, read = mocked_render(stack)
            def actual_boundary(value: object) -> dict:
                self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)
                self.assertEqual(value.layout_deadline, clock.end)
                self.assertEqual(value.fps, "30000/1001")
                self.assertEqual(value.snapshot, intent().snapshot)
                return runtime_return()
            render.side_effect = actual_boundary
            result, metadata = observer.render_observed_graphic(intent(), Path("/TEST/new.mp4"), (clock, runtime, "TEST-name"))
        self.assertFalse(result["cached"])
        self.assertEqual(metadata["request"]["totalFrames"], 120)
        self.assertEqual(clock.events[-1]["status"], "complete")
        read.assert_called_once()
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_expiry_after_render_cannot_renew_proof_time_or_fallback(self) -> None:
        clock = OpeningExecutionClock(time.monotonic() + 20)
        runtime = SimpleNamespace(timeout_seconds=90, image_id="sha256:" + H)
        with ExitStack() as stack:
            render, read = mocked_render(stack)
            def late(_value: object) -> None:
                clock.end = time.monotonic() - 1
            render.side_effect = late
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                observer.render_observed_graphic(intent(), Path("/TEST/new.mp4"), (clock, runtime, "TEST-name"))
        self.assertEqual(clock.events[-1]["status"], "failed")
        self.assertEqual(render.call_count, 1)
        read.assert_not_called()
        self.assertEqual(signal.getitimer(signal.ITIMER_REAL)[0], 0)

    def test_unqualified_actual_geometry_does_not_complete(self) -> None:
        clock = OpeningExecutionClock(time.monotonic() + 20)
        runtime = SimpleNamespace(timeout_seconds=90, image_id="sha256:" + H)
        with ExitStack() as stack:
            _render, read = mocked_render(stack)
            read.return_value = {}, {"status": "unqualified"}
            with self.assertRaisesRegex(RuntimeError, "unqualified"):
                observer.render_observed_graphic(intent(), Path("/TEST/new.mp4"), (clock, runtime, "TEST-name"))
        self.assertEqual(clock.events[-1]["status"], "failed")

    def test_existing_active_timer_cannot_be_replaced(self) -> None:
        from color.deadline import wall_budget
        clock = OpeningExecutionClock(time.monotonic() + 20)
        runtime = SimpleNamespace(timeout_seconds=90, image_id="sha256:" + H)
        with ExitStack() as stack:
            render, _read = mocked_render(stack)
            with wall_budget(clock.end), self.assertRaisesRegex(RuntimeError, "active wall timer"):
                observer.render_observed_graphic(intent(), Path("/TEST/new.mp4"), (clock, runtime, "TEST-name"))
            render.assert_not_called()

    def test_changed_actual_return_never_borrows_disk_runtime_or_layout(self) -> None:
        mutations = (lambda value: value["layoutObservation"].update(sha256="f" * 64),
                     lambda value: value.update(outputSha256="f" * 64),
                     lambda value: value.update(retainedInputArchive={"TEST": "injected"}),
                     lambda value: value.update(unexpected="TEST"))
        for mutate in mutations:
            clock = OpeningExecutionClock(time.monotonic() + 20)
            runtime = SimpleNamespace(timeout_seconds=90, image_id="sha256:" + H)
            with ExitStack() as stack:
                render, read = mocked_render(stack)
                returned = runtime_return()
                mutate(returned)
                render.return_value = returned
                with self.assertRaisesRegex(RuntimeError, "actual renderer return"):
                    observer.render_observed_graphic(intent(), Path("/TEST/new.mp4"), (clock, runtime, "TEST-name"))
                read.assert_not_called()
            self.assertEqual(clock.events[-1]["status"], "failed")

    def test_actual_return_is_copied_before_later_asset_callbacks(self) -> None:
        clock = OpeningExecutionClock(time.monotonic() + 20)
        runtime = SimpleNamespace(timeout_seconds=90, image_id="sha256:" + H)
        returned = runtime_return()
        with ExitStack() as stack:
            render, read = mocked_render(stack)
            render.return_value = returned
            def late_asset(*_args: object) -> dict:
                returned["layoutObservation"]["sha256"] = "f" * 64
                return {"asset": {"sha256": H}, "runtimeAttestation": {
                    **copy.deepcopy(returned), "retainedInputArchive": {"TEST": "not actual"}}}
            stack.enter_context(patch.object(observer, "_asset", side_effect=late_asset))
            with self.assertRaisesRegex(RuntimeError, "actual renderer return"):
                observer.render_observed_graphic(intent(), Path("/TEST/new.mp4"), (clock, runtime, "TEST-name"))
            read.assert_not_called()
        self.assertEqual(clock.events[-1]["status"], "failed")


class ObservedReaderTests(unittest.TestCase):
    def test_original_request_mutation_after_actual_observation_rejects(self) -> None:
        value = observer.observed_execution_request(request(), intent())
        proof = {"requestPath": "/TEST/request.json", "requestSha256": H,
            "actualAsset": {"path": "/TEST/graphic.mp4", "sha256": H}, "captionLayoutObservation": {}}
        binding = {"graphicId": "TEST-agenda", "graphicRequestHash": H, "graphicMediaSha256": H}
        reader = observation_reader({"TEST-agenda": (proof, value)}, lambda: None)
        with patch.object(observer, "read_graphic_observation", return_value=({}, {})), \
                patch("guided_caption_screen_read.bound_json", side_effect=RuntimeError("held request hash differs")):
            with self.assertRaisesRegex(RuntimeError, "held request"):
                reader(binding, {})
