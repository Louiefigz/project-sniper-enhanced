"""Actual TEST byte files through production observation/readback adapters.

Only daemon/archive authenticity is explicitly stubbed; these are protocol
faults, not live Chrome or readable-pixel qualification.
"""
from __future__ import annotations

import copy
import hashlib
import tempfile
import time
import unittest
from contextlib import ExitStack
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from cut_preview_io import digest
import guided_caption_graphic_observation as observer
from guided_caption_graphic_observation import GRAPHIC_POLICY, observed_execution_request, read_graphic_observation
from guided_caption_screen import CaptionScreenContext
from guided_caption_screen_read import graphic_projection, observation_reader
from guided_caption_profile import SCREENED_CAPTION_PROFILE
from guided_opening_execution import OpeningExecutionClock
from headless.render_layout_contract import canonical, encoded_request
from test_guided_caption_graphic_observation import H, intent, request
from test_render_layout_contract import fixture, documents


def raw_sha(path: Path) -> str:
    """Hash only tiny TEST files, not user source media."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


class ObservedScreenBindingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory(prefix="TEST-owned-screen-bytes-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.path = self.root / "graphic.mp4"
        self.path.write_bytes(b"TEST opaque, not actual decoded video")
        self.media = {"path": str(self.path), "sha256": raw_sha(self.path)}
        local, expected, value = fixture()
        held_intent = intent()
        self.row = {**held_intent.row, "order": 2, "endFrameExclusive": 684}
        held_intent = replace(held_intent, row=self.row)
        self.request = observed_execution_request(request(), held_intent)
        self.request["intent"]["endFrameExclusive"] = 684
        self.request["intent"]["fullAnimationFrames"] = 2
        self.request_path = self.root / "request.json"
        self.request_path.write_bytes(canonical(self.request))
        value["media"] = {"sha256": self.media["sha256"], "sizeBytes": self.path.stat().st_size}
        self.layout = Path(str(self.path) + ".layout.json")
        self.layout.write_bytes(canonical(value))
        runtime = {"snapshotSha256": H, "snapshotManifest": [], "layoutObservation": {"sha256": raw_sha(self.layout)}}
        for field in ("containerBeforeOutput", "containerAfterOutput"):
            runtime[field] = {"Config": {"Env": ["SNIPER_LAYOUT_REQUEST=" + encoded_request(local)]}}
        sidecar = Path(str(self.path) + ".proof.json")
        sidecar.write_bytes(canonical({"runtimeAttestation": runtime}))
        self.sources = expected["observerSources"]
        self.proof = {"candidateOrder": 2, "graphicId": self.row["graphicId"], "actualAsset": self.media,
            "requestPath": str(self.request_path), "requestSha256": raw_sha(self.request_path),
            "proofSidecar": {"path": str(sidecar), "sha256": raw_sha(sidecar)},
            "captionLayoutObservation": {"schemaVersion": 1, "policy": GRAPHIC_POLICY, "request": local,
                "observation": {"path": str(self.layout), "sha256": raw_sha(self.layout)}, "observerSources": self.sources}}
        self.addCleanup(patch.stopall)
        patch("guided_caption_graphic_observation.required_runtime", return_value=SimpleNamespace(image_id=self.request["imageId"])).start()
        patch("guided_caption_graphic_observation.approved_sources", return_value=self.sources).start()
        patch("headless.render_layout_read.validate_runtime_attestation").start()
        patch("headless.render_layout_read.sealed_documents", return_value=documents()).start()

    def test_adapter_reads_actual_raw_bytes_and_projects_local_frames_into_global_span(self) -> None:
        ref, value = read_graphic_observation(self.proof, self.request, lambda: None)
        self.assertEqual(ref["sha256"], raw_sha(self.layout))
        self.assertEqual(value["framesObserved"], 2)
        binding = {"graphicId": self.row["graphicId"], "graphicRequestHash": self.proof["requestSha256"],
            "graphicMediaSha256": self.media["sha256"], "frameRate": "30000/1001", "width": 1920, "height": 1080}
        returned = observation_reader({self.row["graphicId"]: (self.proof, self.request)}, lambda: None)(binding, {})
        self.assertEqual((returned[1]["startFrame"], returned[1]["endFrameExclusive"]), (682, 684))
        self.assertEqual(returned[1]["framesObserved"], 2)
        self.assertEqual(returned[1]["declarationHash"], digest({}))

    def test_replacing_layout_or_media_or_proof_bytes_rejects(self) -> None:
        for path in (self.path, self.layout, Path(self.proof["proofSidecar"]["path"])):
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.assertRaises(ValueError):
                read_graphic_observation(self.proof, self.request, lambda: None)
            path.write_bytes(original)

    def test_source_image_and_held_metadata_transplants_reject(self) -> None:
        for field, replacement in (("request", {**self.proof["captionLayoutObservation"]["request"], "totalFrames": 3}),
                                    ("observerSources", []), ("policy", "self-sealed-safe")):
            proof = copy.deepcopy(self.proof)
            proof["captionLayoutObservation"][field] = replacement
            with self.assertRaises((RuntimeError, ValueError)):
                read_graphic_observation(proof, self.request, lambda: None)
        with patch("guided_caption_graphic_observation.required_runtime", return_value=SimpleNamespace(image_id="sha256:" + "f" * 64)):
            with self.assertRaises(RuntimeError):
                read_graphic_observation(self.proof, self.request, lambda: None)

    def test_live_actual_return_not_new_disk_hash_controls_real_cold_reader(self) -> None:
        sidecar = Path(self.proof["proofSidecar"]["path"])
        import json
        runtime = json.loads(sidecar.read_bytes())["runtimeAttestation"]
        runtime["outputSha256"] = self.media["sha256"]
        proof = {"asset": self.media, "runtimeAttestation": {
            **copy.deepcopy(runtime), "retainedInputArchive": {"TEST": "not archive proof"}}}
        actual_intent = replace(intent(), row=self.row)
        for mismatch in (False, True):
            clock = OpeningExecutionClock(time.monotonic() + 20)
            actual = copy.deepcopy(runtime)
            if mismatch:
                actual["layoutObservation"]["sha256"] = "f" * 64
            with ExitStack() as stack:
                stack.enter_context(patch.object(observer, "render_to", return_value=actual))
                stack.enter_context(patch.object(observer, "sealed_documents", return_value=documents()))
                stack.enter_context(patch.object(observer, "_asset", return_value=proof))
                control = SimpleNamespace(timeout_seconds=90, image_id=self.request["imageId"])
                if mismatch:
                    with self.assertRaisesRegex(RuntimeError, "actual renderer return"):
                        observer.render_observed_graphic(actual_intent, self.path, (clock, control, "TEST"))
                else:
                    _, metadata = observer.render_observed_graphic(actual_intent, self.path, (clock, control, "TEST"))
                    self.assertEqual(metadata["observation"]["sha256"], raw_sha(self.layout))
            self.assertEqual(clock.events[-1]["status"], "failed" if mismatch else "complete")

    def test_opening_cannot_accept_body_request_or_other_original_input(self) -> None:
        clock = {"frameRate": "30000/1001", "width": 1920, "height": 1080, "totalFrames": 9325}
        inputs = SimpleNamespace(value={"profile": SCREENED_CAPTION_PROFILE, "executionInputHash": H})
        context = CaptionScreenContext(inputs, None, (self.row,), {"startFrame": 0, "endFrameExclusive": 750})
        for changed in ({**self.request, "executionInputHash": "f" * 64},
                        observed_execution_request(request("body"), replace(intent(), row=self.row))):
            self.request_path.write_bytes(canonical(changed))
            proof = {**self.proof, "requestSha256": raw_sha(self.request_path)}
            with patch("guided_caption_screen_read._sources", side_effect=AssertionError("must refuse before template IO")):
                with self.assertRaises(RuntimeError):
                    graphic_projection((context, clock), self.row, proof, lambda: None)
