"""Synthetic artifact/protocol negatives; not authenticated media success proof."""
from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cut_preview_io import digest, file_hash, write_new
from guided_opening_media import main as media_main
from guided_opening_graphic_proof import OpeningGraphicIntent, verify_graphic_result
from guided_opening_read import ReadAuthority, _record, _unchanged, read_result
from guided_opening_result import check_held_artifacts, held_ref
from graphics.render_rate import normalize_render_rate
from headless.container_io import SealedInput


class OpeningResultContractTests(unittest.TestCase):
    """Exercise exact held bytes and failure semantics without pretending to render."""

    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sniper-opening-result-", dir="/private/tmp")
        self.root = Path(self.temporary.name)
        self.addCleanup(self.temporary.cleanup)
        self.body = {"kind": "TEST-only-incomplete-not-media-proof", "openingApproved": False}
        self.record = {**self.body, "receiptHash": digest(self.body)}
        write_new(self.root / "media-result.json", self.record)
        self.held = ReadAuthority("1" * 64, self.root / "missing-claim.json", "2" * 64,
                                  file_hash(self.root / "media-result.json"), self.record["receiptHash"])

    def test_exact_record_bytes_need_separately_held_hash(self) -> None:
        self.assertEqual(_record(self.root, self.held), self.record)
        wrong = ReadAuthority("1" * 64, self.held.claim_path, "2" * 64, "3" * 64, self.held.receipt_hash)
        with self.assertRaises(RuntimeError):
            _record(self.root, wrong)

    def test_self_resealed_orphan_cannot_replace_the_actual_completion(self) -> None:
        changed = {**self.body, "openingApproved": True}
        (self.root / "media-result.json").write_text(json.dumps({**changed, "receiptHash": digest(changed)}))
        with self.assertRaises(RuntimeError):
            _record(self.root, self.held)

    def test_failure_marker_overrides_a_matching_result(self) -> None:
        write_new(self.root / "media-failed.json", {"TEST": "failure after publication"})
        with self.assertRaisesRegex(RuntimeError, "attempt failed"):
            _record(self.root, self.held)

    def test_dangling_failure_marker_also_blocks_readback(self) -> None:
        (self.root / "media-failed.json").symlink_to(self.root / "missing.json")
        with self.assertRaisesRegex(RuntimeError, "attempt failed"):
            _record(self.root, self.held)

    def test_orphan_result_never_reaches_source_or_media_readers(self) -> None:
        with patch("guided_opening_read.read_current_inputs") as inputs, \
                patch("guided_opening_read.read_ranges") as media:
            with self.assertRaises((OSError, RuntimeError)):
                read_result((self.root / "missing-input.json", self.root), self.held, 10)
        inputs.assert_not_called()
        media.assert_not_called()

    def test_shared_or_linked_output_directory_is_not_a_private_result(self) -> None:
        os.chmod(self.root, 0o755)
        try:
            with self.assertRaisesRegex(RuntimeError, "private owned"):
                _record(self.root, self.held)
        finally:
            os.chmod(self.root, 0o700)

    def test_ref_cannot_escape_through_path_syntax_or_symlink(self) -> None:
        path = self.root / "artifact.mp4"
        path.write_bytes(b"TEST artifact, not encoded video")
        reference = {"path": str(path), "sha256": file_hash(path)}
        self.assertEqual(held_ref(reference, self.root), path)
        alias = self.root / "alias.mp4"
        alias.symlink_to(path)
        for value in (str(alias), str(self.root) + "/./artifact.mp4", str(self.root) + "//artifact.mp4"):
            with self.subTest(path=value), self.assertRaises(RuntimeError):
                held_ref({**reference, "path": value}, self.root)

    def test_ref_fifo_rejects_without_blocking(self) -> None:
        path = self.root / "fifo"
        os.mkfifo(path)
        with self.assertRaisesRegex(RuntimeError, "unsafe|budget"):
            held_ref({"path": str(path), "sha256": "0" * 64}, self.root)

    def test_final_artifact_set_rechecks_audio_and_picture_not_only_mp4(self) -> None:
        path = self.root / "artifact"
        path.write_bytes(b"TEST held bytes")
        ref = {"path": str(path), "sha256": file_hash(path)}
        record = {"audio": ref, "fullProgram": {"base": ref, "receipts": {"TEST": ref}},
            "pictures": {"ranges": {"core": ref, "review": ref}}, "media": {"core": ref, "review": ref}, "graphics": []}
        audio = {"core": ref, "review": ref}
        check_held_artifacts(record, audio, self.root)
        path.write_bytes(b"TEST changed after first media observation")
        with self.assertRaisesRegex(RuntimeError, "bytes changed"):
            check_held_artifacts(record, audio, self.root)

    def test_mutation_during_slow_dependency_check_is_rejected_at_the_end(self) -> None:
        def mutate(_inputs: object) -> None:
            (self.root / "media-result.json").write_bytes(b"TEST changed while checking sources")

        with patch("guided_opening_read.observe_inputs", side_effect=mutate), \
                patch("guided_opening_read.observe_pipeline", return_value={}), \
                patch("guided_opening_read.revalidate_master_selection"), \
                patch("guided_opening_read.check_held_artifacts"):
            with self.assertRaises((RuntimeError, ValueError)):
                _unchanged((self.root, self.held, None, {}, self.record), (None, {}))

    def test_failure_arriving_during_final_check_overrides_prior_success(self) -> None:
        def fail(_inputs: object) -> None:
            write_new(self.root / "media-failed.json", {"TEST": "post-publication failure"})

        with patch("guided_opening_read.observe_inputs", side_effect=fail), \
                patch("guided_opening_read.observe_pipeline", return_value={}), \
                patch("guided_opening_read.revalidate_master_selection"), \
                patch("guided_opening_read.check_held_artifacts"):
            with self.assertRaisesRegex(RuntimeError, "attempt failed during"):
                _unchanged((self.root, self.held, None, {}, self.record), (None, {}))


class OpeningStdoutProtocolTests(unittest.TestCase):
    """Protocol-only stand-ins cannot qualify media or replace actual worker tests."""

    def test_reused_progress_is_stderr_and_stdout_is_one_completion(self) -> None:
        def progress(*_args: object) -> dict:
            print('{"event":"TEST-only ordinary render progress"}')
            return {"kind": "TEST-only-protocol-not-success-proof"}

        args = ["guided_opening_media.py", "/TEST/input", "/TEST/output", "--input-sha256", "1" * 64,
            "--execution-claim", "/TEST/claim", "--execution-claim-sha256", "2" * 64, "--timeout-seconds", "10"]
        output, error = io.StringIO(), io.StringIO()
        with patch("sys.argv", args), patch("guided_opening_media.run", side_effect=progress):
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(error):
                self.assertEqual(media_main(), 0)
        self.assertEqual(json.loads(output.getvalue()), {"kind": "TEST-only-protocol-not-success-proof"})
        self.assertEqual(len(output.getvalue().splitlines()), 1)
        self.assertIn("ordinary render progress", error.getvalue())


class OpeningGraphicBoundaryTests(unittest.TestCase):
    """JSON/typed-seal matching only; mocked decoder/runtime are not OCI evidence."""

    def test_typed_seal_tuple_matches_actual_json_lists(self) -> None:
        seal = SealedInput("/TEST/input.tar", "a" * 64, ({"path": "TEST-source", "sha256": "b" * 64},), ())
        rate = normalize_render_rate("30000/1001")
        row = {"entry": {"kind": "statement-card"}, "startFrame": 10, "endFrameExclusive": 70}
        intent = OpeningGraphicIntent(row, rate, seal, (1920, 1080), ("TEST-only text",), "TEST-key")
        runtime = {"snapshotSha256": seal.sha256, "snapshotManifest": list(seal.manifest),
            "containerBeforeOutput": {"Name": "/TEST-owned"}, "containerAfterOutput": {"Name": "/TEST-owned"}}
        proof = {"asset": {"frameCount": 60, "fps": rate.numeric, "sha256": "c" * 64},
            "runtimeAttestation": runtime, "assetInputs": [], "copy": {"expected": ["TEST-only text"]}}
        result = {"path": "/TEST/asset.mp4", "cached": False, "key": "TEST-key", "fmt": "mp4",
            "fps": rate.token, "kind": "statement-card", "proof": proof}
        with patch("guided_opening_graphic_proof.file_hash", return_value="c" * 64), \
                patch("guided_opening_graphic_proof.validate_runtime_attestation"), \
                patch("guided_opening_graphic_proof.observe_picture", return_value={"TEST": "mocked decoder"}):
            observed = verify_graphic_result(result, intent, ("TEST-image", "TEST-owned", {}))
        self.assertEqual(observed["renderKey"], "TEST-key")


if __name__ == "__main__":
    unittest.main(verbosity=2)
