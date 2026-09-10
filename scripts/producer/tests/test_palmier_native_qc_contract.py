"""Candidate-specific input, export-audio, and review-frame QC contracts."""
import copy
import json
import os
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from audit.audit_checks import CheckResult, FAIL, PASS, WARN
from audit.audit_frames import FrameRef
from audit.audit_glitch import detect_freeze
from fingerprints import file_sha256
from palmier.mcp_client import PalmierError
from palmier.native_qc_audit import (_declared_windows, _export_checks,
                                     _review_frames, run_native_audit)
from palmier.native_qc_contract import (
    authority_from_value, export_path, stable_hash, validate_export,
)
from palmier.native_qc_export import export_candidate
from palmier.timeline_authority import record_authority, snapshot
from test_palmier_native_delta import NativeClient, _record, _timeline


def _artifact(tmp: str, request: str = "Move this card cleanly") -> tuple[dict, dict]:
    client = NativeClient()
    parent = _record(tmp, client)
    request_hash = __import__("hashlib").sha256(request.encode("utf-8")).hexdigest()
    plan = {
        "schemaVersion": 1,
        "parent": {key: parent[key] for key in
                   ("projectId", "timelineId", "fingerprint")},
        "requestHash": request_hash, "lanes": ["graphics", "motion"],
        "operations": [{"tool": "set_clip_properties",
                        "args": {"clipIds": ["clip-1"], "opacity": 0.5},
                        "reason": "Keep the card subordinate"}],
    }
    value = {"schemaVersion": 1, "kind": "palmier-native-candidate-input",
             "request": {"text": request, "hash": request_hash},
             "controller": {"lanes": ["graphics", "motion"]},
             "parent": parent, "nativePlan": plan}
    path = os.path.join(tmp, ".native-input.json")
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(value, handle)
    capture = "native-capture"
    envelope = {
        "schemaVersion": 1, "requestHash": request_hash, "captureId": capture,
        "nativeInput": {"path": path, "hash": file_sha256(path),
                        "requestTextHash": request_hash,
                        "lanes": ["graphics", "motion"],
                        "parent": plan["parent"],
                        "nativePlanHash": stable_hash(plan)},
        "ctx": {"dir": tmp, "scope": "produced", "planPath": path,
                "manifestPath": os.path.join(tmp, "manifest.json"),
                "transcriptsDir": tmp,
                "doctrine": {"runId": capture, "doctrineHash": "d" * 64},
                "pipeline": {"runId": capture}},
    }
    candidate = {"projectId": "project-1", "timelineId": "candidate",
                 "fingerprint": "c" * 64, "requestHash": request_hash,
                 "lanes": ["graphics", "motion"],
                 "nativePlanHash": stable_hash(plan)}
    return envelope, candidate


def _snapshot_summary(plan_hash: str = "p" * 64) -> dict:
    return {"scope": "produced", "planHash": plan_hash,
            "manifestHash": "m" * 64, "operatorIntentDigest": "o" * 64,
            "transcriptDigest": "t" * 64, "referenceDigest": "r" * 64,
            "pipelineDigest": "i" * 64}


class NativeInputAuthorityTests(unittest.TestCase):
    def test_exact_request_lanes_and_full_plan_are_digest_authority(self):
        with tempfile.TemporaryDirectory() as tmp:
            envelope, candidate = _artifact(tmp)
            parent = envelope["nativeInput"]["parent"]
            with patch("palmier.native_qc_contract.authority_snapshot",
                       return_value=_snapshot_summary()), \
                    patch("palmier.native_qc_contract.request_key",
                          return_value="k" * 64):
                found = authority_from_value(
                    envelope, tmp, {"candidate": candidate, "parent": parent})
            self.assertEqual(found["request"]["text"], "Move this card cleanly")
            self.assertEqual(found["lanes"], ["graphics", "motion"])
            with open(envelope["nativeInput"]["path"], encoding="utf-8") as handle:
                expected_plan = json.load(handle)["nativePlan"]
            self.assertEqual(found["nativePlan"], expected_plan)
            self.assertEqual(found["summary"]["requestTextHash"],
                             envelope["requestHash"])

    def test_stale_sniper_plan_hash_is_excluded_but_native_bytes_are_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            envelope, candidate = _artifact(tmp)
            parent = envelope["nativeInput"]["parent"]
            values = []
            for digest in ("a" * 64, "b" * 64):
                with patch("palmier.native_qc_contract.authority_snapshot",
                           return_value=_snapshot_summary(digest)), \
                        patch("palmier.native_qc_contract.request_key",
                              return_value="k" * 64):
                    values.append(authority_from_value(
                        envelope, tmp, {"candidate": candidate, "parent": parent}))
            self.assertEqual(values[0]["inputDigest"], values[1]["inputDigest"])
            artifact = envelope["nativeInput"]["path"]
            with open(artifact, "a", encoding="utf-8") as handle:
                handle.write(" ")
            with self.assertRaisesRegex(PalmierError, "artifact changed"):
                authority_from_value(envelope, tmp,
                                     {"candidate": candidate, "parent": parent})

    def test_executed_candidate_plan_hash_must_match_archived_native_plan(self):
        with tempfile.TemporaryDirectory() as tmp:
            envelope, candidate = _artifact(tmp)
            candidate["nativePlanHash"] = "0" * 64
            with patch("palmier.native_qc_contract.authority_snapshot",
                       return_value=_snapshot_summary()), \
                    patch("palmier.native_qc_contract.request_key",
                          return_value="k" * 64):
                with self.assertRaisesRegex(PalmierError, "not bound"):
                    authority_from_value(envelope, tmp, {
                        "candidate": candidate,
                        "parent": envelope["nativeInput"]["parent"]})


class CandidateExportTests(unittest.TestCase):
    def test_audio_stream_failure_never_overwrites_last_candidate_export(self):
        class Client:
            def call(self, _tool, args):
                self.args = args
                with open(args["outputPath"], "wb") as handle:
                    handle.write(b"new-native-candidate")
                return {"ok": True}
        with tempfile.TemporaryDirectory() as tmp:
            final = os.path.join(tmp, "palmier.candidate.mp4")
            with open(final, "wb") as handle:
                handle.write(b"previous-approved-bytes")
            found = snapshot("project-1", _timeline())
            client = Client()
            probe = SimpleNamespace(duration_s=5.0, frame_error=0.0)
            with patch("palmier.native_qc_export.wait_for_export"), \
                    patch("palmier.native_qc_export.verify_export",
                          return_value=probe), \
                    patch("palmier.native_qc_export.ffprobe_json",
                          return_value={"streams": [{"codec_type": "video"}]}):
                with self.assertRaisesRegex(PalmierError,
                                            "encoded audio stream"):
                    export_candidate(client, tmp, found)
            with open(final, "rb") as handle:
                self.assertEqual(handle.read(), b"previous-approved-bytes")
            self.assertEqual(client.args["timelineId"], "head")

    def test_multiple_audio_streams_fail_before_decode_or_publish(self):
        class Client:
            def call(self, _tool, args):
                with open(args["outputPath"], "wb") as handle:
                    handle.write(b"candidate")
                return {"ok": True}
        with tempfile.TemporaryDirectory() as tmp:
            found = snapshot("project-1", _timeline())
            probe = SimpleNamespace(duration_s=5.0, frame_error=0.0)
            streams = [{"codec_type": "video"}, {"codec_type": "audio"},
                       {"codec_type": "audio"}]
            with patch("palmier.native_qc_export.wait_for_export"), \
                    patch("palmier.native_qc_export.verify_export",
                          return_value=probe), \
                    patch("palmier.native_qc_export.ffprobe_json",
                          return_value={"streams": streams}), \
                    patch("palmier.native_qc_export._full_decode") as decode:
                with self.assertRaisesRegex(PalmierError, "encoded audio stream"):
                    export_candidate(Client(), tmp, found)
            decode.assert_not_called()
            self.assertFalse(os.path.exists(export_path(tmp)))

    def test_durable_export_requires_exact_decode_and_one_audio_stream(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = export_path(tmp)
            with open(media, "wb") as handle:
                handle.write(b"candidate")
            exact = {"path": media, "hash": file_sha256(media),
                     "audioPresent": True, "audioStreamCount": 1,
                     "videoStreamCount": 1,
                     "fullDecode": "ffmpeg-xerror-av-v1"}
            receipt = {"outDir": tmp, "export": exact}
            self.assertEqual(validate_export(receipt), exact)
            for key in ("audioStreamCount", "videoStreamCount", "fullDecode"):
                broken = {name: value for name, value in exact.items()
                          if name != key}
                with self.assertRaisesRegex(PalmierError, "exact one-audio"):
                    validate_export({"outDir": tmp, "export": broken})


class NativeReviewFrameTests(unittest.TestCase):
    def test_plan_declared_ownscreen_windows_are_forwarded_to_glitch_gate(self):
        receipt = {"authority": {"editPlan": {"graphicsTrack": [
            {"outStart": 2, "outEnd": 4, "allowDarkEntry": True},
            {"outStart": 5, "outEnd": 8, "allowStaticHold": True},
        ]}}}
        self.assertEqual(_declared_windows(receipt, "allowDarkEntry"),
                         [(2.0, 4.0)])
        self.assertEqual(_declared_windows(receipt, "allowStaticHold"),
                         [(5.0, 8.0)])

    def test_declared_freeze_is_a_pass_but_unplanned_freeze_warns(self):
        output = ("[freezedetect @ 0xTEST] lavfi.freezedetect.freeze_start: 34\n"
                  "[freezedetect @ 0xTEST] lavfi.freezedetect.freeze_duration: 2.125\n"
                  "[freezedetect @ 0xTEST] lavfi.freezedetect.freeze_end: 36.125\n")
        # Parser/verdict-only fixture; strict whole-decode evidence has its own tests.
        with patch("audit.audit_glitch.scan_glitch_filter", return_value=SimpleNamespace(stderr=output, ansi_stripped=False)):
            planned = detect_freeze("candidate.mp4", [(32.8, 36.8)])
            unplanned = detect_freeze("candidate.mp4")
        self.assertEqual(planned.status, PASS)
        self.assertEqual(unplanned.status, WARN)

    def test_clip_relative_keyframes_use_fresh_nonzero_clip_start(self):
        parent = _timeline()
        parent["tracks"][0]["clips"][0]["frames"] = [48, 120]
        current = copy.deepcopy(parent)
        current["id"] = "candidate"
        current["tracks"][0]["clips"][0]["id"] = "clip-copy"
        found = snapshot("project-1", current)
        receipt = {"authority": {"nativeParent": {"timeline": parent},
                    "nativePlan": {"operations": [{
                        "tool": "set_keyframes", "args": {
                            "clipId": "clip-1", "property": "scale",
                            "keyframes": [[0, 1.0], [24, 1.1]]}}]}}}
        refs = [row for row in _review_frames(receipt, found, 5.0)
                if row.kind == "native-keyframe"]
        self.assertEqual([row.timestamp for row in refs], [2.0, 3.0])

    def test_audit_b_calls_loudness_glitch_and_motion_integrity_gates(self):
        with tempfile.TemporaryDirectory() as tmp:
            media = os.path.join(tmp, "palmier.candidate.mp4")
            frame = os.path.join(tmp, "frame.jpg")
            for path, content in ((media, b"media"), (frame, b"frame")):
                with open(path, "wb") as handle:
                    handle.write(content)
            found = snapshot("project-1", _timeline())
            receipt = {"outDir": tmp, "authority": {"nativePlan": {
                           "operations": []}},
                       "export": {"path": media, "hash": file_sha256(media),
                                  "audioPresent": True,
                                  "audioStreamCount": 1,
                                  "videoStreamCount": 1,
                                  "fullDecode": "ffmpeg-xerror-av-v1",
                                  "durationSeconds": 5.0,
                                  "frameError": 0.0}}
            probe = {"streams": [
                {"codec_type": "video", "width": 1920, "height": 1080,
                 "r_frame_rate": "24/1"}, {"codec_type": "audio"}]}
            refs = [FrameRef("cover", "cover", 0.2, frame, "inspect")]
            loudness = [CheckResult("loudness_integrated", FAIL, "-40 LUFS", "")]
            glitch = [CheckResult("glitch_freeze", WARN, "frozen", "")]
            motion = [CheckResult("motion_smoothness", PASS, "smooth", "")]
            with patch("palmier.native_qc_audit.ffprobe_json", return_value=probe), \
                    patch("palmier.native_qc_audit.check_loudness",
                          return_value=loudness) as loudness_gate, \
                    patch("palmier.native_qc_audit.check_audio_quality",
                          return_value=[]), \
                    patch("palmier.native_qc_audit.check_glitch_screens",
                          return_value=glitch) as glitch_gate, \
                    patch("palmier.native_qc_audit.check_smoothness",
                          return_value=motion) as motion_gate, \
                    patch("palmier.native_qc_audit.extract_review_frames",
                          return_value=refs), \
                    patch("palmier.native_qc_audit.check_frame_extraction",
                          return_value=CheckResult("frames", PASS, "1/1", "")):
                checks, _frames = _export_checks(receipt, found)
            freeze = next(row for row in checks if row["name"] == "glitch_freeze")
            self.assertEqual(freeze["status"], FAIL)
            loudness_gate.assert_called_once()
            glitch_gate.assert_called_once()
            motion_gate.assert_called_once()

    def test_any_render_integrity_failure_persists_failed_audit_and_rejects(self):
        with tempfile.TemporaryDirectory() as tmp:
            found = snapshot("project-1", _timeline())
            receipt = {"outDir": tmp, "export": {
                           "hash": "e" * 64, "path": "candidate.mp4"},
                       "authority": {"inputDigest": "i" * 64}}
            failure = {"name": "glitch_black", "status": FAIL,
                       "measured": "black run", "detail": ""}
            parity_path = os.path.join(tmp, "palmier.editable-parity.json")
            with open(parity_path, "w", encoding="utf-8") as handle:
                handle.write("{}\n")
            parity = {"verdict": "pass", "blockedMetricIds": [],
                      "digest": "p" * 64}
            with patch("palmier.native_qc_audit._export_checks",
                       return_value=([failure], [])), \
                    patch("palmier.native_qc_audit.run_parity",
                          return_value=parity):
                with self.assertRaisesRegex(PalmierError, "failed deterministic"):
                    run_native_audit(tmp, receipt, found)
            with open(os.path.join(tmp, "palmier.native-audit.json"),
                      encoding="utf-8") as handle:
                self.assertEqual(json.load(handle)["status"], FAIL)


if __name__ == "__main__":
    unittest.main()
