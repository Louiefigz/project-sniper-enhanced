"""Synthetic supplied ffprobe text, not actual decoded-source qualification."""
from __future__ import annotations

import unittest

from _grade_contract_fixture import binding, declaration, frame, stream
from color.grade_frame_adapter import frame_records, normalized_frame, validate_records


def raw_frame(index: int, source: dict) -> dict:
    """Use explicit supplied decoder-shaped fields for deterministic unit checks."""
    row = frame(index, stream(source))
    return {"media_type": "video", "stream_index": 0, "pkt_pts": row["pts"],
        "best_effort_timestamp": row["pts"], "pkt_duration": row["durationTicks"],
        "width": 1920, "height": 1080, "pix_fmt": "yuv420p", "interlaced_frame": 0,
        "repeat_pict": 0, "color_range": "tv", "color_space": "bt709",
        "color_primaries": "bt709", "color_transfer": "bt709"}


def text_frame(row: dict) -> list[str]:
    """Serialize a test record in the pinned default-wrapper shape."""
    return ["[FRAME]\n", *[f"{key}={value}\n" for key, value in row.items()], "[/FRAME]\n"]


def observed_probe(source: dict) -> dict:
    """Provide exact rational tags, with first PTS independent of frame index."""
    first = raw_frame(0, source)
    return {"streams": [{**first, "codec_type": "video", "index": 0,
        "avg_frame_rate": source["fps"], "r_frame_rate": source["fps"],
        "start_pts": first["pkt_pts"], "time_base": stream(source)["timeBase"],
        "nb_frames": str(source["frameCount"])}]}


def decoder_terminal(count: int) -> dict:
    """Supplied terminal assertions only; never an actual worker receipt."""
    return {"reachedEof": True, "exitCode": 0, "signal": None, "stderr": "",
        "stderrBytes": 0, "frames": count, "perFrameCorruptFlag": "unavailable",
        "perFrameDecodeErrorFlags": "unavailable"}


class GradeFrameAdapterTests(unittest.TestCase):
    """Do not turn missing decoder metadata into guessed source class facts."""

    def test_complete_nonzero_origin_record_stream_keeps_flags_unavailable(self) -> None:
        context = declaration(3)
        source = binding(context)
        lines = (line for index in range(3) for line in text_frame(raw_frame(index, source)))
        result = validate_records((source, context, observed_probe(source)), lines, decoder_terminal(3))
        self.assertEqual(result.decoded_record_count, 3)
        self.assertFalse(result.decoder_execution_proved)
        self.assertFalse(result.decoded_frame_flags_available)
        self.assertEqual(result.validator_policy, "sniper-private-grade-frame-records-v2")
        self.assertIsNone(normalized_frame(raw_frame(0, source), 0)["corrupt"])

    def test_all_pts_duration_and_class_fields_are_required(self) -> None:
        for field in ("pkt_pts", "best_effort_timestamp", "pkt_duration", "color_range", "pix_fmt"):
            context = declaration(1)
            source = binding(context)
            row = raw_frame(0, source)
            del row[field]
            with self.subTest(field=field), self.assertRaises(ValueError):
                validate_records((source, context, observed_probe(source)), text_frame(row), decoder_terminal(1))

    def test_late_color_change_after_fifty_seconds_rejects(self) -> None:
        context = declaration(1802)
        source = binding(context)
        def lines():
            for index in range(source["frameCount"]):
                row = raw_frame(index, source)
                if index == 1801:
                    row["color_transfer"] = "smpte2084"
                yield from text_frame(row)
        with self.assertRaisesRegex(ValueError, "color metadata"):
            validate_records((source, context, observed_probe(source)), lines(), decoder_terminal(1802))

    def test_unknown_duplicate_nesting_truncation_and_extra_records_block(self) -> None:
        source = binding(declaration(1))
        valid = text_frame(raw_frame(0, source))
        variants = [valid[:-1], valid[:1] + ["foo=bar\n"] + valid[1:],
            valid[:1] + ["pkt_pts=3\n"] + valid[1:], ["\n"] + valid,
            ["[FRAME]\n"] + valid, ["a" * 32769 + "\n"]]
        for lines in variants:
            with self.assertRaises(ValueError):
                list(frame_records(lines))
        with self.assertRaises(ValueError):
            validate_records((source, declaration(1), observed_probe(source)), valid * 2, decoder_terminal(1))

    def test_only_known_inert_sei_side_record_is_supported(self) -> None:
        source = binding(declaration(1))
        valid = text_frame(raw_frame(0, source))
        for kind in ("Mastering display metadata", "Unknown new side metadata"):
            lines = valid[:-1] + ["[SIDE_DATA]\n", f"side_data_type={kind}\n", "[/SIDE_DATA]\n"] + valid[-1:]
            with self.assertRaisesRegex(ValueError, "side metadata"):
                validate_records((source, declaration(1), observed_probe(source)), lines, decoder_terminal(1))

    def test_warning_error_boolean_and_incomplete_terminal_never_qualify(self) -> None:
        source = binding(declaration(1))
        for key, value in (("stderr", "concealing decoder warning"), ("stderrBytes", 1),
                           ("reachedEof", False), ("exitCode", False), ("frames", True),
                           ("perFrameCorruptFlag", False)):
            terminal = decoder_terminal(1)
            terminal[key] = value
            with self.subTest(key=key), self.assertRaises(ValueError):
                validate_records((source, declaration(1), observed_probe(source)),
                                 text_frame(raw_frame(0, source)), terminal)


if __name__ == "__main__":
    unittest.main()
