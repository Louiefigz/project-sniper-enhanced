"""Adversarial tests for governed over-cap qualification conversion."""
from __future__ import annotations

import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from headless.external_media_snapshot import MAX_EXTERNAL_MEDIA_BYTES
from headless.qualification_mezzanine_policy import (
    QualificationAttestation,
    QualificationLaunch,
    attest_qualification_container,
    container_command,
)
from ingest_admission_contract import canonical_bytes
from qualification_mezzanine import (
    QualificationRequest,
    QualificationRunners,
    build_qualification_mezzanine,
    verify_qualification_evidence,
)
from qualification_mezzanine_files import (
    FileFact,
    observe_qualified_output,
)
from qualification_mezzanine_publish import (
    assert_attempt_path,
    cleanup_attempt,
    close_attempt,
    new_attempt,
)
from qualification_mezzanine_fixture import (
    envelope as _envelope,
    inspect_document as _inspect,
    runtime as _runtime,
    source_fact as _source_fact,
)


class QualificationContainerPolicyTests(unittest.TestCase):
    def test_launch_is_exact_nonroot_networkless_and_narrowly_writable(self) -> None:
        runtime = _runtime()
        request = QualificationLaunch(
            "/tmp/source.mp4", "/tmp/out", "qualified", 10800, 24)
        command = container_command(runtime, request)
        for key, value in (("--network", "none"), ("--read-only", "--cap-drop"),
                           ("--user", "501:20"), ("--memory", "2g"),
                           ("--cpus", "4")):
            self.assertEqual(command[command.index(key) + 1], value)
        mounts = [command[index + 1] for index, item in enumerate(command)
                  if item == "--mount"]
        self.assertIn("dst=/input/source,readonly", mounts[0])
        self.assertIn("dst=/output", mounts[1])
        scratch = command[command.index("--tmpfs") + 1]
        self.assertIn("uid=501,gid=20,mode=0700", scratch)
        self.assertIsInstance(command, list)

    def test_resolved_policy_attests_and_mount_tamper_rejects(self) -> None:
        runtime, source, output = _runtime(), "/tmp/source.mp4", "/tmp/out"
        request = QualificationLaunch(
            source, output, "qualified", 10800, 24)
        command = container_command(runtime, request)
        actual = _inspect(runtime, source, output, command)
        with patch(
                "headless.qualification_mezzanine_policy._inspect",
                return_value=actual):
            attested = attest_qualification_container(
                runtime, QualificationAttestation(
                    "/tmp/config", request, command))
        self.assertTrue(attested["sourceMount"]["readonly"])
        actual["Mounts"][0]["RW"] = True
        with patch(
                "headless.qualification_mezzanine_policy._inspect",
                return_value=actual), self.assertRaisesRegex(
                    RuntimeError, "isolation attestation"):
            attest_qualification_container(
                runtime, QualificationAttestation(
                    "/tmp/config", request, command))
        actual = _inspect(runtime, source, output, command)
        actual["HostConfig"]["Tmpfs"]["/scratch"] += ",exec"
        with patch(
                "headless.qualification_mezzanine_policy._inspect",
                return_value=actual), self.assertRaisesRegex(
                    RuntimeError, "isolation attestation"):
            attest_qualification_container(
                runtime, QualificationAttestation(
                    "/tmp/config", request, command))

    @unittest.skipUnless(shutil.which("node"), "node required")
    def test_worker_is_valid_javascript_and_uses_no_shell(self) -> None:
        worker = Path(__file__).parents[1] / "headless" / \
            "qualification_mezzanine_worker.js"
        result = subprocess.run(["node", "--check", str(worker)],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        text = worker.read_text()
        self.assertIn("spawnSync(program, argv", text)
        self.assertNotIn("shell: true", text)

    @unittest.skipUnless(shutil.which("node"), "node required")
    def test_worker_normalizes_only_exact_xvycc_bt709_profile(self) -> None:
        worker = Path(__file__).parents[1] / "headless" / \
            "qualification_mezzanine_worker.js"
        declarations = worker.read_text().split("\ntry {\n", 1)[0]
        cases = [
            ({"color_range": "tv", "color_space": "bt709",
              "color_transfer": "iec61966-2-4",
              "color_primaries": "bt709", "pix_fmt": "yuv420p"}, True),
            ({"color_range": "tv", "color_space": "bt709",
              "color_transfer": "iec61966-2-4",
              "color_primaries": "unknown", "pix_fmt": "yuv420p"}, False),
        ]
        for tags, accepted in cases:
            source = declarations + "\n" + (
                "try { process.stdout.write(JSON.stringify("
                f"colorDecision({json.dumps(tags)}, '24/1', 50))); "
                "} catch (error) { process.stderr.write(String(error.message)); "
                "process.exitCode = 2; }\n")
            result = subprocess.run(
                ["node", "-e", source, "8589934592", "68719476736",
                 "10800", "24"], capture_output=True, text=True)
            with self.subTest(tags=tags):
                self.assertEqual(result.returncode == 0, accepted, result.stderr)
                if accepted:
                    decision = json.loads(result.stdout)
                    self.assertEqual(
                        decision["mode"],
                        "normalize-xvycc-bt709-to-bt709-sdr")
                    self.assertIn(
                        "zscale=p=bt709:t=bt709:m=bt709:r=tv",
                        decision["filter"])
                    self.assertIn(
                        "trim=end_frame=50,setpts=PTS-STARTPTS",
                        decision["filter"])


class QualificationBuildTests(unittest.TestCase):
    def _request(self, root: Path) -> QualificationRequest:
        source = root / "source.mp4"
        source.write_bytes(b"host-hash-only")
        return QualificationRequest(
            str(source), str(root / "qualified.mp4"),
            str(root / "qualified.mp4.qualification.json"), 10800, 24)

    def _runners(self, request: QualificationRequest,
                 mutate: bool = False, bad_rate: bool = False) -> QualificationRunners:
        calls = 0

        def observe(path: str) -> FileFact:
            nonlocal calls
            calls += 1
            return _source_fact(path, mutate and calls > 1)

        def transcode(_source: str, out: str, _timeout: int, _fps: int) -> dict:
            payload = b"qualified-media"
            (Path(out) / "qualified.mp4").write_bytes(payload)
            value = _envelope(
                MAX_EXTERNAL_MEDIA_BYTES + 1, len(payload))
            if bad_rate:
                value["worker"]["outputProbe"]["facts"]["video"]["rate"] = \
                    "24000/1001"
            return value

        return QualificationRunners(observe, transcode)

    def test_build_records_declared_rate_approximation_and_pending_v2(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            request = self._request(Path(raw))
            document = build_qualification_mezzanine(
                request, self._runners(request))
            cadence = document["execution"]["cadenceDecision"]
            self.assertEqual((cadence["sourceRate"], cadence["sourceFrames"]),
                             ("24000/1001", 20004))
            self.assertEqual((cadence["targetRate"], cadence["targetFrames"]),
                             ("24/1", 20024))
            self.assertFalse(document["sourceEligibility"]["eligible"])
            self.assertEqual(document["sourceEligibility"]["requiredPolicy"],
                             "sniper-external-media-probe-v2")
            payload = Path(request.evidence).read_bytes()
            self.assertEqual(payload, canonical_bytes(json.loads(payload)))
            self.assertEqual(stat.S_IMODE(os.stat(request.output).st_mode), 0o400)
            self.assertEqual(verify_qualification_evidence(
                request.evidence)["evidenceDigest"], document["evidenceDigest"])

    def test_host_contract_accepts_only_exact_xvycc_normalization(self) -> None:
        prefix = (
            "zscale=t=linear:npl=100,format=gbrpf32le,"
            "zscale=p=bt709:t=bt709:m=bt709:r=tv,"
        )
        for tampered in (False, True):
            with self.subTest(tampered=tampered), \
                    tempfile.TemporaryDirectory() as raw:
                request = self._request(Path(raw))
                runners = self._runners(request)
                original = runners.isolated_transcode

                def transcode(*args):
                    value = original(*args)
                    decision = value["worker"]["colorDecision"]
                    decision["mode"] = \
                        "normalize-xvycc-bt709-to-bt709-sdr"
                    decision["sourceTags"]["transfer"] = "iec61966-2-4"
                    decision["filter"] = prefix + decision["filter"]
                    if tampered:
                        decision["filter"] = decision["filter"].replace(
                            "npl=100", "npl=99")
                    argv = value["worker"]["transcode"]["argv"]
                    argv[argv.index("-vf") + 1] = decision["filter"]
                    return value

                selected = QualificationRunners(
                    runners.source_observer, transcode)
                if tampered:
                    with self.assertRaisesRegex(
                            RuntimeError, "color decision"):
                        build_qualification_mezzanine(request, selected)
                else:
                    document = build_qualification_mezzanine(
                        request, selected)
                    self.assertEqual(
                        document["execution"]["colorDecision"]["mode"],
                        "normalize-xvycc-bt709-to-bt709-sdr")

    def test_mutation_bad_profile_and_false_removal_never_publish(self) -> None:
        for mode in ("mutation", "rate", "removal"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as raw:
                request = self._request(Path(raw))
                runners = self._runners(
                    request, mutate=mode == "mutation", bad_rate=mode == "rate")
                if mode == "removal":
                    original = runners.isolated_transcode

                    def false_removal(*args):
                        value = original(*args)
                        value["removal"]["canonicalAbsenceProved"] = False
                        return value

                    runners = QualificationRunners(
                        runners.source_observer, false_removal)
                with self.assertRaises(RuntimeError):
                    build_qualification_mezzanine(request, runners)
                self.assertFalse(os.path.lexists(request.output))
                self.assertFalse(os.path.lexists(request.evidence))

    def test_links_collisions_and_oversize_outputs_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root, request = Path(raw), self._request(Path(raw))
            link = Path(request.output)
            link.symlink_to(root / "missing")
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                build_qualification_mezzanine(request, self._runners(request))
            link.unlink()
            huge = root / "huge.mp4"
            huge.touch()
            os.truncate(huge, MAX_EXTERNAL_MEDIA_BYTES + 1)
            with self.assertRaisesRegex(RuntimeError, "byte bounds"):
                observe_qualified_output(str(huge))

    def test_private_stage_rejects_preexisting_result_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            attempt = new_attempt(root)
            try:
                moved = root / ".moved"
                os.rename(attempt.path, moved)
                attempt.path.symlink_to(moved)
                with self.assertRaisesRegex(RuntimeError, "pathname changed"):
                    assert_attempt_path(attempt)
            finally:
                if os.path.lexists(attempt.path):
                    os.unlink(attempt.path)
                os.rename(moved, attempt.path)
                cleanup_attempt(attempt)
                close_attempt(attempt)


if __name__ == "__main__":
    unittest.main()
