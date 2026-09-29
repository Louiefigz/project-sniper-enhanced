"""Short dependency closure and upstream file contract; no render or eligibility qualification."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from studio.native_runtime import digest
from studio.native_stage_evidence import MAX_NATIVE_FILE_BYTES, verify_pins
from studio import native_short_picture_reuse as reuse


class ShortRetainedWrapperTests(unittest.TestCase):
    """Keep the generic executable in the existing Short picture closure and file policy."""

    def setUp(self) -> None:
        """Use isolated tiny files, actual shared pin readers and actual implementation inventory."""
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory())).resolve()

    def test_upstream_short_pin_reader_already_refuses_empty_or_hardlinked_files(self) -> None:
        """Both frame and JSON donor metadata traverse this same reader before the Short child starts."""
        self.assertEqual(MAX_NATIVE_FILE_BYTES, 2 ** 40)
        for name in ('frame_000000.jpg', 'export-request.json', 'batched-picture.json', 'delivery.json'):
            file = self.root / name
            file.write_bytes(b'TEST admitted donor bytes')
            pins = {str(file): digest(file)}
            verify_pins(pins)
            alias = self.root / 'alias'
            alias.hardlink_to(file)
            with self.assertRaisesRegex(RuntimeError, 'unsafe or over budget'):
                verify_pins(pins)
            alias.unlink()
            file.write_bytes(b'')
            with self.assertRaisesRegex(RuntimeError, 'unsafe or over budget'):
                verify_pins({str(file): digest(file)})

    def test_generic_copy_implementation_is_required_in_picture_dependency_closure(self) -> None:
        """A previous Short cannot reuse pictures without the exact generic executable pin."""
        generic = str(reuse.STUDIO / 'native_retained_frames.mjs')
        self.assertIn('native_retained_frames.mjs', reuse.PICTURE_CODE)
        runtime = self.root / 'runtime'
        (runtime / 'dist').mkdir(parents=True)
        for name in reuse.RUNTIME_FILES:
            (runtime / 'dist' / name).write_text('TEST runtime')
        executable = self.root / 'tool'
        executable.write_text('TEST executable')
        paths = [reuse.STUDIO / name for name in reuse.PICTURE_CODE]
        paths += list((runtime / 'dist').iterdir()) + [executable]
        previous = {'runtime': str(runtime), 'tools': dict.fromkeys(('node', 'browser', 'ffmpeg', 'ffprobe'), str(executable)),
                    'pins': {str(file): digest(file) for file in paths}}
        with patch.object(reuse, 'project_dependencies', return_value={}):
            pins = reuse.picture_dependencies(self.root, previous)
            self.assertEqual(pins[generic], digest(Path(generic)))
            previous['pins'].pop(generic)
            with self.assertRaisesRegex(ValueError, 'was not pinned'):
                reuse.picture_dependencies(self.root, previous)
