"""Synthetic Long owners exercising real stage seals, never media or quality proof."""
from __future__ import annotations

import json
from pathlib import Path

from _native_short_pipeline_fixture import ShortPipelineFixture, write_json
from studio.native_runtime import digest
from studio.native_segments.plan import initial_long_plan

CANVAS = {'width': 320, 'height': 180, 'frameRate': '25/1', 'totalFrames': 75}
HTML = ('<html><body><div id="root" data-duration="3">'
        '<div id="a" style="position:absolute" class="clip" data-start="0" data-duration="1">A</div>'
        '<div id="b" style="position:absolute" class="clip" data-start="1" data-duration="1">{middle}</div>'
        '<div id="c" style="position:absolute" class="clip" data-start="2" data-duration="1">C</div>'
        '</div></body></html>')


class LongSectionsFixture(ShortPipelineFixture):
    """Keep real filesystem, request and seals while replacing only native execution."""

    def __init__(self, base: Path) -> None:
        """Publish three absolute sections with explicitly non-decodable test media."""
        super().__init__(base)
        (self.project / 'SHORT-PROJECT.json').unlink()
        (self.project / 'index.html').write_text(HTML.format(middle='B'))
        write_json(self.project / 'LONG-PROJECT.json', {'schemaVersion': 1, 'canvas': CANVAS})
        self.inputs = {name: sha for name, sha in self.inputs.items()
                       if not Path(name).is_relative_to(self.project)}
        self.inputs.update({str(file): digest(file) for file in self.project.iterdir()})
        self.request.update(adapter='native-long', pins=dict(self.inputs), budget={'ownerSeconds': 600},
                            diskProjection={'sampleBytes': 1024, 'outputBytes': 1024, 'miscBytes': 1024},
                            sectionAttemptSequence=1,
                            revision=initial_long_plan(CANVAS, 'a' * 64, [0, 25, 50, 75]))
        self.write_request(self.request)

    def write_phase(self, label: str, root: Path) -> None:
        """Emit section receipts using the production fields and synthetic bytes."""
        if not label.startswith('segment-picture-'):
            super().write_phase(label, root)
            return
        phase = label.split('-retry-')[0]
        request = json.loads((root / 'export-request.json').read_text())
        index = int(phase.rsplit('-', 1)[1])
        window = request['revision']['renderWindows'][index]
        media = root / f'{phase}-TEST.mp4'
        media.write_bytes(f'TEST non-decodable section {index}'.encode())
        audio = root / f'{phase}-TEST.wav'
        audio.write_bytes(f'TEST non-decodable section audio {index}'.encode())
        piece = {'path': str(media), 'sha256': digest(media),
                 'startFrame': window['startFrame'], 'endFrameExclusive': window['endFrame'],
                 'frames': window['endFrame'] - window['startFrame'], 'origin': 'rendered'}
        write_json(root / f'{phase}.json', {'schemaVersion': 1, 'phase': phase,
                   'window': window, 'planIdentity': request['revision']['identity'],
                   'piece': piece, 'audio': {'path': str(audio), 'sha256': digest(audio)},
                   'probes': [], 'frameSha256': [], 'sessions': 1})

    def restart(self) -> dict:
        """Create a fresh attempt retaining the original admitted dependency identity."""
        root = self.base / 'restarted'
        root.mkdir()
        return {**self.request, 'output': str(root), 'pins': dict(self.inputs), 'sectionAttemptSequence': 2,
                'revision': dict(self.request['revision'])}

    def review_bundle(self) -> tuple[Path, dict]:
        """Return fictional judgments for tests, explicitly separate from real approval."""
        from studio.native_segments.reviews import CHECKS
        evidence = self.base / 'TEST-review-evidence.txt'
        evidence.write_text('TEST synthetic review fixture; no playback or editorial pass occurred.')
        rows = []
        for window in self.request['revision']['renderWindows']:
            value = json.loads((self.root / f"segment-picture-{window['index']}.json").read_text())
            media = [('encoded-playback', value['piece']), ('audio-listening', value['audio'])]
            references = [{key: item[key] for key in ('path', 'sha256')} for _kind, item in media]
            rows.append({'sectionId': window['id'], 'generation': window['generation'],
                         'planIdentity': self.request['revision']['identity'],
                         'inputIdentity': window['inputIdentity'], 'status': 'pass',
                         'frameRange': [window['startFrame'], window['endFrame']],
                         'media': {key: value['piece'][key] for key in ('path', 'sha256')},
                         'authorTaskId': 'TEST-author', 'reviewerTaskId': 'TEST-independent-reviewer',
                         'checks': dict.fromkeys(CHECKS, True),
                         'assessments': {key: f'TEST synthetic {key}; no review occurred' for key in CHECKS},
                         'observations': [{'kind': kind, 'path': item['path'], 'sha256': item['sha256'],
                                           'frameRange': [window['startFrame'], window['endFrame']]}
                                          for kind, item in media],
                         'evidence': [*references, {'path': str(evidence), 'sha256': digest(evidence)}]})
        return self.base / 'TEST-section-reviews.json', {'schemaVersion': 1, 'reviews': rows}

    def launch_section(self, parent: object, phase: str) -> dict:
        """Replace child-process launch only; retain the real owner adapter and sealing."""
        from studio.native_segments.owners import seal_window, supervise_window
        from studio.native_short_pipeline import NativeShortPipeline
        pipeline = NativeShortPipeline(parent.request, {})
        label = supervise_window(pipeline, phase, [0])
        seal_window(pipeline, phase, label)
        return {'status': 'sealed', 'stages': pipeline.stages, 'evidence': pipeline.evidence}
