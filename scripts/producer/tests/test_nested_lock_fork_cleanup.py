"""Inherited cross/inner generators cannot close child FD replacements."""

from __future__ import annotations

import os
import unittest

from _common import pl  # noqa: F401
from _cross_ledger_order_fixture import CrossLedgerOrderFixture
from headless.cross_ledger_order_lock import (
    CrossLedgerOrderLockError,
    locked_cross_ledger_order_root_v1,
)
from headless.operation_admission_lock import (
    OperationAdmissionWriterLockError,
    locked_operation_admission_writer_v3,
)


def _reuse_then_unwind(
    context: object,
    target_fd: int,
    expected_error: type[BaseException],
    output_fd: int,
) -> None:
    source_fd = os.open("/dev/null", os.O_RDONLY)
    if source_fd != target_fd:
        os.dup2(source_fd, target_fd)
        os.close(source_fd)
    try:
        getattr(context, "__exit__")(None, None, None)
    except expected_error:
        outcome = "lock-error"
    except BaseException:
        outcome = "wrong-error"
    else:
        outcome = "no-error"
    try:
        os.fstat(target_fd)
    except OSError:
        state = "replacement-closed"
    else:
        state = "replacement-open"
    os.write(output_fd, f"{outcome}/{state}".encode("ascii"))
    os._exit(0)


def _child_unwind_result(
    context: object, target_fd: int, expected_error: type[BaseException]
) -> str:
    read_fd, write_fd = os.pipe()
    child_pid = os.fork()
    if child_pid == 0:
        os.close(read_fd)
        _reuse_then_unwind(context, target_fd, expected_error, write_fd)
    os.close(write_fd)
    raw = os.read(read_fd, 128)
    os.close(read_fd)
    _pid, status = os.waitpid(child_pid, 0)
    if status != 0:
        raise AssertionError(f"fork child failed: {status}")
    return raw.decode("ascii")


@unittest.skipUnless(hasattr(os, "fork"), "fork is required")
class NestedLockForkCleanupTests(unittest.TestCase):
    def setUp(self) -> None:
        self.fixture = CrossLedgerOrderFixture()
        request = self.fixture.request().admission
        self.authority_id = request.admission.authority_id

    def tearDown(self) -> None:
        self.fixture.close()

    def test_cross_inherited_finally_preserves_child_replacement(self) -> None:
        context = locked_cross_ledger_order_root_v1(self.fixture.root)
        lock = context.__enter__()
        try:
            result = _child_unwind_result(
                context, lock.lock_fd, CrossLedgerOrderLockError
            )
        finally:
            context.__exit__(None, None, None)
        self.assertEqual(result, "lock-error/replacement-open")

    def test_inner_inherited_finally_preserves_child_replacement(self) -> None:
        with locked_cross_ledger_order_root_v1(self.fixture.root) as outer:
            context = locked_operation_admission_writer_v3(
                self.fixture.root, self.authority_id, outer
            )
            writer = context.__enter__()
            try:
                result = _child_unwind_result(
                    context,
                    writer.lock_fd,
                    OperationAdmissionWriterLockError,
                )
            finally:
                context.__exit__(None, None, None)
        self.assertEqual(result, "lock-error/replacement-open")


if __name__ == "__main__":
    unittest.main(verbosity=2)
