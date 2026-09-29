"""Fictional JPEG bytes with real original request registration and owner StageEvidence."""
from __future__ import annotations

import shutil
from pathlib import Path

from _native_long_sections_acceptance_fixture import HTML, CANVAS, LongSectionsFixture
from _native_short_pipeline_fixture import write_json
from cut_preview_io import bound_json
from studio.native_export_history import register_attempt
from studio.native_runtime import digest
from studio.native_retained_frames import KIND, ENCODING
from studio.native_segments.compatibility import prepare_long_repair
from studio.native_segments.dependency import inventory
from studio.native_segments.long_plan import initial_long_plan
from studio.native_segments.owners import artifacts, STATUS
from studio.native_stage_evidence import StageEvidence, seal_stage


def manifest(request: dict, name: str, partition: dict | None = None) -> dict:
    """Create bounded non-JPEG test payloads, explicitly not native capture evidence."""
    work = Path(request['output']) / name
    frames = work / 'frames'
    frames.mkdir(parents=True)
    window = request['revision']['renderWindows'][0]
    rows = []
    captured = []
    for frame in range(window['startFrame'], window['endFrame']):
        file = frames / f'frame_{frame:06d}.jpg'
        file.write_bytes(f'TEST fictional frame {frame}'.encode())
        origin = 'retained' if partition and frame in partition['copyFrames'] else 'captured'
        rows.append({'frame': frame, 'path': str(file), 'sha256': digest(file), 'bytes': file.stat().st_size,
                     'origin': origin})
        if origin == 'captured':
            captured.append(frame)
    sessions = [{'frames': captured[start:start + 48], 'sessionClosed': True, 'browserPoolDrained': True,
                 'serverClosed': True, 'transport': {'errors': 0}} for start in range(0, len(captured), 48)]
    file = work / 'retained-frames.json'
    write_json(file, {'schemaVersion': 1, 'kind': KIND, 'canvas': request['revision']['canvas'],
                     'frameRange': [window['startFrame'], window['endFrame']], 'encoding': ENCODING,
                     'frames': rows, 'sessions': sessions})
    return {'path': str(file), 'sha256': digest(file)}


class RetainedFixture:
    """One 75-frame encoder window whose B-local edit affects only frames 25..49."""

    def __init__(self, base: Path, retained: bool = True) -> None:
        """Use actual registered source pins and cleanup seals; substitute only media bytes."""
        self.base, self.f = base, LongSectionsFixture(base)
        self.request = self.f.request
        self.request['sectionImplementationPins'] = {file: sha for file, sha in self.request['pins'].items()
                                                    if not Path(file).is_relative_to(self.f.project)}
        self.request['revision'] = initial_long_plan(CANVAS, 'a' * 64, [0, 75])
        self.f.write_request(self.request)
        register_attempt(self.request)
        self.phase = 'segment-picture-0'
        self.f.write_phase(self.phase, self.f.root)
        receipt_file = self.f.root / f'{self.phase}.json'
        value = bound_json(receipt_file)
        extra = {}
        if retained:
            value['retainedFrames'] = manifest(self.request, 'capture-original')
            write_json(receipt_file, value)
            inventory_value = bound_json(Path(value['retainedFrames']['path']))
            extra = {f"retainedFrame{row['frame']}": Path(row['path']) for row in inventory_value['frames']}
            extra['retainedFrames'] = Path(value['retainedFrames']['path'])
        pins = {**self.request['pins'], str(self.f.root / 'export-request.json'): digest(self.f.root / 'export-request.json')}
        owner = self.f.owner_record(self.request, pins, STATUS, str(receipt_file))
        supervisor = self.f.root / f'{self.phase}.render.json'
        write_json(supervisor, owner)
        seal_stage(StageEvidence(self.phase, self.f.project, self.f.root, self.f.root / 'export-request.json',
                                 supervisor, self.request['pins'], {**artifacts(self.f.root, self.phase), **extra}, STATUS))

    def child(self, global_change: bool = False, parent: dict | None = None) -> dict:
        """Preserve parent source and admit an actual local DOM or global style change."""
        original = parent or self.request
        name = 'second' if parent else 'repaired'
        project, output = self.base / f'{name}-project', self.base / f'{name}-attempt'
        shutil.copytree(original['project'], project)
        html = HTML.format(middle=f'B {name}')
        if global_change:
            html = html.replace('<body>', '<style>*{color:red}</style><body>')
        (project / 'index.html').write_text(html)
        pins = {**self.request['sectionImplementationPins'],
                **{str(project / file): sha for file, sha in inventory(project).items()}}
        current = {**original, 'project': str(project), 'output': str(output), 'pins': pins}
        current = prepare_long_repair(current, Path(original['output']))
        output.mkdir()
        return current

    def complete(self, request: dict, plan: dict, include_proof: bool = True) -> None:
        """Seal a synthetic second capture with real request/lineage and optional comparison authority."""
        from studio.native_segments.frame_reuse import validate_frame_capture
        root = Path(request['output'])
        request['sectionFrameReuse'] = {self.phase: plan}
        self.f.write_request(request)
        register_attempt(request)
        self.f.write_phase(self.phase, root)
        file = root / f'{self.phase}.json'
        value = bound_json(file)
        pin = manifest(request, 'capture-current', plan)
        comparison = validate_frame_capture(request, self.phase, plan, pin)
        value['retainedFrames'] = pin
        inventory_value = bound_json(Path(pin['path']))
        extra = {f"retainedFrame{row['frame']}": Path(row['path']) for row in inventory_value['frames']}
        extra['retainedFrames'] = Path(pin['path'])
        if include_proof:
            proof_file = root / 'capture-current' / 'retained-proof.json'
            write_json(proof_file, comparison)
            value['retainedFrameProof'] = {'path': str(proof_file), 'sha256': digest(proof_file)}
            extra['retainedFrameProof'] = proof_file
        write_json(file, value)
        pins = {**request['pins'], str(root / 'export-request.json'): digest(root / 'export-request.json')}
        supervisor = root / f'{self.phase}.render.json'
        write_json(supervisor, self.f.owner_record(request, pins, STATUS, str(file)))
        seal_stage(StageEvidence(self.phase, Path(request['project']), root, root / 'export-request.json',
                                 supervisor, request['pins'], {**artifacts(root, self.phase), **extra}, STATUS))
