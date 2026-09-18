"""Adversarial tests for immutable external-media admission."""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from headless.container_policy import DockerRuntime
from headless.external_media_probe import _terminal_failure, _wait_result
from headless.external_media_probe_policy import (
    MediaProbeLimits,
    NODE_PROBE,
    PROBE_MEMORY_BYTES,
    PROBE_MEMORY_MIB,
    _valid_host,
    container_command,
    validate_probe_document,
)
from headless.external_media_snapshot import (
    MAX_EXTERNAL_MEDIA_BYTES,
    capture_external_media_snapshot,
    verify_external_media_snapshot,
)

def _runtime() -> DockerRuntime:
    return DockerRuntime(
        docker="/usr/bin/docker",
        socket="/tmp/docker.sock",
        image_id=f"sha256:{'a' * 64}",
        user_id="1000:1000",
        approval={"config": {"environment": [
            "PATH=/usr/bin:/bin", "LANG=C.UTF-8", "LC_ALL=C.UTF-8",
        ]}},
    )


def _valid_document() -> dict:
    return {
        "schemaVersion": 1,
        "ok": True,
        "decoded": True,
        "facts": {
            "mediaKind": "timed-media",
            "durationSeconds": 60,
            "sizeBytes": 1024,
            "width": 1920,
            "height": 1080,
            "videoStreams": 1,
            "audioStreams": 1,
            "streamCount": 2,
            "declaredFrames": 1800,
        },
    }

class ExternalMediaSnapshotTests(unittest.TestCase):
    """Source races and filesystem aliases never become admitted snapshots."""

    def test_regular_snapshot_is_content_addressed_and_reobserved(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, store = root / "source.bin", root / "store"
            source.write_bytes(b"bounded-media-bytes")
            store.mkdir()
            snapshot = capture_external_media_snapshot(str(source), str(store))
            self.assertEqual(
                snapshot.sha256,
                hashlib.sha256(source.read_bytes()).hexdigest(),
            )
            self.assertEqual(os.stat(snapshot.path).st_nlink, 1)
            verify_external_media_snapshot(snapshot)
            Path(snapshot.path).write_bytes(b"mutated")
            with self.assertRaisesRegex(RuntimeError, "corrupt"):
                verify_external_media_snapshot(snapshot)

    def test_symlink_hardlink_and_sparse_oversize_reject(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, store = root / "source.bin", root / "store"
            source.write_bytes(b"x")
            store.mkdir()
            alias = root / "alias.bin"
            alias.symlink_to(source)
            with self.assertRaises(OSError):
                capture_external_media_snapshot(str(alias), str(store))
            hardlink = root / "hardlink.bin"
            os.link(source, hardlink)
            with self.assertRaisesRegex(RuntimeError, "one bounded regular"):
                capture_external_media_snapshot(str(source), str(store))
            hardlink.unlink()
            source.unlink()
            source.touch()
            os.truncate(source, MAX_EXTERNAL_MEDIA_BYTES + 1)
            with self.assertRaisesRegex(RuntimeError, "one bounded regular"):
                capture_external_media_snapshot(str(source), str(store))

    def test_symlinked_snapshot_store_rejects_before_writing(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source = root / "source.bin"
            real_store = root / "real-store"
            linked_store = root / "linked-store"
            source.write_bytes(b"external")
            real_store.mkdir()
            linked_store.symlink_to(real_store, target_is_directory=True)
            with self.assertRaisesRegex(RuntimeError, "real directory"):
                capture_external_media_snapshot(
                    str(source), str(linked_store))
            self.assertEqual(list(real_store.iterdir()), [])

    def test_source_mutation_during_copy_cannot_publish(self) -> None:
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            source, store = root / "source.bin", root / "store"
            source.write_bytes(b"before")
            store.mkdir()

            def mutate() -> None:
                source.write_bytes(b"after")

            with self.assertRaisesRegex(RuntimeError, "changed during"):
                capture_external_media_snapshot(
                    str(source), str(store), mutate)
            self.assertEqual(list(store.glob("*.media")), [])


class ExternalMediaProbePolicyTests(unittest.TestCase):
    """Malformed, oversized, truncated, and hanging evidence fails closed."""

    def test_command_has_required_isolation_and_host_result_mount(self) -> None:
        command = container_command(
            _runtime(), "/tmp/config", "sniper-media-probe-test",
            "/tmp/snapshot.media", MediaProbeLimits())
        for pair in (
            ("--network", "none"),
            ("--read-only", "--cap-drop"),
            ("--cap-drop", "ALL"),
            ("--user", "1000:1000"),
            ("--security-opt", "no-new-privileges:true"),
            ("--memory", f"{PROBE_MEMORY_MIB}m"),
            ("--memory-swap", f"{PROBE_MEMORY_MIB}m"),
            ("--pids-limit", "64"),
        ):
            index = command.index(pair[0])
            self.assertEqual(command[index + 1], pair[1])
        joined = " ".join(command)
        self.assertIn("dst=/input/media,readonly", joined)
        self.assertIn("dst=/scratch", joined)
        self.assertNotIn("--tmpfs", command)
        self.assertNotIn("DOCKER_CONFIG=", joined)
        self.assertEqual(command[-1], "1200")

    def test_attestation_requires_exact_bounded_decode_memory(self) -> None:
        host = {
            "NetworkMode": "none", "ReadonlyRootfs": True,
            "Privileged": False, "CapDrop": ["ALL"],
            "Memory": PROBE_MEMORY_BYTES, "MemorySwap": PROBE_MEMORY_BYTES,
            "NanoCpus": 4_000_000_000, "PidsLimit": 64, "Init": True,
            "SecurityOpt": ["no-new-privileges:true"], "CapAdd": None,
        }
        self.assertTrue(_valid_host(SimpleNamespace(host=host)))
        host["Memory"] = 512 * 1024 ** 2
        self.assertFalse(_valid_host(SimpleNamespace(host=host)))

    def test_oom_and_signal_failures_are_not_generic_rejections(self) -> None:
        oom = _terminal_failure({"OOMKilled": True, "ExitCode": 137})
        killed = _terminal_failure({"OOMKilled": False, "ExitCode": 137})
        self.assertIn("768 MiB memory limit", oom)
        self.assertIn("SIGKILL", killed)
        self.assertIn("DECODER_SIGNAL_", NODE_PROBE)
        self.assertIn("DECODER_EXIT_", NODE_PROBE)
        self.assertNotIn("decoder rejected input", NODE_PROBE)

    def test_decode_timeout_is_receipt_bound_and_bounded(self) -> None:
        limits = MediaProbeLimits(max_decode_seconds=321)
        self.assertEqual(MediaProbeLimits().max_decode_seconds, 1200)
        self.assertIn("const decodeMs=limits.decode*1000;", NODE_PROBE)
        self.assertNotIn("Math.ceil(duration*1000)", NODE_PROBE)
        command = container_command(
            _runtime(), "/tmp/config", "sniper-media-probe-test",
            "/tmp/snapshot.media", limits)
        self.assertEqual(command[-1], "321")
        for timeout in (89, 3601, 1.5):
            with self.subTest(timeout=timeout), self.assertRaisesRegex(
                    RuntimeError, "90..3600"):
                container_command(
                    _runtime(), "/tmp/config", "sniper-media-probe-test",
                    "/tmp/snapshot.media",
                    MediaProbeLimits(max_decode_seconds=timeout),
                )

    @unittest.skipUnless(shutil.which("node"), "node required")
    def test_embedded_probe_is_valid_javascript(self) -> None:
        result = subprocess.run(
            ["node", "--check", "-"], input=NODE_PROBE, text=True,
            capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_result_limits_reject_malformed_and_huge_facts(self) -> None:
        limits = MediaProbeLimits()
        self.assertEqual(
            validate_probe_document(_valid_document(), limits)["decoded"],
            True,
        )
        malformed = _valid_document()
        malformed["extra"] = True
        with self.assertRaisesRegex(RuntimeError, "malformed"):
            validate_probe_document(malformed, limits)
        for key, value in (
            ("width", limits.max_width + 1),
            ("height", limits.max_height + 1),
            ("declaredFrames", limits.max_frames + 1),
            ("durationSeconds", limits.max_duration_seconds + 1),
            ("streamCount", limits.max_streams + 1),
        ):
            huge = _valid_document()
            huge["facts"] = {**huge["facts"], key: value}
            with self.subTest(key=key), self.assertRaisesRegex(
                    RuntimeError, "exceed"):
                validate_probe_document(huge, limits)

    def test_still_image_svg_and_font_documents_are_bounded(self) -> None:
        limits = MediaProbeLimits()
        for kind, frames, width in (
                ("still-image", 1, 1920), ("svg", 1, 1080),
                ("font", 0, 0)):
            document = _valid_document()
            document["facts"].update({
                "mediaKind": kind, "durationSeconds": 0,
                "declaredFrames": frames, "width": width,
                "height": 0 if kind == "font" else 1080,
                "videoStreams": 0 if kind == "font" else 1,
                "audioStreams": 0, "streamCount": 1,
            })
            with self.subTest(kind=kind):
                self.assertTrue(
                    validate_probe_document(document, limits)["decoded"])

    def test_kind_specific_impossible_facts_and_nan_reject(self) -> None:
        limits = MediaProbeLimits()
        cases = []
        font_video = _valid_document()
        font_video["facts"].update({
            "mediaKind": "font", "durationSeconds": 0,
            "width": 0, "height": 0, "audioStreams": 0,
            "streamCount": 1, "declaredFrames": 0,
        })
        cases.append(font_video)
        zero_size_still = _valid_document()
        zero_size_still["facts"].update({
            "mediaKind": "still-image", "durationSeconds": 0,
            "width": 0, "audioStreams": 0, "streamCount": 1,
            "declaredFrames": 1,
        })
        cases.append(zero_size_still)
        subtitle_only = _valid_document()
        subtitle_only["facts"].update({
            "videoStreams": 0, "audioStreams": 0,
            "width": 0, "height": 0, "declaredFrames": 0,
            "streamCount": 1,
        })
        cases.append(subtitle_only)
        for document in cases:
            with self.subTest(kind=document["facts"]["mediaKind"]):
                with self.assertRaisesRegex(RuntimeError, "inconsistent"):
                    validate_probe_document(document, limits)
        nan_size = _valid_document()
        nan_size["facts"]["width"] = float("nan")
        with self.assertRaisesRegex(RuntimeError, "not numeric"):
            validate_probe_document(nan_size, limits)

    def test_truncated_rejection_and_decoder_hang_do_not_admit(self) -> None:
        rejected = json.dumps({"schemaVersion": 1, "ok": False,
                               "code": "DECODE_REJECTED",
                               "message": "truncated stream"})
        with patch(
            "headless.external_media_probe._read_result",
            return_value=rejected,
        ), self.assertRaisesRegex(RuntimeError, "DECODE_REJECTED"):
            _wait_result(_runtime(), "/tmp/config", "probe")
        with patch(
            "headless.external_media_probe._read_result",
            return_value=None,
        ), patch(
            "headless.external_media_probe.time.monotonic",
            side_effect=[0, 111],
        ), self.assertRaisesRegex(RuntimeError, "exceeded 110"):
            _wait_result(_runtime(), "/tmp/config", "probe")
        with self.assertRaisesRegex(RuntimeError, "wait bound"):
            _wait_result(_runtime(), "/tmp/config", "probe", 109)


if __name__ == "__main__":
    unittest.main()
