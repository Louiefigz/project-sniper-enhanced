"""Visual-master publication, component, and ownership contract tests."""
import json
import contextlib
import io
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from palmier.media import MediaBindings
from palmier.mcp_client import PalmierError
from palmier.mirror import (ensure_mirror_bindings, invalidate_for_ai_edit,
                            persist_handoff_to_palmier,
                            persist_reclaim_for_sniper, publish_master,
                            validate_master_binding, validate_mirror_request)
from palmier import ownership


def _request(tmp: str, master: str, digest: str) -> SimpleNamespace:
    return SimpleNamespace(
        out_dir=tmp, plan_hash="plan-hash", master_path=master,
        master_hash=digest, source_hash=digest, master_duration_s=2.0,
        master_fps=24.0, master_width=1920, master_height=1080,
        master_end_frame=48)


def _lanes(master: str, digest: str) -> dict:
    return {
        "project": {"fps": 24, "width": 1920, "height": 1080,
                    "masterHash": digest},
        "imports": {"master": master},
        "mirror": {"entry": {"mediaKey": "master", "startFrame": 0,
                              "endFrame": 48, "source": [0.0, 2.0],
                              "speed": 1.0, "masterHash": digest}},
        "components": {},
    }


class MirrorContractTests(unittest.TestCase):
    def test_validation_binds_steps_to_exact_current_master(self):
        with tempfile.TemporaryDirectory() as tmp:
            master = os.path.join(tmp, "final.mp4")
            with open(master, "wb") as handle:
                handle.write(b"approved-master-with-audio")
            digest = file_sha256(master)
            request, lanes = _request(tmp, master, digest), _lanes(master, digest)
            validate_mirror_request(request, lanes)
            lanes["mirror"]["entry"]["endFrame"] = 47
            with self.assertRaisesRegex(PalmierError, "exactly match"):
                validate_mirror_request(request, lanes)

    def test_import_readback_must_report_the_master_frame_count(self):
        request = SimpleNamespace(master_fps=24.0, master_end_frame=48)
        validate_master_binding(
            request, MediaBindings({"master": "ref"}, {"master": 2.0}, {}))
        with self.assertRaisesRegex(PalmierError, "47 frames"):
            validate_master_binding(
                request, MediaBindings(
                    {"master": "ref"}, {"master": 47 / 24}, {}))

    def test_publication_is_byte_identical_with_hash_and_audio_proof(self):
        with tempfile.TemporaryDirectory() as tmp:
            master = os.path.join(tmp, "final.mp4")
            payload = b"approved-video-and-audio-bytes"
            with open(master, "wb") as handle:
                handle.write(payload)
            request = _request(tmp, master, file_sha256(master))
            publish_master(request, "final.palmier.mp4",
                           "final.palmier.meta.json")
            with open(os.path.join(tmp, "final.palmier.mp4"), "rb") as handle:
                self.assertEqual(handle.read(), payload)
            with open(os.path.join(tmp, "final.palmier.meta.json")) as handle:
                meta = json.load(handle)
        self.assertEqual(meta["publishedHash"], request.master_hash)
        self.assertTrue(meta["visualVerified"])
        self.assertTrue(meta["audioVerified"])


class OwnershipPersistenceTests(unittest.TestCase):
    def test_handoff_and_reclaim_are_atomic_persistent_transitions(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "palmier.sync.json")
            initial = {"ownership": "sniper", "lastPushPlanHash": "p",
                       "laneFp": {"visual": "x"},
                       "verification": {"ok": True}, "projectId": "keep"}
            with open(path, "w") as handle:
                json.dump(initial, handle)
            handed = persist_handoff_to_palmier(tmp)
            self.assertEqual(handed["ownership"], "palmier")
            reclaimed = persist_reclaim_for_sniper(tmp)
            self.assertEqual(reclaimed["ownership"], "sniper")
            self.assertEqual(reclaimed["projectId"], "keep")
            for key in ("lastPushPlanHash", "laneFp", "verification"):
                self.assertNotIn(key, reclaimed)
            with open(path) as handle:
                self.assertEqual(json.load(handle), reclaimed)

    def test_ai_edit_invalidation_preserves_owner_but_revokes_ab_proof(self):
        state = {"schemaVersion": 4, "ownership": "palmier",
                 "projectId": "p", "latestTimelineId": "t",
                 "lastPushPlanHash": "plan", "laneFp": {"visual": "x"},
                 "verification": {"ok": True}, "mirror": {"masterHash": "x"}}
        invalidated = invalidate_for_ai_edit(state)
        self.assertEqual(invalidated["ownership"], "palmier")
        self.assertEqual(invalidated["latestTimelineId"], "t")
        for key in ("lastPushPlanHash", "laneFp", "verification", "mirror"):
            self.assertNotIn(key, invalidated)
        self.assertEqual(state["lastPushPlanHash"], "plan")

    def test_offline_cli_validates_state_and_emits_one_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "palmier.sync.json")
            with open(path, "w") as handle:
                json.dump({"schemaVersion": 4, "ownership": "sniper",
                           "mirrorMode": "visual-master", "projectId": "p",
                           "latestTimelineId": "t", "lastPushPlanHash": "h",
                           "laneFp": {}, "verification": {"ok": True}}, handle)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = ownership.main([tmp, "--handoff"])
            self.assertEqual(code, 0)
            self.assertEqual(len(output.getvalue().splitlines()), 1)
            self.assertEqual(json.loads(output.getvalue())["ownership"], "palmier")
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = ownership.main([tmp, "--reclaim"])
            self.assertEqual(code, 0)
            verdict = json.loads(output.getvalue())
            self.assertTrue(verdict["freshMirrorRequired"])

    def test_offline_cli_returns_retryable_waiting_when_sync_lock_is_busy(self):
        output = io.StringIO()
        with patch("palmier.ownership._acquire", side_effect=BlockingIOError), \
                contextlib.redirect_stdout(output):
            code = ownership.main(["/tmp", "--handoff"])
        self.assertEqual(code, 75)
        self.assertEqual(json.loads(output.getvalue())["status"], "waiting")

    def test_offline_cli_invalidates_ab_without_changing_owner(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "palmier.sync.json")
            with open(path, "w") as handle:
                json.dump({"schemaVersion": 4, "ownership": "palmier",
                           "mirrorMode": "visual-master", "projectId": "p",
                           "latestTimelineId": "t", "lastPushPlanHash": "h",
                           "laneFp": {}, "verification": {"ok": True}}, handle)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = ownership.main([tmp, "--invalidate"])
            self.assertEqual(code, 0)
            verdict = json.loads(output.getvalue())
            self.assertEqual(verdict["action"], "invalidate")
            self.assertEqual(verdict["ownership"], "palmier")
            with open(path) as handle:
                state = json.load(handle)
            self.assertNotIn("lastPushPlanHash", state)
            self.assertNotIn("verification", state)

    def test_offline_cli_can_revoke_a_legacy_sidecar(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "palmier.sync.json")
            with open(path, "w") as handle:
                json.dump({"schemaVersion": 3, "lastPushPlanHash": "old",
                           "verification": {"ok": True}}, handle)
            with contextlib.redirect_stdout(io.StringIO()):
                code = ownership.main([tmp, "--invalidate"])
            self.assertEqual(code, 0)
            with open(path) as handle:
                self.assertEqual(json.load(handle), {
                    "schemaVersion": 3, "ownership": "sniper"})


class ComponentPreservationTests(unittest.TestCase):
    def test_components_are_individual_best_effort_and_never_visible(self):
        class Library:
            def __init__(self, *_args):
                pass

            def ensure(self, imports, prior):
                key = next(iter(imports))
                if key == "bad:text":
                    raise PalmierError("file type unsupported")
                media_map = {**prior, key: {"ref": f"ref-{key}", "seconds": 1}}
                return MediaBindings({key: f"ref-{key}"}, {key: 1}, media_map)

        session = SimpleNamespace(
            request=SimpleNamespace(master_hash="hash", source_hash="hash"),
            client=object(), assert_project=lambda _phase: None)
        lanes = {"imports": {"master": "/final.mp4"},
                 "components": {"source:a": "/raw.mp4",
                                "bad:text": "/captions.srt"}}
        with patch("palmier.mirror.MediaLibrary", Library):
            bindings = ensure_mirror_bindings(session, lanes, None)
        self.assertIn("source:a", bindings.refs)
        self.assertNotIn("bad:text", bindings.refs)
        self.assertTrue(bindings.component_status["source:a"]["preserved"])
        rejected = bindings.component_status["bad:text"]
        self.assertFalse(rejected["preserved"])
        self.assertFalse(rejected["visible"])
        self.assertFalse(rejected["editableOnTimeline"])


if __name__ == "__main__":
    unittest.main()
