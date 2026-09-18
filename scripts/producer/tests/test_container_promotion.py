"""Adversarial no-follow promotion tests."""

from __future__ import annotations

import os
import stat
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from _common import pl  # noqa: F401
from headless import container_io
from test_container_io import _motion_tree


class ContainerPromotionTests(unittest.TestCase):
    def _reject(self, make_source) -> None:
        with tempfile.TemporaryDirectory() as root:
            staged = os.path.join(root, "staged.mov")
            output = os.path.join(root, "output.mov")
            cleanup = make_source(staged)
            try:
                with self.assertRaises((OSError, RuntimeError)):
                    container_io.promote_regular(staged, output)
                self.assertFalse(os.path.lexists(output))
            finally:
                if cleanup:
                    cleanup()

    def test_regular_output_is_copied_to_a_fresh_inode(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            staged = os.path.join(root, "staged.mov")
            output = os.path.join(root, "output.mov")
            Path(staged).write_bytes(b"rendered-media")
            source_inode = os.stat(staged).st_ino
            container_io.promote_regular(staged, output)
            self.assertEqual(Path(output).read_bytes(), b"rendered-media")
            self.assertNotEqual(os.stat(output).st_ino, source_inode)
            self.assertEqual(os.stat(output).st_nlink, 1)

    def test_missing_destination_directory_closes_source_descriptor(self) -> None:
        before = mock.Mock()
        with mock.patch.object(
            container_io, "_source_fd", return_value=(123, before)
        ), mock.patch.object(
            container_io.os, "open", side_effect=FileNotFoundError
        ), mock.patch.object(
            container_io.os, "close"
        ) as close:
            with self.assertRaises(FileNotFoundError):
                container_io.promote_regular("staged.mov", "/missing/output.mov")
        close.assert_called_once_with(123)

    def test_symlink_hardlink_and_fifo_are_rejected(self) -> None:
        self._reject(lambda path: os.symlink("/etc/hosts", path))

        def hardlink(path: str):
            target = path + ".target"
            Path(target).write_bytes(b"media")
            os.link(target, path)

        self._reject(hardlink)
        self._reject(lambda path: os.mkfifo(path))

    def test_socket_inode_is_rejected(self) -> None:
        socket_info = os.stat_result((stat.S_IFSOCK | 0o600, 1, 1, 1, 0, 0, 0, 0, 0, 0))
        with mock.patch.object(
            container_io.os, "open", return_value=123
        ), mock.patch.object(
            container_io.os, "fstat", return_value=socket_info
        ), mock.patch.object(
            container_io.os, "close"
        ):
            with self.assertRaisesRegex(RuntimeError, "regular file"):
                container_io._source_fd("socket.mov")

    def test_existing_target_symlink_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            staged = os.path.join(root, "staged.mov")
            output = os.path.join(root, "output.mov")
            Path(staged).write_bytes(b"media")
            os.symlink("/etc/hosts", output)
            with self.assertRaisesRegex(RuntimeError, "already exists"):
                container_io.promote_regular(staged, output)

    def test_media_digest_must_match_same_inode_that_is_promoted(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            staged = os.path.join(root, "staged.mov")
            output = os.path.join(root, "output.mov")
            Path(staged).write_bytes(b"swapped-after-proof")
            with self.assertRaisesRegex(RuntimeError, "media proof"):
                container_io.promote_regular(staged, output, "0" * 64)
            self.assertFalse(os.path.lexists(output))

    def test_replacement_size_is_rejected_before_payload_copy(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            staged = os.path.join(root, "staged.tar")
            output = os.path.join(root, "output.tar")
            with open(staged, "wb") as handle:
                handle.truncate(129 * 1024 * 1024)
            with mock.patch.object(
                container_io,
                "_copy_fd",
                side_effect=AssertionError("payload copy started"),
            ):
                with self.assertRaisesRegex(RuntimeError, "expected size"):
                    container_io.promote_regular(staged, output, "0" * 64, 1024)
            self.assertFalse(os.path.lexists(output))

    def test_snapshot_and_promotion_override_restrictive_umask(self) -> None:
        with tempfile.TemporaryDirectory() as root, tempfile.TemporaryDirectory() as stage:
            motion = _motion_tree(root)
            composition = container_io.CompositionInput(
                "compositions/card.html",
                (motion / "compositions" / "card.html").read_text(),
            )
            staged = os.path.join(stage, "staged.mov")
            output = os.path.join(stage, "output.mov")
            Path(staged).write_bytes(b"media")
            previous = os.umask(0o777)
            try:
                sealed = container_io.create_snapshot(root, composition, {}, stage)
                container_io.promote_regular(staged, output)
            finally:
                os.umask(previous)
            self.assertEqual(stat.S_IMODE(os.stat(sealed.path).st_mode), 0o400)
            self.assertEqual(stat.S_IMODE(os.stat(output).st_mode), 0o600)
            self.assertEqual(Path(output).read_bytes(), b"media")
