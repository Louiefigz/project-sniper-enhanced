"""Adapter-neutral immutable frame inventory and explicit bounds; fictional byte fixtures."""
from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

from studio.native_retained_frames import CaptureContract, ENCODING, KIND, frame_partition, read_frame_inventory
from studio.native_runtime import digest


class RetainedFrameTests(unittest.TestCase):
    """Neither Short geometry nor permissive filename/session identities leak into generic reads."""

    def setUp(self) -> None:
        """A Long absolute frame beyond the Short clock, with a tiny bounded test payload."""
        root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()
        self.file = root / 'frame_040000.jpg'
        self.file.write_bytes(b'TEST fictional capture')
        canvas = {'width': 320, 'height': 180, 'frameRate': '25/1', 'totalFrames': 50000}
        self.contract = CaptureContract(root, canvas, (40000, 40001), (250, 4096))
        self.value = {'schemaVersion': 1, 'kind': KIND, 'canvas': canvas, 'frameRange': [40000, 40001],
                      'encoding': ENCODING, 'frames': [{'frame': 40000, 'path': str(self.file),
                          'sha256': digest(self.file), 'bytes': self.file.stat().st_size, 'origin': 'captured'}],
                      'sessions': [{'frames': [40000], 'sessionClosed': True, 'browserPoolDrained': True,
                                    'serverClosed': True, 'transport': {'errors': 0}}]}

    def test_geometry_and_absolute_frame_are_adapter_supplied(self) -> None:
        """Generic capture validation permits a validated non-Short geometry and clock."""
        self.assertEqual(read_frame_inventory(self.value, self.contract), {str(self.file): digest(self.file)})
        self.assertEqual(frame_partition((40000, 40004), [[40002, 40003]], 250), ([40002], [40000, 40001, 40003]))

    def test_partition_is_bounded_ordered_and_nonoverlapping(self) -> None:
        """Malformed input cannot allocate an unbounded per-frame set."""
        for bounds, dirty, maximum in [((0, 50000), [], 250), ((0, 20), [[2, 8], [7, 9]], 250),
                                        ((0, 20), [[10, 12], [2, 3]], 250), ((0, 20), [], -1)]:
            with self.assertRaises(ValueError):
                frame_partition(bounds, dirty, maximum)

    def test_corruption_links_and_size_refuse(self) -> None:
        """The generic reader checks real bytes and link identity independently of manifest hashes."""
        self.file.write_bytes(b'TEST changed bytes')
        with self.assertRaises((ValueError, RuntimeError)):
            read_frame_inventory(self.value, self.contract)
        self.file.write_bytes(b'TEST fictional capture')
        alias = self.file.parent / 'alias.jpg'
        alias.hardlink_to(self.file)
        with self.assertRaises((ValueError, RuntimeError)):
            read_frame_inventory(self.value, self.contract)

    def test_session_coverage_cleanup_and_manifest_shape_are_exact(self) -> None:
        """A successful-looking record cannot omit a frame or leave its browser session active."""
        mutations = [lambda v: v['sessions'][0].update(frames=[40001]),
                     lambda v: v['sessions'][0].update(sessionClosed=False),
                     lambda v: v['sessions'][0].update(transport=None),
                     lambda v: v.update(frames=[None]), lambda v: v.update(extra='unadmitted')]
        for mutate in mutations:
            value = copy.deepcopy(self.value)
            mutate(value)
            with self.assertRaises(ValueError):
                read_frame_inventory(value, self.contract)


if __name__ == '__main__':
    unittest.main()
