"""Original cold read deadline/callback/file boundaries, all faults TEST-owned.

Only the exact fixture allowlist may be rewritten. No dependency inventories,
current executables or media source bytes are fault targets.
"""
from __future__ import annotations

import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import patch

from _source_color_observation_read_fixture import ColdObservationFixture
import guided_source_color_observation_read as reader
import guided_source_color_observation_replay as replay


def _frames(fixture: ColdObservationFixture, mutate: object) -> None:
    """Rehash only exact TEST raw frames/worker refs to exercise the real full parser."""
    row = fixture.sections[0]
    path = Path(row["artifacts"]["frames"]["path"])
    raw = mutate(path.read_bytes())
    row["artifacts"]["frames"] = fixture.replace(path, raw)
    reference = row["artifacts"]["frames"]
    fixture.change_record("execution", lambda value: value["worker"]["decoder"].update(
        sha256=reference["sha256"], bytes=reference["sizeBytes"]))


class ColdObservationFaultTests(unittest.TestCase):
    """No first-callback baseline, final callback substitution or new cutoff may escape."""

    def setUp(self) -> None:
        """Use the same virtual original clock object for setup and every cold read."""
        self.now = [1000.0]
        timer = patch("time.monotonic", side_effect=lambda: self.now[0])
        timer.start()
        self.addCleanup(timer.stop)
        self.f = ColdObservationFixture()
        self.addCleanup(self.f.cleanup)
        self.f.guard.reset_mock()

    def test_first_callback_cannot_rebaseline_later_job_or_launch_intent(self) -> None:
        """Every job file is held before any caller callback, even before its own replay."""
        path = Path(self.f.sections[1]["artifacts"]["execution"]["path"]).parent / "launch-intent.json"
        self.f.guard.side_effect = lambda: self.f.replace(path)
        with self.assertRaisesRegex(RuntimeError, "metadata file"):
            self.f.read()
        self.assertEqual(self.f.guard.call_count, 1)

    def test_first_callback_cannot_replace_original_read_cutoff_or_guard(self) -> None:
        """Capture exact cutoff/callback identity before invoking it."""
        self.f.guard.side_effect = lambda: object.__setattr__(self.f.read_context, "deadline", 1400.0)
        with self.assertRaisesRegex(RuntimeError, "original context"):
            self.f.read()

    def test_first_callback_cannot_change_equal_valued_input_types(self) -> None:
        """Original numeric type identity is part of the supplied metadata lifetime."""
        self.f.guard.side_effect = lambda: self.f.inputs.value.update(schemaVersion=1.0)
        with self.assertRaisesRegex(RuntimeError, "original context"):
            self.f.read()

    def test_first_callback_cannot_replace_original_reference_objects(self) -> None:
        """Equal JSON copies cannot replace the caller's actual original reference records."""
        self.f.guard.side_effect = lambda: self.f.references.update(archive=deepcopy(self.f.references["archive"]))
        with self.assertRaisesRegex(RuntimeError, "original context"):
            self.f.read()

    def test_actual_pin_parser_return_is_held_before_later_callbacks(self) -> None:
        """Retain actual derived parser objects immediately, not only their input lock."""
        actual, returned = reader.pipeline_inventory, []
        def pins(inputs: object, value: dict) -> dict:
            """Use the real parser and expose its actual TEST return for one mutation."""
            result = actual(inputs, value)
            returned.append(result)
            return result
        self.f.guard.side_effect = lambda: returned[0].clear()
        with patch.object(reader, "pipeline_inventory", side_effect=pins), self.assertRaisesRegex(RuntimeError, "parsed metadata"):
            self.f.read()

    def test_final_callback_cannot_mutate_earlier_raw_metadata(self) -> None:
        """The last arbitrary callback is followed by the whole original finite file sweep."""
        armed, actual = [False], reader.deepcopy
        path = Path(self.f.sections[0]["artifacts"]["probe"]["path"])
        def copied(value: object) -> object:
            """Arm only after the actual final detached result is built."""
            result = actual(value)
            armed[0] = True
            return result
        self.f.guard.side_effect = lambda: self.f.replace(path) if armed[0] else None
        with patch.object(reader, "deepcopy", side_effect=copied), self.assertRaisesRegex(RuntimeError, "metadata file"):
            self.f.read()

    def test_final_callback_cannot_expire_original_clock(self) -> None:
        """No per-job phase cutoff is revived and no final bookkeeping time is refunded."""
        armed, actual = [False], reader.deepcopy
        def copied(value: object) -> object:
            """Retain actual final result and then arm the original deadline failure."""
            result = actual(value)
            armed[0] = True
            return result
        def guard() -> None:
            """Expire only the same original read clock at its last caller boundary."""
            if armed[0]:
                self.now[0] = 1300.0
        self.f.guard.side_effect = guard
        with patch.object(reader, "deepcopy", side_effect=copied), self.assertRaises(RuntimeError):
            self.f.read()

    def test_full_frame_replay_rejects_late_color_geometry_pts_and_truncation(self) -> None:
        """Late records are actually parsed, not replaced by header or sampled checks."""
        faults = [lambda raw: b"color_space=bt2020nc".join(raw.rsplit(b"color_space=bt709", 1)),
            lambda raw: b"chroma_location=center".join(raw.rsplit(b"chroma_location=left", 1)),
            lambda raw: b"sample_aspect_ratio=2:1".join(raw.rsplit(b"sample_aspect_ratio=1:1", 1)),
            lambda raw: b"pkt_pts=900024".join(raw.rsplit(b"pkt_pts=900023", 1)),
            lambda raw: raw[:-9]]
        for change in faults:
            f = ColdObservationFixture()
            self.addCleanup(f.cleanup)
            _frames(f, change)
            with self.subTest(change=change), self.assertRaises((ValueError, RuntimeError)):
                f.read()

    def test_original_cutoff_is_checked_inside_stream_without_new_guard_per_line(self) -> None:
        """The final line can consume the remaining original allowance and must reject."""
        actual = replay._lines
        def lines(path: Path, expected: dict) -> object:
            """Use actual bounded raw reader; only TEST clock passage is supplied."""
            for index, line in enumerate(actual(path, expected)):
                if index == 12:
                    self.now[0] = 1300.0
                yield line
        with patch.object(replay, "_lines", side_effect=lines), self.assertRaises(RuntimeError):
            self.f.read()

    def test_raw_hash_size_duplicate_json_and_file_aliases_reject(self) -> None:
        """No duplicate-key parser choice or same-byte hardlink baseline is accepted."""
        path = Path(self.f.sections[0]["artifacts"]["probe"]["path"])
        raw = path.read_bytes()
        self.f.replace(path, b'{"streams":[],"streams":[]}\n')
        with self.assertRaises(RuntimeError):
            self.f.read()
        self.f.replace(path, raw)
        alias = self.f.root / "TEST-hardlink"
        alias.hardlink_to(path)
        with self.assertRaisesRegex(RuntimeError, "single-link"):
            self.f.read()


if __name__ == "__main__":
    unittest.main()
