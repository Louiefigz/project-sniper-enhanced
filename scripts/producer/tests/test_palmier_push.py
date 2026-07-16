"""Push CLI asset resolution and universal NDJSON error envelope."""
import contextlib
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from _common import *  # noqa: F401,F403
from fingerprints import file_sha256
from fingerprints import plan_content_hash
from palmier import push


class MusicResolutionTests(unittest.TestCase):
    def test_manifest_asset_id_becomes_absolute_execution_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            track = os.path.join(tmp, "bed.mp3")
            with open(track, "wb"):
                pass
            manifest = os.path.join(tmp, "asset_manifest.json")
            with open(manifest, "w") as handle:
                json.dump({"music": [{"id": "music-1", "path": track}]}, handle)
            plan = {"music": {"enabled": True, "assetId": "music-1"}}
            resolved = push.resolve_plan_assets(plan, manifest)
        self.assertEqual(resolved["music"]["path"], track)
        self.assertNotIn("path", plan["music"])

    def test_missing_asset_names_the_identifier(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest = os.path.join(tmp, "asset_manifest.json")
            with open(manifest, "w") as handle:
                json.dump({"music": []}, handle)
            with self.assertRaisesRegex(RuntimeError, "missing-bed"):
                push.resolve_plan_assets(
                    {"music": {"enabled": True, "assetId": "missing-bed"}},
                    manifest)


class ErrorEnvelopeTests(unittest.TestCase):
    def test_missing_inputs_emit_exactly_one_error_frame(self):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = push.main(["/no/edit-plan.json", "/no/manifest.json"])
        frames = [json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(code, 1)
        self.assertEqual(len([frame for frame in frames if "error" in frame]), 1)
        self.assertNotIn("Traceback", output.getvalue())

    def test_preflight_asset_failure_is_a_blocked_verdict_not_traceback(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan = os.path.join(tmp, "edit_plan.json")
            manifest = os.path.join(tmp, "asset_manifest.json")
            with open(plan, "w") as handle:
                json.dump({"music": {"enabled": True, "assetId": "ghost"}}, handle)
            with open(manifest, "w") as handle:
                json.dump({"sources": [{"id": "s", "path": "/src.mp4",
                                         "fps": 24, "resolution": [1920, 1080]}],
                           "music": []}, handle)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                code = push.main([plan, manifest, "--preflight"])
        verdict = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertFalse(verdict["ok"])
        self.assertIn("ghost", verdict["blocked"])

    def test_preflight_uses_unsaved_stdin_plan_without_writing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            plan_path = os.path.join(tmp, "edit_plan.json")
            manifest = os.path.join(tmp, "asset_manifest.json")
            saved = {"cutTrack": [{"sourceId": "s", "start": 0, "end": 2}]}
            memory = {**saved, "graphicsTrack": [
                {"kind": "card", "outStart": 0, "outEnd": 1}]}
            with open(plan_path, "w") as handle:
                json.dump(saved, handle)
            with open(manifest, "w") as handle:
                json.dump({"sources": [{"id": "s", "path": "/src.mp4",
                                         "fps": 24, "resolution": [1920, 1080]}]},
                          handle)
            output = io.StringIO()
            with patch("sys.stdin", io.StringIO(json.dumps(memory))), \
                    contextlib.redirect_stdout(output):
                code = push.main([
                    plan_path, manifest, "--preflight", "--plan-stdin"])
            with open(plan_path) as handle:
                self.assertEqual(json.load(handle), saved)
        verdict = json.loads(output.getvalue())
        self.assertEqual(code, 0)
        self.assertEqual(verdict["planHash"], plan_content_hash(memory))
        self.assertFalse(verdict["parity"]["fullyEditable"])


class RequiredGraphicsTests(unittest.TestCase):
    """A GUI-selected graphic is a deliverable, never a best-effort lane."""

    PLAN = {"graphicsTrack": [{"kind": "statement-card",
                                "outStart": 0, "outEnd": 1,
                                "spec": {"variant": "classic",
                                         "text": "Required copy"}}]}

    def test_render_failure_blocks_push_instead_of_omitting(self):
        with patch("palmier.push.render_entry",
                   side_effect=RuntimeError("render failed")):
            with self.assertRaisesRegex(
                    push.PalmierError,
                    r"required component graphicsTrack\[0\].*rendered and proved"):
                push.render_graphics(self.PLAN, None)

    def test_missing_asset_proof_blocks_push_instead_of_omitting(self):
        rendered = {"path": "/graphic.mp4", "cached": False,
                    "kind": "statement-card"}
        with patch("palmier.push.render_entry", return_value=rendered):
            with self.assertRaisesRegex(push.PalmierError,
                                        "no rendered asset proof"):
                push.render_graphics(self.PLAN, None)


class AuthorityProvenanceTests(unittest.TestCase):
    def _paths(self, tmp: str, plan_hash: str) -> tuple[str, str]:
        final = os.path.join(tmp, "final.mp4")
        with open(final, "wb") as handle:
            handle.write(b"verified-authority")
        proof = final + ".assembled.json"
        with open(proof, "w") as handle:
            json.dump({"planHash": plan_hash,
                       "authorityHash": file_sha256(final)}, handle)
        return final, proof

    def test_accepts_current_plan_and_exact_final_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            final, _proof = self._paths(tmp, "plan-hash")
            self.assertEqual(push._authority_hash(tmp, "plan-hash"),
                             file_sha256(final))

    def test_rejects_stale_plan_or_changed_final(self):
        with tempfile.TemporaryDirectory() as tmp:
            final, proof = self._paths(tmp, "old-plan")
            with self.assertRaisesRegex(Exception, "stale or unproven"):
                push._authority_hash(tmp, "new-plan")
            with open(proof) as handle:
                record = json.load(handle)
            record["planHash"] = "new-plan"
            with open(proof, "w") as handle:
                json.dump(record, handle)
            with open(final, "ab") as handle:
                handle.write(b"changed")
            with self.assertRaisesRegex(Exception, "changed after"):
                push._authority_hash(tmp, "new-plan")


if __name__ == "__main__":
    unittest.main()
