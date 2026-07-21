from __future__ import annotations

import os
import unittest
from unittest import mock

from _common import pl  # noqa: F401
from _generation_sealer_fixture import SealerFixture
import headless.generation_sealer_final as final_module
import headless.generation_sealer_source as source_module
from headless.generation_sealer import seal_generation
from headless.generation_sealer_types import GenerationSealError


class GenerationSealerNonregularTests(unittest.TestCase):
    def test_staging_fifo_is_rejected_before_any_open_attempt(self) -> None:
        fixture = SealerFixture()
        target = fixture.staging / "media/final.mp4"
        target.unlink()
        os.mkfifo(target, 0o600)
        original = source_module._open_at
        try:
            with mock.patch.object(
                source_module, "_open_at", wraps=original
            ) as opened:
                with self.assertRaises(GenerationSealError):
                    seal_generation(fixture.request())
            opened_names = [call.args[1] for call in opened.call_args_list]
            self.assertNotIn("final.mp4", opened_names)
            self.assertFalse(fixture.pending().exists())
        finally:
            fixture.close()

    def test_colliding_fifo_commit_is_rejected_before_open(self) -> None:
        fixture = SealerFixture()
        try:
            seal_generation(fixture.request())
            final = fixture.final()
            commit = final / "commit.json"
            final.chmod(0o700)
            commit.unlink()
            os.mkfifo(commit, 0o400)
            final.chmod(0o500)
            original = final_module._open_at
            with mock.patch.object(
                final_module, "_open_at", wraps=original
            ) as opened:
                with self.assertRaises(GenerationSealError):
                    seal_generation(fixture.request())
            opened_names = [call.args[1] for call in opened.call_args_list]
            self.assertNotIn("commit.json", opened_names)
        finally:
            fixture.close()


if __name__ == "__main__":
    unittest.main()
