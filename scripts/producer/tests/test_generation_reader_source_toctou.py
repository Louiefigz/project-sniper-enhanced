"""Late source-tree mutation attacks against the generation reader."""

from __future__ import annotations

import unittest
from unittest import mock

from _common import pl  # noqa: F401
from _generation_reader_fixture import Fixture, write
from headless.generation_reader import GenerationReadError, read_current_generation
import headless.generation_reader as reader_module


def _mutate_prior_file(fixture: Fixture) -> None:
    target = fixture.generation / "artifacts/admission-inputs-v1-0.bin"
    raw = bytearray(target.read_bytes())
    raw[0] = (raw[0] + 1) % 256
    target.chmod(0o600)
    write(target, bytes(raw), 0o400)


def _add_prior_nested_entry(fixture: Fixture) -> None:
    directory = fixture.generation / "artifacts"
    directory.chmod(0o700)
    write(directory / "late-extra.bin", b"extra", 0o400)
    directory.chmod(0o500)


_ATTACKS = {
    "prior-file": (2, _mutate_prior_file),
    "prior-nested-entry": (40, _add_prior_nested_entry),
}


class GenerationReaderSourceToctouTests(unittest.TestCase):
    def _assert_source_attack_rejects(self, attack_name: str) -> None:
        fixture = Fixture()
        original, copied = reader_module._stream, []
        trigger, attack = _ATTACKS[attack_name]

        def attacking_stream(
            source_fd: int, destination_fd: int | None
        ) -> tuple[int, str]:
            observed = original(source_fd, destination_fd)
            if destination_fd is not None:
                copied.append(True)
                if len(copied) == trigger:
                    attack(fixture)
            return observed

        try:
            stream_patch = mock.patch.object(reader_module, "_stream", attacking_stream)
            with stream_patch, self.assertRaises(GenerationReadError):
                with read_current_generation(
                    str(fixture.authority), str(fixture.destination)
                ):
                    self.fail("late source-tree mutation unexpectedly resolved")
            self.assertGreaterEqual(len(copied), trigger)
        finally:
            fixture.close()

    def test_prior_source_subtree_cannot_change_during_later_copy(self) -> None:
        for attack_name in _ATTACKS:
            with self.subTest(attack=attack_name):
                self._assert_source_attack_rejects(attack_name)


if __name__ == "__main__":
    unittest.main(verbosity=2)
