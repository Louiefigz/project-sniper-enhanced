"""Descriptor-bound reads reject path identity swaps."""
from __future__ import annotations

import os
import shutil
import tempfile
import unittest
from collections.abc import Callable
from typing import Any
from unittest.mock import patch

from edit import cut_repair_context_sources as sources


class ContextSourceStableReadTests(unittest.TestCase):
    def setUp(self) -> None:
        self.root = os.path.realpath(tempfile.mkdtemp())
        self.path = os.path.join(self.root, "authority.json")
        self.backup = os.path.join(self.root, "authority.original.json")

    def tearDown(self) -> None:
        shutil.rmtree(self.root, ignore_errors=True)

    def _swap_after_first_read(self, replacement: bytes) -> Any:
        original_read = os.read
        swapped = False

        def read_and_swap(descriptor: int, size: int) -> bytes:
            nonlocal swapped
            chunk = original_read(descriptor, size)
            if not swapped:
                os.replace(self.path, self.backup)
                with open(self.path, "wb") as stream:
                    stream.write(replacement)
                swapped = True
            return chunk

        return patch.object(sources.os, "read", side_effect=read_and_swap)

    def _assert_swap_rejected(
            self, reader: Callable[[str, str], object], original: bytes,
            replacement: bytes) -> None:
        with open(self.path, "wb") as stream:
            stream.write(original)
        with self._swap_after_first_read(replacement):
            with self.assertRaisesRegex(
                    sources.ContextMaterializationError,
                    "changed while read"):
                reader(self.path, "authority")
        os.unlink(self.path)
        os.replace(self.backup, self.path)

    def test_all_readers_reject_same_path_new_inode(self) -> None:
        cases = (
            (sources.stable_file_digest, b"original", b"replaced"),
            (sources.stable_json, b'{"value":"original"}',
             b'{"value":"replaced"}'),
            (sources.stable_text, b"original text", b"replaced text"),
        )
        for reader, original, replacement in cases:
            with self.subTest(reader=reader.__name__):
                self._assert_swap_rejected(reader, original, replacement)


if __name__ == "__main__":
    unittest.main(verbosity=2)
