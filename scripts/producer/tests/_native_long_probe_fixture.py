"""Synthetic decoder boundary for stage/lineage tests, never media qualification."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from cut_preview_io import write_new
from studio.native_runtime import digest
from studio.native_segments.probe import dependency_frames, execute_dependency_probe


def synthetic_dependency_probe(request: dict, phase: str, directory: Path, value: dict) -> dict:
    """Run real proof construction with explicitly fake capture and decoded comparison bytes."""
    directory.mkdir(exist_ok=True)
    def capture(command: list, **_options: object) -> None:
        """Only the new probe entry may launch; full-picture rendering remains forbidden."""
        if Path(command[1]).name != 'probe.mjs':
            raise AssertionError('Unexpected picture render in reuse TEST')
        work = Path(command[-2])
        work.mkdir()
        rows = []
        for frame in dependency_frames(value['window'], Path(request['project'])):
            file = work / f'probe-{frame}.jpg'
            file.write_bytes(f'TEST synthetic current screenshot {frame}'.encode())
            rows.append({'frame': frame, 'path': str(file), 'sha256': digest(file)})
        write_new(work / 'capture.json', {'window': value['window'], 'planIdentity': request['revision']['identity'],
                                       'probes': rows, 'TEST': 'no real renderer'})

    def compare(rows: list, _piece: dict, canvas: dict, _directory: Path) -> dict:
        """This fixture's media is text; numerical/real-media comparators have separate tests."""
        return {'passed': True, 'absoluteFrames': [row['frame'] for row in rows], 'canvas': canvas,
                'runtimeQualification': 'not-established', 'TEST': 'synthetic decode, no playback claim'}

    with patch('studio.native_segments.probe.subprocess.run', side_effect=capture), \
            patch('studio.native_segments.probe.verify_long_segment_probes', side_effect=compare):
        return execute_dependency_probe(request, phase, directory, value)
