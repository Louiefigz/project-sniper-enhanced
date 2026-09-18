"""Real harmless descendant cleanup and fail-closed process inspection tests."""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from unittest import mock

from studio import managed_preview_state as state
from studio.studio_server import StudioServerError


class PreviewTreeTests(unittest.TestCase):
    """No browser or media is launched; fixture children only sleep."""

    def test_inspection_permission_error_is_not_process_absence(self) -> None:
        """Empty stdout alone cannot turn denied ps into verified cleanup."""
        denied = mock.Mock(returncode=1, stdout='', stderr='Operation not permitted')
        with mock.patch.object(state.subprocess, 'run', return_value=denied):
            with self.assertRaisesRegex(StudioServerError, 'Cannot inspect'):
                state.process_identity(24500)

    def test_real_detached_child_is_removed_after_parent_already_exited(self) -> None:
        """Remember ancestry before exit; clean the separate process group after."""
        child_code = 'import time; time.sleep(40)'
        parent_code = ('import subprocess,sys,time; '
                       'p=subprocess.Popen([sys.executable,"-c",sys.argv[1]],start_new_session=True); '
                       'print(p.pid,flush=True); time.sleep(40)')
        parent = subprocess.Popen([sys.executable, '-u', '-c', parent_code, child_code],
                                  stdout=subprocess.PIPE, text=True, start_new_session=True)
        child_pid = int(parent.stdout.readline())
        known = None
        try:
            identity = state.process_identity(parent.pid)
            known = state.snapshot_owned({'identity': identity})
            self.assertIn(child_pid, [row['pid'] for row in known['processes']])
            child = next(row for row in known['processes'] if row['pid'] == child_pid)
            self.assertEqual(child['pgid'], child_pid)
            self.assertNotEqual(child['pgid'], identity['pgid'])
            parent.terminate()
            parent.wait(timeout=3)
            self.assertIn(child_pid, [row['pid'] for row in state.live_owned(known)])
            result = state.terminate_tree(known)
            self.assertTrue(result['verified'], result)
            self.assertEqual(state.live_owned(known), [])
        finally:
            if parent.poll() is None:
                parent.kill()
                parent.wait(timeout=3)
            if known is not None:
                state.terminate_tree(known)
            parent.stdout.close()


if __name__ == '__main__':
    unittest.main()
