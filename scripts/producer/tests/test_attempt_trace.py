from __future__ import annotations

import hashlib
import json
import os
import sys
import tempfile
import unittest
import zlib
from dataclasses import replace
from pathlib import Path

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))

from headless.attempt_trace import (  # noqa: E402
    LOCK_NAME,
    TRACE_NAME,
    AttemptTrace,
    TornTraceTail,
    TraceContext,
    TraceCorruption,
    TraceError,
    UnsafeTracePath,
)


def _context() -> TraceContext:
    return TraceContext(
        unit_id="unit-001",
        attempt_id="attempt-001",
        release_id="release-test",
        build_id="build-test",
        boot_id="boot-test-stable-001",
        policy_id="policy-test",
        expected_parent="generation-0:commit-0:sequence-0",
        request_digest=hashlib.sha256(b"normalized-request").hexdigest(),
        authority_id="authority-mp4-v1",
    )


def _frames(attempt_dir: str) -> list[dict]:
    path = os.path.join(attempt_dir, TRACE_NAME)
    with open(path, "rb") as handle:
        return [json.loads(line) for line in handle.readlines()]


class AttemptTraceTests(unittest.TestCase):
    """Canonical frame, path-safety, and recovery behavior."""

    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.attempt_dir = os.path.join(self.temp.name, "attempt")
        os.mkdir(self.attempt_dir, 0o700)
        self.trace = AttemptTrace(self.attempt_dir, _context())

    def _trace_path(self) -> str:
        return os.path.join(self.attempt_dir, TRACE_NAME)

    def test_frames_are_canonical_chained_and_identity_complete(self) -> None:
        first = self.trace.append("ADMITTED", {"queueNs": 4})
        lock_path = os.path.join(self.attempt_dir, LOCK_NAME)
        lock_inode = os.stat(lock_path).st_ino
        second = self.trace.append(
            "PROVIDER_END",
            {
                "providerRawEventDigest": "a" * 64,
                "inputTokens": 2,
                "outputTokens": 1,
            },
        )
        state = self.trace.validate()
        self.assertEqual((state.record_count, state.last_sequence), (2, 2))
        self.assertEqual(state.last_digest, second.event_digest)
        self.assertEqual(os.stat(lock_path).st_ino, lock_inode)
        with open(self._trace_path(), "rb") as handle:
            raw_lines = handle.readlines()
        frames = [json.loads(line) for line in raw_lines]
        for raw, frame in zip(raw_lines, frames):
            canonical = json.dumps(
                frame, ensure_ascii=False, separators=(",", ":"), sort_keys=True
            ).encode()
            self.assertEqual(raw, canonical + b"\n")
            payload_bytes = json.dumps(
                frame["payload"],
                ensure_ascii=False,
                separators=(",", ":"),
                sort_keys=True,
            ).encode()
            self.assertEqual(frame["payloadByteLength"], len(payload_bytes))
            self.assertEqual(
                frame["payloadCrc32"], f"{zlib.crc32(payload_bytes) & 0xffffffff:08x}"
            )
        self.assertEqual(frames[0]["sequence"], first.sequence)
        self.assertEqual(frames[1]["priorDigest"], frames[0]["eventDigest"])
        payload = frames[1]["payload"]
        self.assertEqual(payload["unitId"], "unit-001")
        self.assertEqual(payload["attemptId"], "attempt-001")
        self.assertEqual(payload["bootId"], "boot-test-stable-001")
        self.assertEqual(payload["monotonicClock"], "CLOCK_MONOTONIC")
        self.assertIsInstance(payload["monotonicNs"], int)
        self.assertTrue(payload["wallTime"].endswith("+00:00"))

    def test_torn_tail_requires_explicit_recovery(self) -> None:
        self.trace.append("ADMITTED")
        self.trace.append("WORKER_END", {"exitCode": 137})
        with open(self._trace_path(), "rb") as handle:
            first, second = handle.readlines()
        fragment = second[: len(second) // 2]
        with open(self._trace_path(), "wb") as handle:
            handle.write(first + fragment)
        before = Path(self._trace_path()).read_bytes()
        with self.assertRaises(TornTraceTail) as caught:
            self.trace.validate()
        self.assertEqual(caught.exception.byte_count, len(fragment))
        with self.assertRaises(TornTraceTail):
            self.trace.append("TERMINAL_SEALED")
        self.assertEqual(Path(self._trace_path()).read_bytes(), before)
        with self.assertRaises(TraceError):
            self.trace.append("invalid-event", {}, True)
        self.assertEqual(Path(self._trace_path()).read_bytes(), before)
        result = self.trace.append(
            "TERMINAL_SEALED", {"disposition": "FAILED", "resultDigest": "d" * 64}, True
        )
        self.assertEqual(result.sequence, 2)
        self.assertEqual(result.recovered_tail_bytes, len(fragment))
        frames = _frames(self.attempt_dir)
        self.assertEqual(
            [item["payload"]["event"] for item in frames],
            ["ADMITTED", "TERMINAL_SEALED"],
        )
        self.assertEqual(
            frames[1]["payload"]["traceRecovery"], {"truncatedTailBytes": len(fragment)}
        )
        self.assertEqual(self.trace.validate().record_count, 2)

    def test_trace_identity_cannot_change_between_writers(self) -> None:
        self.trace.append("ADMITTED")
        wrong = AttemptTrace(
            self.attempt_dir, replace(_context(), boot_id="boot-other")
        )
        before = Path(self._trace_path()).read_bytes()
        with self.assertRaises(TraceCorruption):
            wrong.append("WORKER_START")
        self.assertEqual(Path(self._trace_path()).read_bytes(), before)

    def test_complete_corruption_and_fork_are_never_repaired(self) -> None:
        self.trace.append("ADMITTED")
        original = Path(self._trace_path()).read_bytes()
        corrupted = original.replace(b'"event":"ADMITTED"', b'"event":"ADMIXTED"')
        self.assertNotEqual(corrupted, original)
        Path(self._trace_path()).write_bytes(corrupted)
        with self.assertRaises(TraceCorruption):
            self.trace.append("TERMINAL_SEALED", {}, True)
        self.assertEqual(Path(self._trace_path()).read_bytes(), corrupted)
        Path(self._trace_path()).write_bytes(original)
        self.trace.append("WORKER_END")
        lines = Path(self._trace_path()).read_bytes().splitlines(keepends=True)
        Path(self._trace_path()).write_bytes(b"".join(lines + [lines[-1]]))
        with self.assertRaises(TraceCorruption):
            self.trace.validate()

    def test_secret_fields_oversize_frames_and_symlinks_are_refused(self) -> None:
        with self.assertRaises(TraceError):
            self.trace.append("PROVIDER_END", {"anthropic_api_key": "forbidden"})
        with self.assertRaises(TraceError):
            self.trace.append("PROVIDER_END", {"raw": "Bearer abcdefghijklmnop"})
        with self.assertRaises(TraceError):
            self.trace.append("PROVIDER_END", {"raw": "sk-ant-abcdefghijk"})
        with self.assertRaises(TraceError):
            self.trace.append("PROVIDER_END", {"raw": "x" * 70_000})
        cycle: list = []
        cycle.append(cycle)
        with self.assertRaises(TraceError):
            self.trace.append("PROVIDER_END", {"cycle": cycle})
        self.assertEqual(self.trace.validate().record_count, 0)
        other_dir = os.path.join(self.temp.name, "other-attempt")
        os.mkdir(other_dir, 0o700)
        target = os.path.join(self.temp.name, "outside")
        Path(target).write_text("outside", encoding="utf-8")
        os.symlink(target, os.path.join(other_dir, TRACE_NAME))
        with self.assertRaises(UnsafeTracePath):
            AttemptTrace(other_dir, _context()).append("ADMITTED")
        self.assertEqual(Path(target).read_text(encoding="utf-8"), "outside")

    def test_attempt_directory_symlink_is_refused(self) -> None:
        alias = os.path.join(self.temp.name, "attempt-alias")
        os.symlink(self.attempt_dir, alias)
        with self.assertRaises(UnsafeTracePath):
            AttemptTrace(alias, _context()).append("ADMITTED")

    def test_lock_symlink_and_trace_or_lock_hardlinks_are_refused(self) -> None:
        lock_dir = os.path.join(self.temp.name, "lock-symlink")
        os.mkdir(lock_dir, 0o700)
        outside = os.path.join(self.temp.name, "outside-lock")
        Path(outside).write_text("outside", encoding="utf-8")
        os.symlink(outside, os.path.join(lock_dir, LOCK_NAME))
        with self.assertRaises(UnsafeTracePath):
            AttemptTrace(lock_dir, _context()).append("ADMITTED")
        for index, name in enumerate((TRACE_NAME, LOCK_NAME)):
            linked_dir = os.path.join(self.temp.name, f"hardlink-{index}")
            os.mkdir(linked_dir, 0o700)
            source = os.path.join(self.temp.name, f"linked-source-{index}")
            Path(source).write_bytes(b"")
            os.chmod(source, 0o600)
            os.link(source, os.path.join(linked_dir, name))
            with self.subTest(name=name), self.assertRaises(UnsafeTracePath):
                AttemptTrace(linked_dir, _context()).append("ADMITTED")

    def test_group_writable_attempt_directory_is_refused(self) -> None:
        unsafe = os.path.join(self.temp.name, "unsafe-attempt")
        os.mkdir(unsafe, 0o770)
        os.chmod(unsafe, 0o770)
        with self.assertRaises(UnsafeTracePath):
            AttemptTrace(unsafe, _context()).append("ADMITTED")
