"""C0679-geometry metadata lower bounds and the read-only attempt size report (P4-25, M-145).

The bounds come from the existing pure functions in ``native_segments.frame_metadata`` over the §4.0 T2 window
geometries: 3 sections, ~60 s chunks, 1920x1080 at 24000/1001; 72 render windows at P = 660 s (15,824 frames)
and 90 at P = 834.3 s (20,003 frames). Both counts are printed as one JSON line each; each must stay below the
unchanged 16 MiB reader limit. Above 80 % is the plan's stop for the operator's declared duration: it is
printed (``stop``), never worked around. The requests carry no implementation, owner or source pins and use a
fixed 197-character output root (the recorded reproduction's), so each count is a floor of the real bound, and
``rootCharactersAt80`` says how long a real root may be before the floor alone passes 80 %. P4-30/P4-32 measure
real attempts with the report script, which this module runs only on synthetic attempt folders it creates.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

import cut_preview_io
from studio import native_long_metadata_report as report
from studio.native_segments import frame_metadata
from studio.native_segments.long_plan import MAX_WINDOW_FRAMES, initial_long_plan

GEOMETRIES = {'P660': (15824, 72), 'P834.3': (20003, 90)}  # program frames, T2 render windows (6 per ~55 s chunk)
SECTIONS, WINDOWS_PER_CHUNK, RATE = 3, 6, '24000/1001'
LIMIT = 16 * 1024 * 1024
# The output root is fixed at 197 characters: the length at which these functions reproduce the recorded
# 15,000-frame reproduction (LSTATUS: 9,485,660 bytes) exactly; see the calibration test and D-C9-3.
ROOT = '/TEST/c0679-attempt-'.ljust(197, 'x')
PICTURE_INPUTS = 'c' * 64
RECORDED_15000_FRAME_OWNER_BYTES = 9_485_660  # initial-long-sections/STATUS.md; ...-double-count-recheck.log


def t2_request(frames: int, windows: int, root: str = ROOT) -> dict:
    """An initial Long request on the T2 geometry: evenly split windows, section edges on window edges."""
    canvas = {'width': 1920, 'height': 1080, 'frameRate': RATE, 'totalFrames': frames}
    boundaries = [frames * index // windows for index in range(windows + 1)]
    return {'pins': {}, 'project': '/TEST/c0679-project', 'output': root,
            'revision': initial_long_plan(canvas, PICTURE_INPUTS, boundaries)}


def sections(request: dict) -> list[list[int]]:
    """The three section frame ranges, each an exact run of whole windows."""
    windows = request['revision']['renderWindows']
    size = len(windows) // SECTIONS
    return [[windows[index]['startFrame'], windows[index + size - 1]['endFrame']]
            for index in range(0, len(windows), size)]


def bounds(request: dict) -> dict[str, int]:
    """The existing lower bound with no completed evidence and no owner or source pins."""
    return frame_metadata.metadata_lower_bounds(request, {}, ({}, {}))


def geometry_record(name: str) -> dict:
    """Byte counts for the full program and each section, the fraction of the limit and the 80 % stop."""
    frames, windows = GEOMETRIES[name]
    request = t2_request(frames, windows)
    full = bounds(request)
    scoped = [max(bounds({**request, 'sectionScope': {'frameRange': span}}).values()) for span in sections(request)]
    count = max(full.values())
    slope = max(bounds(t2_request(frames, windows, ROOT + 'x')).values()) - count
    return {'geometry': name, 'frames': frames, 'windows': windows, 'rootCharacters': len(ROOT), 'full': full,
            'sectionMaxima': scoped, 'bytes': count, 'fractionOfLimit': round(count / LIMIT, 4),
            'stop': count > LIMIT * 4 // 5, 'rootCharactersAt80': len(ROOT) + (LIMIT * 4 // 5 - count) // slope}


class C0679GeometryBoundTests(unittest.TestCase):
    """The pure lower bounds on the two T2 geometries, against the unchanged 16 MiB reader limit."""

    def test_t2_geometry_is_the_plans(self) -> None:
        """72 and 90 whole windows of at most 250 frames cover the clock; 3 sections of ~55 s chunks."""
        for name, (frames, windows) in GEOMETRIES.items():
            rows = t2_request(frames, windows)['revision']['renderWindows']
            spans = sections(t2_request(frames, windows))
            self.assertEqual((len(rows), rows[0]['startFrame'], rows[-1]['endFrame']), (windows, 0, frames), name)
            self.assertTrue(all(0 < row['endFrame'] - row['startFrame'] <= MAX_WINDOW_FRAMES for row in rows))
            self.assertEqual([span[1] for span in spans[:-1]], [span[0] for span in spans[1:]], name)
            self.assertEqual((len(spans), spans[-1][1], windows % (SECTIONS * WINDOWS_PER_CHUNK)), (3, frames, 0))
            chunk_seconds = frames / windows * WINDOWS_PER_CHUNK * 1001 / 24000
            self.assertTrue(45 <= chunk_seconds <= 90, name)

    def test_root_length_reproduces_the_recorded_15000_frame_bound(self) -> None:
        """At ROOT's length the recorded 15,000-frame, 25 fps, 250-frame-grid owner map is matched to the byte."""
        canvas = {'width': 1920, 'height': 1080, 'frameRate': '25/1', 'totalFrames': 15000}
        request = {'pins': {}, 'project': '/TEST/c0679-project', 'output': ROOT,
                   'revision': initial_long_plan(canvas, PICTURE_INPUTS)}
        actual = {path.replace('-try-7/', '-try-0/').replace('-retry-1.render', '.render'): sha
                  for path, sha in frame_metadata.future_frame_pins(request, {}).items()}
        self.assertEqual(len(ROOT), 197)
        self.assertEqual(frame_metadata.metadata_lower_bounds(request, actual, ({}, {}))['futureOwner'],
                         RECORDED_15000_FRAME_OWNER_BYTES)

    def test_c0679_lower_bounds_stay_below_16_mib(self) -> None:
        """Both byte counts are recorded in the output and each is below the unchanged limit."""
        for name in GEOMETRIES:
            record = geometry_record(name)
            sys.stderr.write('\nL5-GEOMETRY ' + json.dumps(record, sort_keys=True) + '\n')
            self.assertLess(record['bytes'], LIMIT, name)
            self.assertLess(max(record['sectionMaxima']), record['bytes'], name)  # a section projects its frames

    def test_no_field_is_omitted(self) -> None:
        """Every future JPEG and window artifact pin is counted, in both owner maps and the stage map."""
        for name, (frames, windows) in GEOMETRIES.items():
            request = t2_request(frames, windows)
            pins = frame_metadata.future_frame_pins(request, {})
            self.assertEqual(len(pins), frames + 6 * windows, name)
            per_map = sum(len(path) + 70 for path in pins)  # "path":"<64 hex>", in canonical compact JSON
            sizes = bounds(request)
            self.assertGreater(sizes['futureOwner'], 2 * per_map, name)
            self.assertGreater(sizes['futureStage'], per_map, name)

    def test_limit_is_unchanged_and_the_gate_admits_t2(self) -> None:
        """No limit is raised; the production gate admits both geometries with its real owner pins."""
        self.assertEqual((cut_preview_io.MAX_JSON, frame_metadata.MAX_JSON, report.MAX_JSON), (LIMIT,) * 3)
        with tempfile.TemporaryDirectory() as project:
            for frames, windows in GEOMETRIES.values():
                frame_metadata.require_retained_metadata_capacity({**t2_request(frames, windows), 'project': project})

    def test_the_gate_refuses_t2_once_the_bound_passes_the_limit(self) -> None:
        """The same geometry under a 500-character output root is refused before media."""
        with tempfile.TemporaryDirectory() as project:
            request = {**t2_request(*GEOMETRIES['P834.3'], root='/' + 'r' * 499), 'project': project}
            with self.assertRaisesRegex(ValueError, 'necessarily exceeds existing JSON bound before media'):
                frame_metadata.require_retained_metadata_capacity(request)


def sized(path: Path, size: int) -> Path:
    """Create a file of exactly ``size`` bytes (sparse, so large sizes use no disk)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, 'wb') as handle:
        handle.truncate(size)
    return path


def synthetic_attempt(root: Path) -> Path:
    """A fake attempt: the three classes at several depths plus files the report must not size."""
    attempt = root / 'attempt'
    sized(attempt / 'export-request.json', 5000)
    for index in range(12):
        sized(attempt / f'segment-picture-{index}.render.json', 1000 + index)
    sized(attempt / 'audio' / 'audio-stage.render.json', 3000)
    for name, size in (('picture-stage.json', 4000), ('segment-picture-3-stage.json', 700),
                       ('audio/audio-stage.json', 800)):
        sized(attempt / name, size)
    for name in ('delivery.json', 'audio/audio-stage-failed.json', 'segment-003-try-0/retained-frames.json',
                 'segment-003-try-0/frames/frame_000001.jpg', 'x.render.json.partial'):
        sized(attempt / name, 9_000_000)
    return attempt


def snapshot(folder: Path) -> list[tuple]:
    """Every entry below ``folder`` with its size and modification time."""
    return sorted((str(path), path.lstat().st_size, path.lstat().st_mtime_ns) for path in folder.rglob('*'))


class AttemptReportTests(unittest.TestCase):
    """The read-only report, only ever on synthetic attempt folders created here."""

    def setUp(self) -> None:
        """A private temporary root per test."""
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()

    def test_report_sizes_the_three_classes_at_any_depth(self) -> None:
        """Counts, per-class maxima, the ten largest and the maximum; other files are never sized."""
        value = report.report(synthetic_attempt(self.root))
        self.assertEqual(value['counts'], {'exportRequest': 1, 'ownerReceipt': 13, 'stageEvidence': 3})
        self.assertEqual(value['maximumByClass'], {'exportRequest': 5000, 'ownerReceipt': 3000, 'stageEvidence': 4000})
        self.assertEqual(list(value['top10'].items())[:4], [('export-request.json', 5000), ('picture-stage.json', 4000),
                                                            ('audio/audio-stage.render.json', 3000),
                                                            ('segment-picture-11.render.json', 1011)])
        self.assertEqual(len(value['top10']), 10)
        self.assertEqual(value['maximum'], {'path': 'export-request.json', 'bytes': 5000,
                                            'fractionOfLimit': round(5000 / LIMIT, 6)})
        self.assertEqual((value['limitBytes'], value['stop'], value['links']), (LIMIT, False, 0))

    def test_report_never_follows_links(self) -> None:
        """A linked receipt or folder is counted as a link, never sized; a linked attempt is refused."""
        outside = sized(self.root / 'outside' / 'big.render.json', 7000)
        attempt = synthetic_attempt(self.root)
        os.symlink(outside, attempt / 'linked.render.json')
        os.symlink(outside.parent, attempt / 'linked-folder')
        value = report.report(attempt)
        self.assertEqual((value['links'], value['counts']['ownerReceipt'], value['maximum']['bytes']), (2, 13, 5000))
        os.symlink(attempt, self.root / 'attempt-link')
        with self.assertRaisesRegex(ValueError, 'real attempt folder'):
            report.report(self.root / 'attempt-link')

    def test_report_stop_is_above_80_percent_of_the_limit(self) -> None:
        """At exactly 80 % (rounded down) there is no stop; one byte more is the plan's stop."""
        attempt = self.root / 'attempt'
        receipt = sized(attempt / 'capture.render.json', LIMIT * 4 // 5)
        self.assertFalse(report.report(attempt)['stop'])
        sized(receipt, LIMIT * 4 // 5 + 1)
        self.assertTrue(report.report(attempt)['stop'])

    def test_report_refuses_an_unlistable_folder(self) -> None:
        """A folder it cannot list stops the report instead of being skipped (which would under-report)."""
        attempt = synthetic_attempt(self.root)
        locked = attempt / 'segment-003-try-0'
        locked.chmod(0)
        self.addCleanup(locked.chmod, 0o755)
        with self.assertRaises(PermissionError):
            report.report(attempt)
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(report.main([str(attempt)]), 2)
        self.assertIn('error', json.loads(output.getvalue()))

    def test_report_cli_prints_one_json_object_and_writes_nothing(self) -> None:
        """The CLI prints the report as one JSON object; the attempt is unchanged; bad arguments exit 2."""
        attempt = synthetic_attempt(self.root)
        before, output = snapshot(self.root), io.StringIO()
        with contextlib.redirect_stdout(output):
            code = report.main([str(attempt)])
        self.assertEqual((code, json.loads(output.getvalue())), (0, report.report(attempt)))
        self.assertEqual(snapshot(self.root), before)
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            self.assertEqual((report.main([]), report.main([str(self.root / 'missing')])), (2, 2))


if __name__ == '__main__':
    unittest.main()
