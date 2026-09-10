"""Pure command-contract checks; no encoder, OCI or source admission runs."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

import live_grade_v2_fixture as fixture
from headless.container_policy import DockerRuntime
from headless.external_media_probe_policy import container_command

from live_grade_v2_fixture import encode_arguments


class GradeV2FixtureContractTests(unittest.TestCase):
    """The opt-in fixture never selects creator inputs or silently upgrades media."""

    def test_native_24_frame_original_rate_with_no_audio_or_transform(self) -> None:
        args = encode_arguments(Path("/unused/TEST-UHD-tagged.mp4"))
        self.assertEqual(args[args.index("-frames:v") + 1], "24")
        self.assertEqual(args[args.index("-i") + 1], "color=c=0x808080:s=3840x2160:r=24000/1001")
        self.assertEqual(args[args.index("-video_track_timescale") + 1], "24000")
        self.assertIn("-an", args)
        self.assertNotIn("zscale", " ".join(args))
        self.assertNotIn("-y", args)

    def test_tags_are_explicit_at_initial_test_encode_not_a_creator_source_relabel(self) -> None:
        args = encode_arguments(Path("/unused/TEST-UHD-tagged.mp4"))
        self.assertEqual(args[args.index("-color_trc") + 1], "iec61966-2-4")
        self.assertEqual(args[args.index("-colorspace") + 1], "bt709")
        self.assertEqual(args[args.index("-pix_fmt") + 1], "yuv420p")
        self.assertEqual(args[args.index("-threads") + 1], "4")
        self.assertEqual(args.count("-i"), 1)



class GradeV2AdmissionBoundaryTests(unittest.TestCase):
    """Fake source/daemon calls exercise the real policy command and original clock."""

    def policy_admission(self, source: str, store: str, limits: object) -> dict:
        """Build the real policy command without executing its nonexistent TEST tool."""
        runtime = DockerRuntime("/TEST/not-executed/docker", "/TEST/not-contacted/socket",
                                "sha256:" + "a" * 64, "501:20", {})
        argv = container_command(runtime, store, "TEST-probe", source, limits)
        self.assertEqual(argv[-1], "90")
        self.assertEqual(argv[argv.index("--network") + 1], "none")
        self.assertEqual(argv[argv.index("--pull") + 1], "never")
        return {"TEST-mocked-admission-not-source-authority": True}

    def test_real_admission_callback_respects_policy_after_actual_setup_cost(self) -> None:
        """Call create_fixture's actual callback, retaining 120s rather than resetting it."""
        clock = [1000.0]
        def encode(_root: Path, _output: Path, deadline: float) -> None:
            """Charge 20s of explicit TEST setup without encoding."""
            self.assertEqual(deadline, 1120.0)
            clock[0] = 1020.0
        def ingest(candidates: list, producer: Path, admit: object) -> object:
            """Invoke the exact callback supplied by the unchanged ingress workflow."""
            self.assertEqual(len(candidates), 1)
            self.assertTrue(admit(str(producer / "TEST.mp4"), str(producer)))
            return object()
        with tempfile.TemporaryDirectory(prefix="sniper-v2-unit-policy-", dir="/private/tmp") as raw:
            with mock.patch.object(fixture.tempfile, "mkdtemp", return_value=raw), \
                    mock.patch.object(fixture.time, "monotonic", side_effect=lambda: clock[0]), \
                    mock.patch.object(fixture, "_encode", side_effect=encode), \
                    mock.patch.object(fixture, "file_hash", return_value="b" * 64), \
                    mock.patch.object(fixture, "admit_external_media", side_effect=self.policy_admission) as admission, \
                    mock.patch.object(fixture, "admit_ingest_candidates", side_effect=ingest), \
                    mock.patch.object(fixture, "_publish", side_effect=lambda project, _admitted, _original: project / "producer"), \
                    redirect_stdout(io.StringIO()):
                result = fixture.create_fixture()
                self.assertEqual(result, Path(raw) / "synthetic/producer")
                self.assertEqual(admission.call_count, 1)
                self.assertEqual(json.loads((Path(raw) / "TEST-fixture.json").read_text())["elapsedMs"], 20000)

    def test_original_remainder_below_policy_minimum_cannot_start_admission(self) -> None:
        """No rounded-up minimum or fresh 90s allowance after setup consumed the credit."""
        with mock.patch.object(fixture.time, "monotonic", return_value=1030.001), \
                mock.patch.object(fixture, "admit_external_media") as admission:
            with self.assertRaisesRegex(RuntimeError, "original 120s"):
                fixture._admit_source("/TEST/source", "/TEST/store", 1120.0)
            admission.assert_not_called()

    def test_late_admission_returns_through_cleanup_but_never_setup_success(self) -> None:
        """A slow actual boundary is not interrupted before its own mandatory cleanup."""
        clock, cleaned = [1000.0], []
        def completed(source: str, store: str, limits: object) -> dict:
            """Advance past original deadline only after the mock owned cleanup finishes."""
            result = self.policy_admission(source, store, limits)
            cleaned.append(True)
            clock[0] = 1120.001
            return result
        with mock.patch.object(fixture.time, "monotonic", side_effect=lambda: clock[0]), \
                mock.patch.object(fixture, "admit_external_media", side_effect=completed):
            with self.assertRaisesRegex(RuntimeError, "deadline"):
                fixture._admit_source("/TEST/source", "/TEST/store", 1120.0)
        self.assertEqual(cleaned, [True])

    def test_local_encoder_passes_absolute_resolved_binary_to_the_existing_runner(self) -> None:
        """Exercise the actual helper with inert bytes, no local encoder invocation."""
        with tempfile.TemporaryDirectory(prefix="sniper-v2-encoder-unit-", dir="/private/tmp") as raw:
            root = Path(raw)
            binary = root / "ffmpeg-real"
            binary.write_text("TEST inert non-executable tool bytes")
            alias = root / "ffmpeg"
            alias.symlink_to(binary)
            with mock.patch.object(fixture.shutil, "which", return_value=str(alias)), \
                    mock.patch.object(fixture, "run_text", return_value=SimpleNamespace(returncode=0, stdout="", stderr="")) as run:
                fixture._encode(root, root / "TEST.mp4", fixture.time.monotonic() + 30)
                request = run.call_args.args[0]
                self.assertEqual(request.command[0], str(binary.resolve()))
                self.assertTrue(Path(request.command[0]).is_absolute())
                self.assertLessEqual(request.timeout_seconds, 30)


if __name__ == "__main__":
    unittest.main()
