"""TEST-only synthetic native Short projects for schema-2 dependency packets; no media claims."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from studio.native_runtime import digest
from studio.native_short_regions import ISOLATION_RULE as RULE  # src bumped the rule to v2 (P0 adaptation)
GLOBAL_PART = 'a' * 64


def composition(name: str, css: str = 'color:#fff') -> str:
    """A tiny catalog-shaped composition; bytes only, never rendered by these tests."""
    return (f'<html data-composition-id="{name}"><body><template><style>#{name} .label{{{css}}}</style>'
            f'<div id="{name}" data-composition-id="{name}"><p class="label">TEST {name}</p></div>'
            '</template></body></html>')


def mount(name: str, start: str, duration: str) -> str:
    """One root-clock host with the pinned render-seek timing attributes."""
    return (f'<div id="{name}" data-composition-id="{name}" data-composition-src="compositions/{name}.html" '
            f'data-start="{start}" data-duration="{duration}" style="position:absolute;inset:0"></div>')


class ShortRegionProject:
    """Write one project directory; callers mutate files explicitly to model revisions."""

    def __init__(self, directory: Path, lineage: dict | None = None) -> None:
        self.directory = directory
        directory.mkdir(parents=True)
        (directory / 'compositions').mkdir()
        (directory / 'assets').mkdir()
        self.regions = {'card-a': ('0', '2', 0, 60, 'scoped'), 'card-b': ('10', '2', 300, 360, 'scoped')}
        for name in self.regions:
            (directory / f'compositions/{name}.html').write_text(composition(name))
        (directory / 'assets/source.mp4').write_bytes(b'TEST prepared source bytes')
        self.plan = {'schemaVersion': 1, 'request': {'selection': 'auto'},
                     'canvas': {'frameRate': '30/1', 'totalFrames': 900, 'title': 'TEST title',
                                'segments': [{'startFrame': 0, 'endFrameExclusive': 450},
                                             {'startFrame': 450, 'endFrameExclusive': 900}]},
                     'assets': [{'file': 'assets/source.mp4', 'role': 'source', 'path': '/TEST/original.mp4',
                                 'sha256': digest(directory / 'assets/source.mp4')}],
                     'catalogFiles': [{'file': f'compositions/{name}.html', 'catalogId': 'count-up',
                                       'path': f'/TEST/catalog/{name}-v1.html',
                                       'sha256': digest(directory / f'compositions/{name}.html')}
                                      for name in self.regions],
                     'catalogTitle': {'file': 'compositions/card-a.html', 'copy': {'text': 'TEST title'}},
                     'preparedSources': {'path': str(directory) + '.sources/stage.json', 'sha256': 'b' * 64},
                     'strategy': {'payoff': 'TEST payoff', 'pacing': {'lanes': {'motion': 'TEST prose'},
                                  'holds': [{'startFrame': 6, 'endFrame': 54, 'targetId': 'card-a'}]},
                                  'story': {'revisionHash': 'c' * 64, 'payoff': 'TEST payoff'}}}
        self.prepared = {'schemaVersion': 1, 'package': {'path': str(directory) + '.sources/stage.json', 'sha256': 'd' * 64},
                         'mappings': [{'id': 'source-0-0', 'preparedFile': 'assets/source.mp4', 'mediaStart': 1}]}
        self.lineage = lineage
        self.write()

    def write(self) -> None:
        """Rewrite every generated file from the current fields."""
        body = ''.join(mount(name, start, duration) for name, (start, duration, *_rest) in self.regions.items())
        (self.directory / 'index.html').write_text(
            f'<html><body><div id="native-canvas" data-composition-id="native-canvas">{body}</div></body></html>')
        (self.directory / 'SHORT-PROJECT.json').write_text(json.dumps(self.plan))
        (self.directory / 'PREPARED-SOURCES.json').write_text(json.dumps(self.prepared))
        units = [{'id': name, 'file': f'compositions/{name}.html', 'startFrame': start, 'endFrame': end,
                  'isolation': {'status': 'scoped', 'rule': RULE, 'globalSha256': GLOBAL_PART} if status == 'scoped'
                  else {'status': 'global', 'reason': 'TEST unproven composition'}}
                 for name, (_s, _d, start, end, status) in self.regions.items()]
        (self.directory / 'REVIEW-REGIONS.json').write_text(json.dumps(
            {'schemaVersion': 2, 'derivation': 'mounted-composition-intervals-v1', 'units': units}))
        manifest = {'schemaVersion': 1, 'projectHash': hashlib.sha256(json.dumps(self.plan).encode()).hexdigest()}
        if self.lineage is not None:
            manifest['lineage'] = self.lineage
        (self.directory / 'PROJECT-MANIFEST.json').write_text(json.dumps(manifest))

    def request(self, pins: dict | None = None) -> dict:
        """The minimal request fields a packet reads; implementation pins are TEST values."""
        return {'project': str(self.directory), 'runtime': '/TEST/runtime/hyperframes', 'tools': {'node': '/TEST/node'},
                'captureMode': 'sdk-streaming', 'sourceCacheMode': 'acquire-sdk-preflight', 'audioProfile': 'TEST',
                'pins': pins or {}}


def root_lineage(clip: str = 'e' * 32) -> dict:
    """A recorded root clip identity."""
    return {'schemaVersion': 1, 'clipId': clip, 'generation': 0, 'parent': None}


def child_lineage(parent: ShortRegionProject) -> dict:
    """Bind a rebuilt revision to its parent's exact manifest bytes."""
    manifest = parent.directory / 'PROJECT-MANIFEST.json'
    recorded = json.loads(manifest.read_text())
    prior = recorded['lineage']
    return {'schemaVersion': 1, 'clipId': prior['clipId'], 'generation': prior['generation'] + 1,
            'parent': {'path': str(parent.directory), 'projectHash': recorded['projectHash'],
                       'manifestSha256': digest(manifest), 'clipId': prior['clipId'], 'generation': prior['generation']}}
