"""Independent lifetime alias/capture regressions over named TEST-owned files.

All sources, tools and code are inert bytes inside the fixture root. The local
UNIX socket has no listener or daemon. No media/provider/native runner executes.
"""
from __future__ import annotations

from dataclasses import replace
import json
import stat
import time
import unittest
from unittest.mock import patch

from _guided_opening_lifetime_fixture import OpeningLifetimeFixture
from cut_preview_io import digest, file_hash
import guided_opening_lifetime as lifetime
from headless.external_media_verification import (
    SourceVerificationRuntime, VerifiedSnapshotIdentity, snapshot_stat_identity,
)
from ingest_media_observation import SourceVerificationCapture, VerifiedExecutionMedia


def _rewrite(fixture: OpeningLifetimeFixture, name: str, value: dict) -> None:
    """Replace only an explicitly named canonical regular single-link TEST file."""
    path = fixture.paths[name]
    info = path.lstat()
    if path.resolve(strict=True) != path or not path.is_relative_to(fixture.root) \
            or not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise RuntimeError("TEST rewrite target is not an original private regular file")
    path.write_bytes(json.dumps(value).encode())


def _scale_pipeline(fixture: OpeningLifetimeFixture, count: int) -> None:
    """Add genuine tiny mirrored code files, not duplicate metadata-only pin rows."""
    lock_path = fixture.paths["pipeline/pipeline-lock.json"]
    lock = json.loads(lock_path.read_bytes())
    closure = fixture.pipeline["executionClosure"]
    for index in range(count):
        logical = f"scripts/TEST-scaled-{index}.py"
        live = fixture.put("repo/" + logical, f"TEST inert code {index}\n".encode())
        copied = fixture.put("pipeline/files/" + logical, live.read_bytes())
        lock["files"].append({"path": logical, "hash": file_hash(copied)})
        closure.append({"path": logical, "sha256": file_hash(live)})
    lock["digest"] = digest(lock["files"])
    _rewrite(fixture, "pipeline/pipeline-lock.json", lock)
    expected = fixture.inputs.value["pipeline"]
    expected.update(lockSha256=file_hash(lock_path), digest=lock["digest"])
    fixture.pipeline.update(lockSha256=expected["lockSha256"], pipelineDigest=lock["digest"],
                            pinnedFileCount=len(lock["files"]))
    _rewrite(fixture, "input.json", fixture.inputs.value)
    fixture.inputs = replace(fixture.inputs, sha256=file_hash(fixture.inputs.path))


def _scale_sources(fixture: OpeningLifetimeFixture, count: int) -> None:
    """Collect actual same-pass identities from additional explicitly owned bytes."""
    capture = SourceVerificationCapture(SourceVerificationRuntime(fixture.clock.remaining))
    rows = []
    for index in range(count):
        source = fixture.put(f"media/TEST-scaled-{index}.bin", f"TEST source {index}\n".encode())
        info, sha = source.lstat(), file_hash(source)
        identity = VerifiedSnapshotIdentity(str(source), sha, info.st_size, snapshot_stat_identity(info))
        capture.add(identity)
        rows.append({"snapshotPath": str(source), "sha256": sha, "sizeBytes": info.st_size})
    fixture.inputs = replace(fixture.inputs, verified_media=capture.finish(rows))


class OpeningLifetimeFaultTests(unittest.TestCase):
    """Use the actual constructor and guard, with only declared fault boundaries."""

    def test_original_source_capture_alias_cannot_be_replaced(self) -> None:
        """An empty secondary alias cannot waive the initially verified source set."""
        fixture = OpeningLifetimeFixture(self)
        held = fixture.hold()
        held.capture = VerifiedExecutionMedia(b"[]", ())
        with self.assertRaisesRegex(RuntimeError, "original .*changed"):
            held.guard()

    def test_original_dependency_aliases_cannot_be_replaced(self) -> None:
        """Stat rows, ancestry, source runtime and socket holds retain their origin."""
        fixture = OpeningLifetimeFixture(self)
        held = fixture.hold()
        changes = {"files": (), "parents": (), "parent_identity": (),
                   "runtime": SourceVerificationRuntime(lambda: 60), "socket_identity": ()}
        for name, changed in changes.items():
            original = getattr(held, name)
            setattr(held, name, changed)
            self.assertRaisesRegex(RuntimeError, "original captured dependencies", held.guard)
            setattr(held, name, original)
        held.guard()

    def test_instance_remaining_shadow_cannot_skip_original_metadata(self) -> None:
        """A replaced inspection method must not replace private security comparisons."""
        fixture = OpeningLifetimeFixture(self)
        held = fixture.hold()
        held.remaining = lambda: 60
        fixture.inputs.documents["candidatePlan"]["TEST"] = "changed"
        with self.assertRaises(RuntimeError):
            held.guard()

    def test_dependency_hash_cannot_rebaseline_original_capture_alias(self) -> None:
        """The actual constructor cannot seal a substituted capture after hashing."""
        fixture = OpeningLifetimeFixture(self)
        observed = []
        socket_identity = lifetime.OpeningSourceLifetime._socket_identity
        original_hold = lifetime.hold_body_file

        def socket_checked(value: lifetime.OpeningSourceLifetime) -> tuple:
            """Retain the actual constructing holder at an existing observation seam."""
            observed.append(value)
            return socket_identity(value)

        def captured(*args: object) -> object:
            """Mutate only an in-memory TEST alias after actual dependency hashing."""
            result = original_hold(*args)
            observed[0].capture = VerifiedExecutionMedia(b"[]", ())
            return result

        with patch.object(lifetime.OpeningSourceLifetime, "_socket_identity", socket_checked):
            with patch.object(lifetime, "hold_body_file", side_effect=captured):
                self.assertRaises(RuntimeError, fixture.hold)

    def test_final_source_observer_cannot_replace_retained_files(self) -> None:
        """The last original source sweep cannot replace already-held control rows."""
        fixture = OpeningLifetimeFixture(self)
        held = fixture.hold()
        original = lifetime.assert_verified_snapshots

        def changed(*args: object) -> None:
            """Run the real source check before replacing only the in-memory alias."""
            original(*args)
            held.files = ()

        with patch.object(lifetime, "assert_verified_snapshots", side_effect=changed):
            self.assertRaisesRegex(RuntimeError, "original captured dependencies", held.guard)

    def test_scaled_synthetic_metadata_guard_cost_has_no_rehashes(self) -> None:
        """Measure256 extra pins/32 sources, not real-project or video performance."""
        fixture = OpeningLifetimeFixture(self)
        _scale_pipeline(fixture, 256)
        _scale_sources(fixture, 32)
        started = time.monotonic()
        held = fixture.hold()
        setup_ms = (time.monotonic() - started) * 1000
        with patch("guided_body_execution.file_hash", side_effect=AssertionError("TEST unexpected rehash")):
            started = time.monotonic()
            for _ in range(26):
                held.guard()
            elapsed_ms = (time.monotonic() - started) * 1000
        print(f"TEST synthetic lifetime: {len(held.files)} held files /32 sources; "
              f"hold={setup_ms:.3f}ms;26 guards={elapsed_ms:.3f}ms;mean={elapsed_ms / 26:.3f}ms;0 rehashes")


if __name__ == "__main__":
    unittest.main()
