"""M11 (P0 Step 5.11): the four utility owners wait in the host pool's FIFO instead of failing on a busy slot.

Each builder's ``NativeRun`` settings come from ``native_owner_queue.queued_owner``, which is checked in the source.
Running the builders would need a real runtime build, hashing of local tool binaries and a Whisper model, and P0
tests touch none of those. ``queued_owner`` itself gives an owner that refused at once (no capacity wait) the pool's
bounded queue in its lane. Before M-028, src's four builders were the add8f82c files, which constructed a raw
``NativeRunConfig``. M-029 queues the review-bundle owner the same way; its merge keeps src's ``'audio'``
class for that ffmpeg-only work (the donor passed no class, so the default ``'heavy'`` would apply).
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import ast
import tempfile
import unittest
from pathlib import Path

from native_work_pool_policy import QUEUE_SECONDS
from studio.native_owner_queue import queued_owner
from studio.native_run_config import NativeRunConfig
from studio.native_runtime import digest

PRODUCER = Path(__file__).resolve().parents[1]
BUILDERS = {'edit/selected_sources.py': 'prepare', 'studio/native_review_recognition.py': 'execute',
            'studio/source_cache_alias.py': 'execute', 'studio/web_capture.py': 'execute'}


def owner_settings(path: Path, function: str) -> list[bool]:
    """For each ``NativeRun(label, settings)`` in the function: whether ``settings`` came from ``queued_owner``."""
    body = next(node for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.FunctionDef)
                and node.name == function)
    queued = {target.id for node in ast.walk(body) if isinstance(node, ast.Assign)
              and isinstance(node.value, ast.Call) and getattr(node.value.func, 'id', '') == 'queued_owner'
              for target in node.targets if isinstance(target, ast.Name)}
    return [isinstance(call.args[1], ast.Name) and call.args[1].id in queued for call in ast.walk(body)
            if isinstance(call, ast.Call) and getattr(call.func, 'id', '') == 'NativeRun' and len(call.args) >= 2]


class OwnerQueueTests(unittest.TestCase):
    """Utility owners queue for their lane; nothing refuses a busy slot at once."""

    def test_the_four_utility_owners_are_queued(self) -> None:
        """Every NativeRun of the four builders runs with queued settings."""
        for relative, function in BUILDERS.items():
            with self.subTest(builder=relative):
                found = owner_settings(PRODUCER / relative, function)
                self.assertTrue(found and all(found), f'{relative}:{function} builds a NativeRun without queued_owner')

    def test_the_review_bundle_owner_queues_in_the_audio_class(self) -> None:
        """M-029: the review-bundle owner is queued, and its ffmpeg-only work keeps the 'audio' class."""
        path = PRODUCER / 'studio/native_review_bundle.py'
        self.assertEqual(owner_settings(path, 'supervise'), [True])
        call = next(node for node in ast.walk(ast.parse(path.read_text())) if isinstance(node, ast.Call)
                    and getattr(node.func, 'id', '') == 'queued_owner')
        self.assertEqual([ast.literal_eval(argument) for argument in call.args[1:]], ['audio'])

    def test_a_refusing_owner_gains_the_bounded_queue_in_its_lane(self) -> None:
        """capacity_wait_seconds becomes the pool's queue allowance; the work deadline is kept on top of it."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name).resolve()
        cli, sandbox = root / 'cli.js', root / 'TEST.sb'
        cli.write_text('TEST cli')
        sandbox.write_text('TEST sandbox')
        (root / 'out').mkdir()
        admission = {'output': str(root / 'out/result.json'), 'sdkSha256': digest(cli),
                     'sandboxSha256': digest(sandbox)}
        settings = NativeRunConfig(root / 'project', root / 'out', cli, ['TEST'], {}, admission, sandbox=sandbox,
                                   deadline=300, lane='audio')
        queued = queued_owner(settings)
        self.assertEqual((queued.capacity_wait_seconds, queued.deadline, queued.queue_work_seconds, queued.lane),
                         (QUEUE_SECONDS, 300 + QUEUE_SECONDS, 300, 'audio'))
        self.assertGreater(queued.capacity_wait_seconds, 0)


if __name__ == '__main__':
    unittest.main()
