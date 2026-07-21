from __future__ import annotations

import json
import os
import sys
import unittest
from pathlib import Path
from unittest import mock

PRODUCER_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PRODUCER_DIR))
from _generation_reader_fixture import (  # noqa: E402
    Fixture as _Fixture,
    canonical as _canonical,
    write as _write,
)
import headless.generation_reader as reader_module  # noqa: E402
from headless.generation_reader import (  # noqa: E402
    GenerationReadError,
    read_current_generation,
)


class GenerationReaderRejectionTests(unittest.TestCase):
    def _reject(self, fixture: _Fixture) -> None:
        with self.assertRaises(GenerationReadError):
            with read_current_generation(
                str(fixture.authority), str(fixture.destination)
            ):
                pass

    def test_missing_lock_fails_without_creating_one(self) -> None:
        fixture = _Fixture()
        try:
            (fixture.authority / ".publish.mutex").unlink()
            self._reject(fixture)
            self.assertFalse((fixture.authority / ".publish.mutex").exists())
        finally:
            fixture.close()

    def test_multiply_linked_publish_lock_rejects(self) -> None:
        fixture = _Fixture()
        try:
            os.link(fixture.authority / ".publish.mutex", fixture.root / "lock-alias")
            self._reject(fixture)
        finally:
            fixture.close()

    def test_noncanonical_root_and_nonempty_destination_reject(self) -> None:
        fixture = _Fixture()
        try:
            alias = fixture.root / "authority-alias"
            alias.symlink_to(fixture.authority, target_is_directory=True)
            with self.assertRaises(GenerationReadError):
                with read_current_generation(str(alias), str(fixture.destination)):
                    pass
            _write(fixture.destination / "existing", b"x", 0o600)
            self._reject(fixture)
        finally:
            fixture.close()

    def test_unknown_and_missing_generation_nodes_reject(self) -> None:
        for mutation in ("unknown", "missing"):
            fixture = _Fixture()
            try:
                fixture.make_generation_writable()
                if mutation == "unknown":
                    _write(fixture.generation / "unknown.bin", b"x", 0o400)
                else:
                    target = fixture.generation / "media/final.mp4"
                    target.parent.chmod(0o700)
                    target.unlink()
                    target.parent.chmod(0o500)
                fixture.generation.chmod(0o500)
                self._reject(fixture)
            finally:
                fixture.close()

    def test_symlink_hardlink_and_fifo_manifest_nodes_reject(self) -> None:
        for kind in ("symlink", "hardlink", "fifo"):
            fixture = _Fixture()
            try:
                target = fixture.generation / "media/final.mp4"
                fixture.make_generation_writable()
                target.parent.chmod(0o700)
                target.unlink()
                if kind == "symlink":
                    target.symlink_to(fixture.root / "outside")
                elif kind == "hardlink":
                    outside = fixture.root / "outside"
                    _write(outside, fixture.files["media/final.mp4"], 0o400)
                    os.link(outside, target)
                else:
                    os.mkfifo(target, 0o400)
                target.parent.chmod(0o500)
                fixture.generation.chmod(0o500)
                self._reject(fixture)
            finally:
                fixture.close()

    def test_unsafe_mutable_and_sealed_modes_reject(self) -> None:
        mutations = (
            lambda f: (f.authority / "CURRENT").chmod(0o644),
            lambda f: (f.authority / ".publish.mutex").chmod(0o400),
            lambda f: (f.authority / "generations").chmod(0o755),
            lambda f: f.generation.chmod(0o700),
            lambda f: (f.generation / "proof/qc.json").chmod(0o600),
        )
        for mutate in mutations:
            fixture = _Fixture()
            try:
                mutate(fixture)
                self._reject(fixture)
            finally:
                fixture.close()

    def test_current_commit_binding_mismatch_rejects(self) -> None:
        fixture = _Fixture()
        try:
            path = fixture.authority / "CURRENT"
            current = json.loads(path.read_bytes())
            current["commitDigest"] = "0" * 64
            _write(path, _canonical(current), 0o600)
            self._reject(fixture)
        finally:
            fixture.close()

    def test_invalid_profile_rejects_before_tree_walk_or_copy(self) -> None:
        fixture = _Fixture()
        document = fixture.commit_document()
        document["files"] = [
            row
            for row in document["files"]
            if row["artifactClass"] != "base-fingerprint-v1"
        ]
        fixture.replace_commit(document)
        patches = (
            mock.patch.object(reader_module, "_manifest_tree"),
            mock.patch.object(reader_module, "_walk"),
            mock.patch.object(reader_module, "_copy_row"),
        )
        try:
            with patches[0] as tree, patches[1] as walk, patches[2] as copy:
                self._reject(fixture)
                tree.assert_not_called()
                walk.assert_not_called()
                copy.assert_not_called()
                self.assertEqual(tuple(fixture.destination.iterdir()), ())
        finally:
            fixture.close()

    def test_source_mutation_during_copy_rejects(self) -> None:
        fixture = _Fixture()
        original = reader_module._stream
        changed = []

        def mutating_stream(source_fd: int, destination_fd: int | None):
            result = original(source_fd, destination_fd)
            if destination_fd is not None and not changed:
                target = fixture.generation / "authority/approved-parent.json"
                target.chmod(0o600)
                target.write_bytes(b"changed")
                target.chmod(0o400)
                changed.append(True)
            return result

        try:
            with mock.patch.object(reader_module, "_stream", mutating_stream):
                self._reject(fixture)
        finally:
            fixture.close()

    def test_manifest_entry_replacement_during_copy_rejects(self) -> None:
        fixture = _Fixture()
        original = reader_module._stream
        changed = []

        def replacing_stream(source_fd: int, destination_fd: int | None):
            result = original(source_fd, destination_fd)
            if destination_fd is not None and not changed:
                source_inode = os.fstat(source_fd).st_ino
                relative = next(
                    path
                    for path in fixture.files
                    if (fixture.generation / path).stat().st_ino == source_inode
                )
                target = fixture.generation / relative
                target.parent.chmod(0o700)
                replacement = target.parent / ".replacement"
                _write(replacement, target.read_bytes(), 0o400)
                os.replace(replacement, target)
                target.parent.chmod(0o500)
                changed.append(True)
            return result

        try:
            with mock.patch.object(reader_module, "_stream", replacing_stream):
                self._reject(fixture)
        finally:
            fixture.close()

    def test_current_replacement_during_copy_rejects_identity_change(self) -> None:
        fixture = _Fixture()
        original = reader_module._copy_row
        changed = []

        def replacing_current(source_dir, destination_dir, row, context):
            original(source_dir, destination_dir, row, context)
            if not changed:
                current = fixture.authority / "CURRENT"
                replacement = fixture.authority / ".CURRENT.new"
                _write(replacement, current.read_bytes(), 0o600)
                os.replace(replacement, current)
                changed.append(True)

        try:
            with mock.patch.object(reader_module, "_copy_row", replacing_current):
                self._reject(fixture)
        finally:
            fixture.close()

    def test_post_copy_materialized_leaf_substitution_rejects(self) -> None:
        kinds = (
            "same-bytes-new-inode",
            "changed-bytes",
            "changed-size",
            "changed-mode",
            "symlink",
            "hardlink",
            "fifo",
        )
        for kind in kinds:
            fixture = _Fixture()
            original = reader_module._copy_row
            changed = []

            def replacing_output(source_dir, destination_dir, row, context):
                original(source_dir, destination_dir, row, context)
                if changed:
                    return
                target = fixture.destination / row.path
                expected = target.read_bytes()
                outside = fixture.root / f"outside-{kind}"
                if kind == "changed-mode":
                    target.chmod(0o644)
                else:
                    target.unlink()
                if kind == "same-bytes-new-inode":
                    _write(outside, expected, 0o600)
                    os.replace(outside, target)
                elif kind == "changed-bytes":
                    _write(target, b"X" * len(expected), 0o600)
                elif kind == "changed-size":
                    _write(target, expected + b"X", 0o600)
                elif kind == "symlink":
                    _write(outside, expected, 0o600)
                    target.symlink_to(outside)
                elif kind == "hardlink":
                    _write(outside, expected, 0o600)
                    os.link(outside, target)
                elif kind == "fifo":
                    os.mkfifo(target, 0o600)
                changed.append(True)

            try:
                with self.subTest(kind=kind), mock.patch.object(
                    reader_module, "_copy_row", replacing_output
                ):
                    self._reject(fixture)
            finally:
                fixture.close()

    def test_post_walk_unknown_materialized_node_rejects(self) -> None:
        fixture = _Fixture()
        original = reader_module._walk
        changed = []

        def adding_unknown(source, destination, tree, context):
            original(source, destination, tree, context)
            if source.fd == context.root_source_fd and not changed:
                _write(fixture.destination / "unknown.bin", b"x", 0o600)
                changed.append(True)

        try:
            with mock.patch.object(reader_module, "_walk", adding_unknown):
                self._reject(fixture)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
