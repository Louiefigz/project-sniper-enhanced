from __future__ import annotations

import ctypes
import errno
import fcntl
import os
import stat
import unittest
from unittest import mock

from _common import pl  # noqa: F401
from _generation_sealer_fixture import SealerFixture, write
import headless.generation_sealer as sealer_module
import headless.generation_sealer_cleanup as cleanup_module
import headless.generation_sealer_final as final_module
import headless.generation_sealer_source as source_module
from headless.generation_reader_fs import _Pinned, _Policy
from headless.generation_sealer import seal_generation
from headless.generation_sealer_types import GenerationSealError


class _FakeRename:
    def __init__(self, error: int) -> None:
        self.error = error
        self.calls = 0

    def __call__(self, *_args: object) -> int:
        self.calls += 1
        ctypes.set_errno(self.error)
        return 0 if self.error == 0 else -1


class _FakeLib:
    pass


class GenerationSealerDefensiveTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = SealerFixture()

    def tearDown(self) -> None:
        self.fixture.close()

    def test_json_depth_and_structure_are_bounded_before_decode(self) -> None:
        deep = b"[" * 9 + b"0" + b"]" * 9
        wide = b"[" + b"0," * 65_537 + b"0]"
        for raw in (deep, wide):
            with self.subTest(size=len(raw)), mock.patch.object(
                sealer_module,
                "parse_generation_commit",
                side_effect=AssertionError("decoder must not run"),
            ):
                with self.assertRaisesRegex(
                    GenerationSealError, "parser limits"
                ):
                    seal_generation(self.fixture.request(raw))
        self.assertEqual(tuple(self.fixture.authority.iterdir()), ())

    def test_replaced_lock_inode_is_rejected_immediately(self) -> None:
        lock = self.fixture.authority / ".generation-seal.lock"
        real_flock = sealer_module.fcntl.flock
        replaced = []

        def replace_after_acquire(fd: int, operation: int) -> None:
            real_flock(fd, operation)
            if operation != fcntl.LOCK_EX or not lock.exists() or replaced:
                return
            lock.unlink()
            write(lock, b"", 0o600)
            replaced.append(True)

        with mock.patch.object(
            sealer_module.fcntl, "flock", side_effect=replace_after_acquire
        ):
            with self.assertRaises(GenerationSealError):
                seal_generation(self.fixture.request())
        self.assertTrue(replaced)
        self.assertFalse((self.fixture.authority / "generations").exists())

    def test_cleanup_prechecks_fifo_before_leaf_open(self) -> None:
        fixture = SealerFixture()
        try:
            self._leave_mutable_residue(fixture)
            target = fixture.pending() / "media/final.mp4"
            target.unlink()
            os.mkfifo(target, 0o600)
            real_open = cleanup_module.os.open
            with mock.patch.object(
                cleanup_module.os, "open", wraps=real_open
            ) as opened:
                with self.assertRaises(GenerationSealError):
                    seal_generation(fixture.request())
            opened_names = [call.args[0] for call in opened.call_args_list]
            self.assertNotIn("final.mp4", opened_names)
            self.assertTrue(target.exists())
        finally:
            fixture.close()

    def test_cleanup_prechecks_devices_and_socket_before_open(self) -> None:
        parent = _Pinned(9, None, "pending", ())
        context = cleanup_module._CleanupContext(
            _Policy(7, os.geteuid()), parent
        )
        for node_type in (stat.S_IFCHR, stat.S_IFBLK, stat.S_IFSOCK):
            info = mock.Mock(st_mode=node_type | 0o600)
            with self.subTest(node_type=node_type), mock.patch.object(
                cleanup_module.os, "stat", return_value=info
            ), mock.patch.object(cleanup_module.os, "open") as opened:
                with self.assertRaises(GenerationSealError):
                    cleanup_module._cleanup_open(
                        parent, "unsafe", False, context
                    )
                opened.assert_not_called()

    @staticmethod
    def _leave_mutable_residue(fixture: SealerFixture) -> None:
        def crash(label: str) -> None:
            if label == "payload-copied":
                raise KeyboardInterrupt(label)

        with mock.patch.object(sealer_module, "_checkpoint", crash):
            with unittest.TestCase().assertRaises(KeyboardInterrupt):
                seal_generation(fixture.request())

    def test_unsupported_noreplace_variant_falls_through(self) -> None:
        first, second = _FakeRename(errno.ENOSYS), _FakeRename(0)
        library = _FakeLib()
        library.renameatx_np = first
        library.renameat2 = second
        pinned = _Pinned(11, None, "generations", ())
        with mock.patch.object(
            final_module.ctypes, "CDLL", return_value=library
        ):
            final_module._rename_noreplace(pinned, "pending", "final")
        self.assertEqual((first.calls, second.calls), (1, 1))

    def test_all_unsupported_noreplace_variants_fail_closed(self) -> None:
        library = _FakeLib()
        library.renameatx_np = _FakeRename(errno.ENOTSUP)
        pinned = _Pinned(11, None, "generations", ())
        with mock.patch.object(
            final_module.ctypes, "CDLL", return_value=library
        ):
            with self.assertRaisesRegex(GenerationSealError, "unavailable"):
                final_module._rename_noreplace(pinned, "pending", "final")

    def test_enospc_is_normalized_and_owned_residue_is_removed(self) -> None:
        failure = OSError(errno.ENOSPC, os.strerror(errno.ENOSPC))
        with mock.patch.object(
            source_module, "_write_chunk", side_effect=failure
        ):
            with self.assertRaisesRegex(GenerationSealError, "safely sealed"):
                seal_generation(self.fixture.request())
        self.assertFalse(self.fixture.pending().exists())
        self.assertFalse(self.fixture.final().exists())

    def test_existing_publication_state_is_byte_for_byte_untouched(
        self,
    ) -> None:
        seal_generation(self.fixture.request())
        sentinels = {
            "CURRENT": b"opaque-current",
            ".publish.mutex": b"opaque-publish-lock",
            "FENCE": b"opaque-fence",
        }
        for name, raw in sentinels.items():
            write(self.fixture.authority / name, raw, 0o600)
        before = {name: self._file_observation(name) for name in sentinels}
        self.assertTrue(seal_generation(self.fixture.request()).replayed)
        after = {name: self._file_observation(name) for name in sentinels}
        self.assertEqual(after, before)

    def _file_observation(self, name: str) -> tuple[bytes, int, int, int]:
        path = self.fixture.authority / name
        info = path.stat()
        return (path.read_bytes(), info.st_ino, info.st_mode, info.st_mtime_ns)


if __name__ == "__main__":
    unittest.main()
