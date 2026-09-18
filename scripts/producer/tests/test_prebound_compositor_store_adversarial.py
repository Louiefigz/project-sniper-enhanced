"""Filesystem attacks against the private prebound candidate store."""

from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from headless import prebound_compositor_store as store_module
from headless.prebound_compositor_store import CandidateStore
from headless.quality_pass_contract import ArtifactRefV1


class _StringSubclass(str):
    pass


class PreboundCompositorStoreAdversarialTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.candidate = self.root / "candidate"
        self.candidate.mkdir(mode=0o700)
        os.chmod(self.candidate, 0o700)
        self.source = self.root / "source.bin"
        self.source.write_bytes(b"source")
        os.chmod(self.source, 0o600)
        self.ref = ArtifactRefV1(
            "source.bin", hashlib.sha256(b"source").hexdigest(), 6
        )

    def _store(self, resolver=None) -> CandidateStore:
        callback = resolver or (lambda _ref: str(self.source))
        store = CandidateStore.open(str(self.candidate), callback)
        self.addCleanup(store.close)
        return store

    def test_nonempty_root_rejects_without_unbounded_listdir(self) -> None:
        extra = self.candidate / "unexpected"
        extra.write_bytes(b"x")
        os.chmod(extra, 0o600)
        with mock.patch.object(
            store_module.os,
            "listdir",
            side_effect=AssertionError("unbounded enumeration"),
            create=True,
        ), self.assertRaisesRegex(RuntimeError, "new empty"):
            CandidateStore.open(
                str(self.candidate), lambda ref: str(self.source)
            )

    def test_write_is_create_once_and_preserves_existing_bytes(self) -> None:
        store = self._store()
        existing = self.candidate / "result.json"
        existing.write_bytes(b"foreign")
        os.chmod(existing, 0o600)
        with self.assertRaises(RuntimeError):
            store.write("result.json", b"replacement")
        self.assertEqual(existing.read_bytes(), b"foreign")

    def test_names_cannot_escape_candidate_root(self) -> None:
        store = self._store()
        for name in ("../escape", "nested/file", "bad\\name", ".", ""):
            with self.subTest(name=name), self.assertRaisesRegex(
                RuntimeError, "name is invalid"
            ):
                store.import_artifact(self.ref, name)
        self.assertFalse((self.root / "escape").exists())

    def test_resolver_string_subclass_is_rejected(self) -> None:
        store = self._store(lambda _ref: _StringSubclass(str(self.source)))
        with self.assertRaisesRegex(RuntimeError, "ambient path"):
            store.import_artifact(self.ref, "source.bin")

    def test_promote_does_not_replace_existing_final(self) -> None:
        store = self._store()
        pending = self.candidate / ".pending.mp4"
        final = self.candidate / "final.mp4"
        pending.write_bytes(b"candidate")
        final.write_bytes(b"foreign")
        os.chmod(pending, 0o600)
        os.chmod(final, 0o600)
        with self.assertRaises(FileExistsError):
            store.promote(pending.name, final.name)
        self.assertEqual(final.read_bytes(), b"foreign")
        self.assertEqual(pending.read_bytes(), b"candidate")

    def test_pending_swap_during_link_never_returns_success(self) -> None:
        store = self._store()
        pending = self.candidate / ".pending.mp4"
        replacement = self.candidate / ".replacement.mp4"
        pending.write_bytes(b"candidate")
        replacement.write_bytes(b"attacker")
        os.chmod(pending, 0o600)
        os.chmod(replacement, 0o600)
        original_link = os.link

        def swap_then_link(*args, **kwargs):
            os.replace(replacement, pending)
            return original_link(*args, **kwargs)

        with mock.patch.object(
            store_module.os, "link", side_effect=swap_then_link
        ), self.assertRaisesRegex(RuntimeError, "changed during promotion"):
            store.promote(pending.name, "final.mp4")


if __name__ == "__main__":
    unittest.main(verbosity=2)
