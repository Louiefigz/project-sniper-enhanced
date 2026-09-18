"""Fault and verdict contracts; actual decoded-media parity lives in test_audit_glitch_media."""
from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from audit.audit_checks import FAIL, PASS, WARN
from audit.audit_glitch import check_glitch_screens, detect_black, detect_flash, detect_freeze
from audit.audit_glitch_scan import (MAX_LUMA_FRAMES, SCAN_BASE_S, SCAN_PER_MEDIA_SECOND,
                                     SCAN_UNKNOWN_DURATION_BUDGET_S, GlitchScan, GlitchScanError,
                                     filter_escape, scan_budget_s, scan_glitch_filter, scan_luma,
                                     scan_luma_frames)

PROGRESS = "frame=3\nout_time_us=100000\nprogress=end\n"


def completed(stdout: str = PROGRESS, stderr: str = "", code: int = 0) -> subprocess.CompletedProcess:
    """TEST process output only, never actual media execution provenance."""
    return subprocess.CompletedProcess(["TEST ffmpeg"], code, stdout, stderr)


def luma_rows(values: tuple[int, ...]) -> str:
    """TEST regular three-frame clock in the exact metadata print format."""
    return "".join(f"frame:{index} pts:{index} pts_time:{index / 30:.6f}\n"
                   f"lavfi.signalstats.YAVG={value}\n" for index, value in enumerate(values))


def freeze_log(*events: tuple[str, float]) -> str:
    """TEST freezedetect lines in FFmpeg's av_log shape."""
    return "".join(f"[freezedetect @ 0xTEST] lavfi.freezedetect.freeze_{kind}: {value}\n"
                   for kind, value in events)


def black_log(*spans: tuple[float, float]) -> str:
    return "".join(f"[blackdetect @ 0xTEST] black_start:{start} black_end:{end} black_duration:{end - start}\n"
                   for start, end in spans)


def scan_run(*, stdout: str = PROGRESS, stderr: str = "", code: int = 0):
    return patch("audit.audit_glitch_scan.run_scan_process", return_value=completed(stdout, stderr, code))


def luma_run(metadata: str, stdout: str = PROGRESS):
    """Patch the scan so the private sink receives ``metadata`` and progress reports ``stdout``."""
    def fake_run(command, _budget):
        sink = next(arg for arg in command if arg.startswith("signalstats,")).split("file=", 1)[1]
        with open(sink.replace("\\", ""), "w", encoding="utf8") as handle:
            handle.write(metadata)
        return completed(stdout)
    return patch("audit.audit_glitch_scan.run_scan_process", side_effect=fake_run)


class GlitchScanFaultTests(unittest.TestCase):
    """Missing measurements must never create clean-video PASS rows."""

    def test_nonzero_empty_and_partial_output_fail_all_detectors(self) -> None:
        for output in ("", PROGRESS):
            with self.subTest(output=bool(output)), scan_run(stdout=output, code=1):
                rows = check_glitch_screens("TEST.mp4", 3)
            self.assertEqual([row.status for row in rows], [FAIL, FAIL, FAIL])
            self.assertTrue(all(row.measured == "unmeasured" for row in rows))

    def test_missing_zero_or_conflicting_decode_completion_is_rejected(self) -> None:
        outputs = ("", "frame=0\nout_time_us=1\nprogress=end\n", "frame=3\nout_time_us=1\nprogress=continue\n",
                   "out_time_us=1\nprogress=end\n", "frame=4\nprogress=continue\nframe=3\nout_time_us=1\nprogress=end\n",
                   "frame=3\nout_time_us=1\nprogress=end\nprogress=end\n", "frame=3\nframe=4\nout_time_us=1\nprogress=end\n",
                   "frame=3\nout_time_us=1\nprogress=unknown\n", "frame=3\nout_time_us=1\nprogress=end\nframe=4\n",
                   "frame=3\nprogress=end\n", "frame=3\nout_time_us=0\nprogress=end\n")
        for output in outputs:
            with self.subTest(output=output), scan_run(stdout=output):
                self.assertEqual(detect_black("TEST.mp4", 0.1).status, FAIL)

    def test_decoded_length_must_match_the_audited_duration(self) -> None:
        with scan_run(stdout="frame=30\nout_time_us=1000000\nprogress=end\n"):
            self.assertEqual(detect_black("TEST.mp4", 4.0).status, FAIL)
            self.assertEqual(detect_freeze("TEST.mp4", None, 4.0).status, FAIL)
            self.assertEqual(detect_black("TEST.mp4", 1.2).status, PASS)
            self.assertEqual(detect_freeze("TEST.mp4").status, PASS)

    def test_scan_budget_scales_with_media_length_and_respects_run_deadline(self) -> None:
        self.assertEqual(scan_budget_s(600), SCAN_BASE_S + 600 * SCAN_PER_MEDIA_SECOND)
        for unknown in (None, 0, -1, float("nan"), float("inf")):
            self.assertEqual(scan_budget_s(unknown), SCAN_UNKNOWN_DURATION_BUDGET_S)
        hour = "frame=108000\nout_time_us=3600000000\nprogress=end\n"
        with patch("audit.audit_glitch_scan.subprocess.run", return_value=completed(hour)) as run, \
                patch("audit.audit_glitch_scan.process_timeout", side_effect=lambda budget: min(budget, 7.5)) as clock:
            scan_glitch_filter("TEST.mp4", "null", 3600)
        self.assertEqual(clock.call_args.args[0], scan_budget_s(3600))
        self.assertEqual(run.call_args.kwargs["timeout"], 7.5)

    def test_timeout_os_and_unicode_errors_become_unmeasured_rows(self) -> None:
        errors = (subprocess.TimeoutExpired("TEST", 1), OSError("TEST missing executable"), UnicodeError("TEST bad logs"))
        for error in errors:
            with self.subTest(error=error), patch("audit.audit_glitch_scan.run_scan_process", side_effect=error):
                self.assertEqual([row.status for row in check_glitch_screens("TEST.mp4", 3)], [FAIL, FAIL, FAIL])

    def test_command_is_strict_selected_video_passthrough_without_seek_or_scale(self) -> None:
        with scan_run() as run:
            observed = scan_glitch_filter("TEST.mp4", "blackdetect=d=0.2:pic_th=0.98")
        args = run.call_args.args[0]
        self.assertEqual((observed.frames, observed.scanned_seconds), (3, 0.1))
        for option, value in (("-map", "0:v:0"), ("-err_detect", "explode"), ("-fps_mode", "passthrough"), ("-progress", "pipe:1")):
            self.assertEqual(args[args.index(option) + 1], value)
        self.assertIn("-xerror", args)
        self.assertFalse(any(arg in args for arg in ("-ss", "-t", "-r")))
        self.assertNotIn("scale", " ".join(args))

    def test_luma_streams_from_a_private_sink_never_the_progress_pipe(self) -> None:
        with luma_run(luma_rows((90, 91, 92))) as run:
            self.assertEqual(scan_luma_frames("TEST.mp4"), [(0.0, 90), (0.033333, 91), (0.066667, 92)])
        filters = run.call_args.args[0][run.call_args.args[0].index("-vf") + 1]
        self.assertIn("metadata=print:key=lavfi.signalstats.YAVG:file=", filters)
        self.assertNotIn("file=-", filters)
        with scan_run():
            with self.assertRaises(GlitchScanError) as caught:
                scan_luma_frames("TEST.mp4")
        self.assertIn("unreadable", str(caught.exception))

    def test_filter_escape_covers_option_and_graph_levels_including_apostrophes(self) -> None:
        self.assertEqual(filter_escape("/tmp/a b"), "/tmp/a b")
        self.assertEqual(filter_escape("a:b"), "a\\\\:b")
        self.assertEqual(filter_escape("o'b"), "o\\\\\\'b")
        self.assertEqual(filter_escape("x,y[1];z"), "x\\,y\\[1\\]\\;z")
        self.assertEqual(filter_escape("p\\q"), "p\\\\\\\\q")

    def test_missing_duplicate_unpaired_or_malformed_luma_rejects(self) -> None:
        valid = luma_rows((90, 91, 92))
        outputs = ("", valid.replace("lavfi.signalstats.YAVG=91\n", ""),
                   valid.replace("frame:1 ", "frame:0 "),
                   valid.replace("frame:1 pts:1 pts_time:0.033333", "frame:1 pts:0 pts_time:0.000000"),
                   valid.replace("frame:1 pts:1 pts_time:0.033333", "frame:1 pts:0 pts_time:0.033333"),
                   valid.replace("frame:2 pts:2 pts_time:0.066667", "frame:2 pts:2 pts_time:0.000000"),
                   valid.replace("YAVG=91", "YAVG=nan"), valid.replace("YAVG=91", "YAVG=256"),
                   "lavfi.signalstats.YAVG=4\n" + valid, valid + "frame:3 pts:3 pts_time:0.1\n",
                   valid.replace("frame:1 pts:1 pts_time:0.033333", "frame:1 pts:1 pts_ti"))
        for output in outputs:
            with self.subTest(output=output), self.assertRaises(GlitchScanError):
                scan_luma(GlitchScan("", "", 3, 0.1, output))
        with self.assertRaises(GlitchScanError):
            scan_luma(GlitchScan("", "", 4, 0.1, valid))
        with self.assertRaises(GlitchScanError):
            scan_luma(GlitchScan("", valid, 3, 0.1, ""))

    def test_luma_frame_class_ceiling_is_explicit(self) -> None:
        header = f"frame:{MAX_LUMA_FRAMES} pts:{MAX_LUMA_FRAMES} pts_time:1\nlavfi.signalstats.YAVG=1\n"
        with self.assertRaises(GlitchScanError) as caught:
            scan_luma(GlitchScan("", "", MAX_LUMA_FRAMES + 1, 1.0, "x" * 0 + header))
        self.assertIn("frame", str(caught.exception))

    def test_equal_printed_pts_time_with_increasing_pts_is_the_precision_limit(self) -> None:
        rows = ("frame:0 pts:300000000 pts_time:10000\nlavfi.signalstats.YAVG=90\n"
                "frame:1 pts:300001001 pts_time:10000\nlavfi.signalstats.YAVG=91\n"
                "frame:2 pts:300002002 pts_time:10000.1\nlavfi.signalstats.YAVG=92\n")
        self.assertEqual(scan_luma(GlitchScan("", "", 3, 10000.1, rows)), [(10000.0, 90), (10000.0, 91), (10000.1, 92)])

    def test_torn_progress_line_in_sink_position_cannot_pass(self) -> None:
        torn = luma_rows((90, 91, 92)).replace("frame:1 ", "fframe=482\nrame:1 ")
        with self.assertRaises(GlitchScanError):
            scan_luma(GlitchScan("", "", 3, 0.1, torn))


class GlitchVerdictTests(unittest.TestCase):
    """Preserve valid thresholds; explicitly expose former silent omissions."""

    def test_invalid_duration_fails_before_decoder(self) -> None:
        with patch("audit.audit_glitch.scan_glitch_filter") as scan:
            for duration in (0, -1, float("inf"), float("nan"), None, True, "3"):
                self.assertEqual(detect_black("TEST.mp4", duration).status, FAIL)
        scan.assert_not_called()

    def test_black_head_tail_body_and_declared_slack_keep_verdicts(self) -> None:
        progress = "frame=300\nout_time_us=10000000\nprogress=end\n"
        cases = ((black_log((0, 0.5)), None, PASS), (black_log((9.5, 10)), None, PASS),
                 (black_log((2, 3)), None, FAIL), (black_log((2, 3)), [(2.25, 2.75)], WARN),
                 (black_log((2, 3)), [(2.26, 2.75)], FAIL))
        for stderr, allow, status in cases:
            with self.subTest(stderr=stderr, allow=allow), scan_run(stdout=progress, stderr=stderr):
                self.assertEqual(detect_black("TEST.mp4", 10, allow).status, status)

    def test_only_detector_prefixed_lines_are_events(self) -> None:
        progress = "frame=300\nout_time_us=10000000\nprogress=end\n"
        injected = ("    title           : black_start:1 black_end:2 lavfi.freezedetect.freeze_start: 1\n"
                    "Input #0, mov, from 'black_start:1 black_end:2.mp4':\n")
        with scan_run(stdout=progress, stderr=injected):
            self.assertEqual(detect_black("TEST.mp4", 10).status, PASS)
            self.assertEqual(detect_freeze("TEST.mp4", None, 10).status, PASS)
        with scan_run(stdout=progress, stderr="[blackdetect @ 0xTEST] black_start:nan black_end:3\n"):
            self.assertEqual(detect_black("TEST.mp4", 10).status, FAIL)

    def test_colorized_detector_lines_are_stripped_and_declared_never_ignored(self) -> None:
        progress = "frame=300\nout_time_us=10000000\nprogress=end\n"
        plain = black_log((1.0, 2.0))
        colored = ("\x1b[0;33m[blackdetect @ 0xTEST] \x1b[0mblack_start:1.0 black_end:2.0 "
                   "black_duration:1.0\x1b[0m\n")
        with scan_run(stdout=progress, stderr=plain):
            expected = detect_black("TEST.mp4", 10)
        with scan_run(stdout=progress, stderr=colored):
            observed = detect_black("TEST.mp4", 10)
        self.assertEqual(observed.status, expected.status)
        self.assertNotEqual(observed.status, PASS)          # a one-second black run is never clean
        self.assertIn("ansiStripped: true", observed.detail)
        self.assertNotIn("ansiStripped", expected.detail)
        with scan_run(stdout=progress, stderr="\x1b]0;title\x07" + plain):   # not a color code
            self.assertEqual(detect_black("TEST.mp4", 10).status, FAIL)
        with scan_run(stdout=progress, stderr=colored.replace("\n", "") + "\n"):
            self.assertEqual(detect_freeze("TEST.mp4", None, 10).status, PASS)   # stripped line stays a black event only

    def test_scan_process_environment_forbids_color(self) -> None:
        with patch("audit.audit_glitch_scan.subprocess.run", return_value=completed()) as run, \
                patch.dict("os.environ", {"AV_LOG_FORCE_COLOR": "1"}):
            detect_black("TEST.mp4", 0.1)
        env = run.call_args.kwargs["env"]
        self.assertEqual(env.get("AV_LOG_FORCE_NOCOLOR"), "1")
        self.assertNotIn("AV_LOG_FORCE_COLOR", env)

    def test_terminal_progress_block_alone_defines_the_decode(self) -> None:
        stream = "frame=2\nout_time_us=50000\nprogress=continue\nframe=3\nout_time_us=100000\nprogress=end\n"
        with scan_run(stdout=stream):
            self.assertEqual(detect_black("TEST.mp4", 0.1).status, PASS)
        later_keys = "frame=3\nout_time_us=100000\nprogress=end\nframe=9\n"
        end_not_last = "frame=3\nout_time_us=100000\nprogress=end\nframe=4\nout_time_us=1\nprogress=continue\n"
        for output in (later_keys, end_not_last, "frame=3\nout_time_us=1e5\nprogress=end\n"):
            with self.subTest(output=output), scan_run(stdout=output):
                self.assertEqual(detect_black("TEST.mp4", 0.1).status, FAIL)

    def test_malformed_black_and_freeze_events_fail(self) -> None:
        progress = "frame=300\nout_time_us=10000000\nprogress=end\n"
        for stderr in ("[blackdetect @ 0xTEST] black_start:nan black_end:3", "[blackdetect @ 0xTEST] black_start:4 black_end:3",
                       "[blackdetect @ 0xTEST] black_end:3"):
            with scan_run(stdout=progress, stderr=stderr):
                self.assertEqual(detect_black("TEST.mp4", 10).status, FAIL)
        malformed = (freeze_log(("start", "nan")), freeze_log(("duration", 2)),
                     freeze_log(("start", 1), ("start", 2)),
                     freeze_log(("start", 1), ("duration", 0.5), ("end", 1.5)),
                     freeze_log(("start", 1), ("duration", 2)),
                     freeze_log(("start", 1), ("duration", 2), ("end", 3.5)),
                     freeze_log(("start", 1), ("end", 3), ("duration", 2)),
                     freeze_log(("start", 1), ("duration", 2), ("end", 3), ("duration", 2), ("end", 5)),
                     freeze_log(("start", 5), ("duration", 2), ("end", 7), ("start", 6)),
                     freeze_log(("start", 5), ("duration", 2), ("end", 7), ("start", 1), ("duration", 2), ("end", 3)),
                     "[freezedetect @ 0xTEST] lavfi.freezedetect.freeze_start: 1x\n")
        for stderr in malformed:
            with self.subTest(stderr=stderr), scan_run(stderr=stderr):
                row = detect_freeze("TEST.mp4", [(0, 100)])
            self.assertEqual(row.status, FAIL)
            self.assertEqual(row.measured, "unmeasured")

    def test_freeze_end_tolerates_only_ffmpeg_six_decimal_rounding(self) -> None:
        rounded = freeze_log(("start", 1000.989974), ("duration", 2.5), ("end", 1003.489974))
        with scan_run(stderr=rounded):
            self.assertEqual(detect_freeze("TEST.mp4").status, WARN)
        drifted = freeze_log(("start", 1000.989974), ("duration", 2.5), ("end", 1003.493))
        with scan_run(stderr=drifted):
            self.assertEqual(detect_freeze("TEST.mp4").status, FAIL)

    def test_terminal_freeze_cannot_disappear_or_get_an_invented_allowed_end(self) -> None:
        progress = "frame=120\nout_time_us=4000000\nprogress=end\n"
        with scan_run(stdout=progress, stderr=freeze_log(("start", 1))):
            row = detect_freeze("TEST.mp4", [(0, 100)])
            unknown_end = detect_freeze("TEST.mp4", [(0, 3.5)], 4.0)
            declared = detect_freeze("TEST.mp4", [(0.9, 3.8)], 4.0)
        self.assertEqual(row.status, WARN)
        self.assertIn("EOF", row.measured)
        self.assertIn("no declared hold covers it", row.detail)
        self.assertEqual(unknown_end.status, WARN)
        self.assertEqual(declared.status, PASS)
        self.assertIn("reaches the program end", declared.measured)

    def test_terminal_freeze_reports_earlier_closed_spans_too(self) -> None:
        log = freeze_log(("start", 1), ("duration", 2), ("end", 3), ("start", 4))
        with scan_run(stderr=log):
            unplanned = detect_freeze("TEST.mp4")
            declared = detect_freeze("TEST.mp4", [(1, 3)])
        self.assertEqual(unplanned.status, WARN)
        self.assertIn("from 4.00s reaches decode EOF", unplanned.measured)
        self.assertIn("1 earlier unplanned freeze(s), longest 2.00s", unplanned.measured)
        self.assertEqual(declared.status, WARN)
        self.assertIn("1 declared hold(s)", declared.measured)
        self.assertNotIn("unplanned", declared.measured)
        progress = "frame=180\nout_time_us=6000000\nprogress=end\n"
        with scan_run(stdout=progress, stderr=log):
            mixed = detect_freeze("TEST.mp4", [(3.9, 6.0)], 6.0)
        self.assertEqual(mixed.status, WARN)
        self.assertIn("1 freeze(s), longest 2.00s; declared hold from 4.00s", mixed.measured)

    def test_completed_freeze_and_flash_thresholds_preserve_semantics(self) -> None:
        freeze = freeze_log(("start", 1), ("duration", 1.5), ("end", 2.5))
        with scan_run(stderr=freeze):
            self.assertEqual(detect_freeze("TEST.mp4").status, WARN)
            self.assertEqual(detect_freeze("TEST.mp4", [(1, 2.5)]).status, PASS)
            self.assertEqual(detect_freeze("TEST.mp4", [(1.26, 2.5)]).status, WARN)
        two = freeze_log(("start", 1), ("duration", 2), ("end", 3), ("start", 5), ("duration", 3), ("end", 8))
        with scan_run(stderr=two):
            row = detect_freeze("TEST.mp4", [(5, 8)])
        self.assertEqual(row.status, WARN)
        self.assertIn("1 freeze(s), longest 2.00s (1 declared)", row.measured)
        for values, status in (((90, 134, 90), PASS), ((90, 135, 90), WARN), ((90, 45, 90), WARN), ((90, 135, 120), PASS)):
            with luma_run(luma_rows(values)):
                self.assertEqual(detect_flash("TEST.mp4").status, status)


if __name__ == "__main__":
    unittest.main(verbosity=2)
