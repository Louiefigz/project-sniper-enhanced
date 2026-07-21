from __future__ import annotations

import os
import stat
import unittest
from unittest import mock

from _common import pl  # noqa: F401
from _generation_sealer_fixture import SealerFixture, canonical, write
import headless.generation_sealer_final as final_module
import headless.generation_sealer_source as source_module
from headless.generation_reader_fs import (
    _MUTABLE_FILE,
    _Pinned,
    _Policy,
    _safe,
)
from headless.generation_sealer import seal_generation
from headless.generation_sealer_types import (
    MAX_FILE_BYTES,
    GenerationSealError,
    GenerationSealRequestV1,
)


class GenerationSealerAdversarialTests(unittest.TestCase):
    def _reject(
        self, fixture: SealerFixture, commit: bytes | None = None
    ) -> None:
        with self.assertRaises(GenerationSealError):
            seal_generation(fixture.request(commit))
        self.assertFalse(fixture.final().exists())

    def test_symlink_hardlink_and_fifo_payloads_reject(self) -> None:
        for kind in ("symlink", "hardlink", "fifo"):
            fixture = SealerFixture()
            try:
                target = fixture.staging / "media/final.mp4"
                target.unlink()
                outside = fixture.root / f"outside-{kind}"
                if kind == "symlink":
                    write(outside, fixture.files["media/final.mp4"], 0o600)
                    target.symlink_to(outside)
                elif kind == "hardlink":
                    write(outside, fixture.files["media/final.mp4"], 0o600)
                    os.link(outside, target)
                elif kind == "fifo":
                    os.mkfifo(target, 0o600)
                with self.subTest(kind=kind):
                    self._reject(fixture)
                    self.assertFalse(fixture.pending().exists())
            finally:
                fixture.close()

    def test_device_and_socket_types_are_not_safe_staging_files(self) -> None:
        policy = _Policy(7, os.geteuid())
        for node_type in (stat.S_IFCHR, stat.S_IFBLK, stat.S_IFSOCK):
            info = mock.Mock(
                st_mode=node_type | 0o600,
                st_nlink=1,
                st_dev=7,
                st_uid=os.geteuid(),
            )
            with self.subTest(node_type=node_type):
                self.assertFalse(_safe(info, _MUTABLE_FILE, policy))

    def test_unknown_missing_and_unsafe_mode_nodes_reject(self) -> None:
        mutations = (
            lambda f: write(f.staging / "unknown.bin", b"x", 0o600),
            lambda f: (f.staging / "proof/qc.json").unlink(),
            lambda f: (f.staging / "proof/qc.json").chmod(0o644),
            lambda f: (f.staging / "proof").chmod(0o755),
        )
        for mutate in mutations:
            fixture = SealerFixture()
            try:
                mutate(fixture)
                with self.subTest(mutation=mutate):
                    self._reject(fixture)
                    self.assertFalse(fixture.pending().exists())
            finally:
                fixture.close()

    def test_size_digest_duplicate_and_resource_abuse_reject(self) -> None:
        fixture = SealerFixture()
        try:
            target = fixture.staging / "media/final.mp4"
            target.write_bytes(b"X" * len(target.read_bytes()))
            self._reject(fixture)
        finally:
            fixture.close()
        for mutation in ("duplicate", "oversize"):
            fixture = SealerFixture()
            try:
                document = fixture.commit_document()
                if mutation == "duplicate":
                    document["files"].append(dict(document["files"][0]))
                else:
                    document["files"][0]["sizeBytes"] = MAX_FILE_BYTES + 1
                with self.subTest(mutation=mutation):
                    self._reject(fixture, canonical(document))
            finally:
                fixture.close()

    def test_file_directory_prefix_collision_rejects_before_authority_writes(
        self,
    ) -> None:
        fixture = SealerFixture()
        try:
            document = fixture.commit_document()
            document["files"].append(
                {
                    "artifactClass": "hostile-prefix-v1",
                    "path": "authority",
                    "sha256": "e3b0c44298fc1c149afbf4c8996fb924"
                    "27ae41e4649b934ca495991b7852b855",
                    "sizeBytes": 0,
                }
            )
            self._reject(fixture, canonical(document))
            self.assertEqual(tuple(fixture.authority.iterdir()), ())
        finally:
            fixture.close()

    def test_late_same_inode_write_and_replacement_reject(self) -> None:
        for kind in ("write", "replace"):
            fixture = SealerFixture()
            original = source_module._copy_leaf
            changed = []

            def mutate_after_copy(source, output, row, context):
                original(source, output, row, context)
                if changed:
                    return
                target = fixture.staging / row.path
                raw = target.read_bytes()
                if kind == "write":
                    target.write_bytes(b"X" * len(raw))
                    target.chmod(0o600)
                else:
                    replacement = fixture.root / "replacement"
                    write(replacement, raw, 0o600)
                    os.replace(replacement, target)
                changed.append(True)

            try:
                with self.subTest(kind=kind), mock.patch.object(
                    source_module, "_copy_leaf", mutate_after_copy
                ):
                    self._reject(fixture)
                    self.assertTrue(changed)
                    self.assertFalse(fixture.pending().exists())
            finally:
                fixture.close()

    def test_late_unknown_entry_rejects_and_is_not_copied(self) -> None:
        fixture = SealerFixture()
        original = source_module._copy_tree
        changed = []

        def add_after_walk(source, output, tree, context):
            original(source, output, tree, context)
            if source.name == str(fixture.staging) and not changed:
                write(fixture.staging / "late.bin", b"late", 0o600)
                changed.append(True)

        try:
            with mock.patch.object(
                source_module, "_copy_tree", add_after_walk
            ):
                self._reject(fixture)
            self.assertFalse(fixture.pending().exists())
        finally:
            fixture.close()

    def test_exact_generation_id_equivocation_fails_closed(self) -> None:
        fixture = SealerFixture()
        try:
            seal_generation(fixture.request())
            changed = fixture.changed_commit("media/final.mp4", b"different")
            before = (fixture.final() / "commit.json").read_bytes()
            with self.assertRaisesRegex(GenerationSealError, "equivocation"):
                seal_generation(fixture.request(changed))
            self.assertEqual(
                (fixture.final() / "commit.json").read_bytes(), before
            )
        finally:
            fixture.close()

    def test_corrupt_final_collision_never_falls_back_to_staging(self) -> None:
        fixture = SealerFixture()
        try:
            seal_generation(fixture.request())
            final = fixture.final()
            commit = final / "commit.json"
            final.chmod(0o700)
            commit.chmod(0o600)
            commit.write_bytes(b"{}")
            commit.chmod(0o400)
            final.chmod(0o500)
            with self.assertRaises(GenerationSealError):
                seal_generation(fixture.request())
            self.assertEqual(commit.read_bytes(), b"{}")
        finally:
            fixture.close()

    def test_atomic_install_never_replaces_a_racing_empty_final(self) -> None:
        fixture = SealerFixture()
        original = final_module._rename_noreplace
        raced = []

        def race(generations: _Pinned, source: str, target: str) -> None:
            if target != fixture.final().name:
                original(generations, source, target)
                return
            final = fixture.authority / "generations" / target
            final.mkdir(mode=0o500)
            raced.append(final.stat().st_ino)
            original(generations, source, target)

        try:
            with mock.patch.object(final_module, "_rename_noreplace", race):
                with self.assertRaisesRegex(GenerationSealError, "collision"):
                    seal_generation(fixture.request())
            self.assertEqual(fixture.final().stat().st_ino, raced[0])
            self.assertEqual(tuple(fixture.final().iterdir()), ())
            self.assertFalse(fixture.pending().exists())
        finally:
            fixture.close()

    def test_missing_atomic_noreplace_support_fails_and_cleans_pending(
        self,
    ) -> None:
        fixture = SealerFixture()
        try:
            with mock.patch.object(
                final_module.ctypes, "CDLL", return_value=object()
            ):
                with self.assertRaisesRegex(
                    GenerationSealError, "unavailable"
                ):
                    seal_generation(fixture.request())
            self.assertFalse(fixture.final().exists())
            self.assertFalse(fixture.pending().exists())
        finally:
            fixture.close()

    def test_overlapping_roots_and_oversized_commit_reject_before_writes(
        self,
    ) -> None:
        fixture = SealerFixture()
        try:
            overlap = GenerationSealRequestV1(
                str(fixture.authority),
                str(fixture.authority),
                fixture.commit_json,
            )
            with self.assertRaises(GenerationSealError):
                seal_generation(overlap)
            huge = fixture.commit_json + b" " * (16 * 1024 * 1024)
            with self.assertRaises(GenerationSealError):
                seal_generation(fixture.request(huge))
            self.assertEqual(tuple(fixture.authority.iterdir()), ())
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
