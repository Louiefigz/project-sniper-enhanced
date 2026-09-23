"""SDK ABI/identity unit checks; no unknown live process is silently omitted."""
from __future__ import annotations

import ctypes as c
import errno
import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from native_render_process_table import BsdInfo, process_row, child_pids, identity_table, MAX_PROCESSES
from native_render_processes import ProcessIdentity, ProcessRequest, ResourceMeasurementError, process_selection


class DirectIdentityTests(unittest.TestCase):
    """Kernel exit evidence and errors have deliberately different outcomes."""

    def library(self, *, error=0, size=None, zombie=False):
        def read(pid, _flavor, _arg, pointer, _size):
            value = c.cast(pointer, c.POINTER(BsdInfo)).contents
            value.pid, value.ppid, value.pgid = pid, 100, 100
            value.start_seconds, value.status = 1790115652, 5 if zombie else 2
            c.set_errno(error)
            return c.sizeof(BsdInfo) if size is None else size
        return SimpleNamespace(proc_pidinfo=read)

    def test_compiled_sdk_layout_matches_checked_offsets(self):
        self.assertEqual((c.sizeof(BsdInfo), BsdInfo.pgid.offset, BsdInfo.start_seconds.offset), (136, 100, 120))

    def test_confirmed_exit_is_distinct_from_permission_denied(self):
        self.assertIsNone(process_row(self.library(error=errno.ESRCH, size=0), 101))
        self.assertIsNone(process_row(self.library(zombie=True), 101))
        with self.assertRaises(ResourceMeasurementError):
            process_row(self.library(error=errno.EPERM, size=0), 101)
        with self.assertRaises(ResourceMeasurementError):
            process_row(self.library(size=12), 101)

    def test_child_api_returns_pid_count_not_byte_count(self):
        def children(_pid, buffer, _bytes):
            buffer[0], buffer[1], buffer[2] = 101, 102, 103
            return 3
        self.assertEqual(child_pids(SimpleNamespace(proc_listchildpids=children), 100), [101, 102, 103])

    def test_full_child_buffer_and_permission_error_fail_closed(self):
        with self.assertRaises(ResourceMeasurementError):
            child_pids(SimpleNamespace(proc_listchildpids=lambda *_: MAX_PROCESSES + 1), 100)
        def denied(*_args):
            c.set_errno(errno.EPERM)
            return 0
        with self.assertRaises(ResourceMeasurementError):
            child_pids(SimpleNamespace(proc_listchildpids=denied), 100)

    def test_remembered_orphans_remain_owned_and_unrelated_processes_do_not(self):
        root = ProcessIdentity(100, 'START', 100)
        orphan = ProcessIdentity(200, 'ORPHAN', 200)
        rows = {100: (1, 100, 'START'), 101: (100, 100, 'CHILD'),
                200: (1, 200, 'ORPHAN'), 999: (1, 999, 'HELPER')}
        request = ProcessRequest(root, (orphan,))
        with patch('native_render_process_table.process_bindings', return_value=Mock()), \
             patch('native_render_process_table.process_row', side_effect=lambda _lib, pid: rows.get(pid)), \
             patch('native_render_process_table.child_pids', side_effect=lambda _lib, pid: [101] if pid == 100 else []), \
             patch('native_render_process_table.os.getpid', return_value=999):
            result = process_selection(identity_table(request), request)
        self.assertEqual(result['owned'], {100, 101, 200})

    def test_reused_root_never_authorizes_descendant_discovery(self):
        with patch('native_render_process_table.process_bindings', return_value=Mock()), \
             patch('native_render_process_table.process_row', return_value=(1, 100, 'NEW')), \
             patch('native_render_process_table.child_pids') as children, \
             patch('native_render_process_table.os.getpid', return_value=999):
            result = process_selection(identity_table(ProcessRequest(ProcessIdentity(100, 'OLD', 100))),
                                       ProcessRequest(ProcessIdentity(100, 'OLD', 100)))
        children.assert_not_called()
        self.assertFalse(result['verified'])
        self.assertEqual(result['owned'], set())
