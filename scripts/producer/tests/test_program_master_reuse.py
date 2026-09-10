"""Pure control-flow regressions for retained program-master reuse (no media).

Cancellation must propagate before any rebuild; only a held render-graph
selection may authorize reuse; a genuinely stale receipt rebuilds exactly once.
"""
from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from audio import program_master_reuse as reuse
from color.deadline import WallBudgetExceeded
from headless.process_runner import ProcessDeadlineError
from palmier.mcp_client import PalmierError

POINTER = {"schemaVersion": 2, "kind": "ordinary-program-audio-pointer", "audioClockPolicy": "source-float-v2",
           "programMasterReceiptPath": "/TEST/master-receipt.json", "programMasterReceiptHash": "a" * 64}


def _quiet():
    return patch("assemble.emit", lambda **fields: None)


class ProgramMasterReuseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="sniper-reuse-", dir="/private/tmp")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        (self.root / reuse.PROGRAM_AUDIO_POINTER).write_text(json.dumps(POINTER))
        self.job = SimpleNamespace(out=str(self.root / "final.mp4"), plan={})

    def _held(self, value: str = "a" * 64):
        return patch.object(reuse, "held_program_selection", return_value=(value, {"/TEST/graph.json": "g" * 64}))

    def test_terminal_cancellation_propagates_before_any_rebuild(self) -> None:
        errors = (WallBudgetExceeded("TEST wall"), ProcessDeadlineError("TEST child"), TimeoutError("TEST"),
                  PalmierError("TEST Deadline.remaining expired"), subprocess.TimeoutExpired(["TEST"], 1))
        for error in errors:
            build = unittest.mock.Mock()
            with self.subTest(error=type(error).__name__), self._held(), _quiet(), \
                    patch.object(reuse, "load_program_master", side_effect=error):
                with self.assertRaises(type(error)) as caught:
                    reuse.select_program_master(self.job, object(), None, build)
                self.assertIs(caught.exception, error)
            build.assert_not_called()

    def test_stale_or_invalid_receipt_rebuilds_exactly_once(self) -> None:
        for error in (RuntimeError("full-program master finishing settings changed"),
                      ValueError("TEST malformed"), OSError("TEST unreadable")):
            build = unittest.mock.Mock(return_value="TEST-master")
            with self.subTest(error=error), self._held(), _quiet(), \
                    patch.object(reuse, "load_program_master", side_effect=error):
                master, reused, files = reuse.select_program_master(self.job, object(), None, build)
            self.assertEqual((master, reused, files), ("TEST-master", False, {}))
            build.assert_called_once()

    def test_without_held_graph_selection_the_pointer_is_never_authority(self) -> None:
        build = unittest.mock.Mock(return_value="TEST-master")
        with patch.object(reuse, "held_program_selection", return_value=None), _quiet(), \
                patch.object(reuse, "load_program_master") as load:
            master, reused, _files = reuse.select_program_master(self.job, object(), None, build)
        load.assert_not_called()
        self.assertEqual((master, reused), ("TEST-master", False))
        build.assert_called_once()

    def test_pointer_differing_from_held_selection_is_declined_without_loading(self) -> None:
        build = unittest.mock.Mock(return_value="TEST-master")
        with self._held("b" * 64), _quiet(), patch.object(reuse, "load_program_master") as load:
            master, reused, _files = reuse.select_program_master(self.job, object(), None, build)
        load.assert_not_called()
        self.assertEqual((master, reused), ("TEST-master", False))

    def test_held_and_proved_master_is_reused_with_its_graph_files_held(self) -> None:
        build = unittest.mock.Mock()
        with self._held(), _quiet(), patch.object(reuse, "load_program_master", return_value=SimpleNamespace(
                receipt={"receiptHash": "a" * 64})) as load:
            master, reused, files = reuse.select_program_master(self.job, object(), None, build)
        self.assertEqual(load.call_args.args[2], ("/TEST/master-receipt.json", "a" * 64))
        self.assertTrue(reused)
        self.assertEqual(master.receipt["receiptHash"], "a" * 64)
        self.assertIn("/TEST/graph.json", files)
        self.assertIn(str(self.root / reuse.PROGRAM_AUDIO_POINTER), files)
        build.assert_not_called()

    def test_held_preparation_wins_without_any_pointer_read(self) -> None:
        build = unittest.mock.Mock()
        preparation = SimpleNamespace(selection=SimpleNamespace(master="HELD"))
        with _quiet(), patch.object(reuse, "held_program_selection") as held:
            self.assertEqual(reuse.select_program_master(self.job, object(), preparation, build), ("HELD", False, {}))
        held.assert_not_called()
        build.assert_not_called()

    def test_malformed_pointer_declines_before_graph_or_loader(self) -> None:
        for pointer in ({"schemaVersion": 1}, {**POINTER, "programMasterReceiptHash": 5}):
            (self.root / reuse.PROGRAM_AUDIO_POINTER).write_text(json.dumps(pointer))
            build = unittest.mock.Mock(return_value="TEST-master")
            with self.subTest(pointer=pointer), _quiet(), patch.object(reuse, "held_program_selection") as held, \
                    patch.object(reuse, "load_program_master") as load:
                reuse.select_program_master(self.job, object(), None, build)
            held.assert_not_called()
            load.assert_not_called()
            build.assert_called_once()


if __name__ == "__main__":
    unittest.main(verbosity=2)
