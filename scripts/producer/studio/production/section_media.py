"""Bounded logical-section media index; existing window seals retain media authority."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cut_preview_io import read_bytes
from cross_runtime_canonical_json import canonical_compact_json
from studio.native_segments.owners import current_window, segment_phase
from studio.production.section_results import rehash, require, validate_pin

MAX_MANIFEST_BYTES = 4 * 1024 ** 2
KEYS = {'schemaVersion', 'kind', 'request', 'planIdentity', 'sectionId', 'generation',
        'inputIdentity', 'frameRange', 'windows'}
WINDOW_KEYS = {'phase', 'seal', 'picture', 'audio', 'frameRange'}


def read_index(pin: dict) -> dict:
    """Read a size-bounded, canonical, digest-bound manifest without accepting ambiguous JSON."""
    validate_pin(pin)
    require(pin['bytes'] <= MAX_MANIFEST_BYTES, 'media manifest is too large')
    rehash(pin)
    raw = read_bytes(Path(pin['path']), MAX_MANIFEST_BYTES)
    require(len(raw) == pin['bytes'] and hashlib.sha256(raw).hexdigest() == pin['sha256'],
            'media manifest bytes changed')
    value = json.loads(raw)
    require(type(value) is dict and canonical_compact_json(value).encode() == raw.removesuffix(b'\n'),
            'media manifest must be exact canonical JSON')
    return value


def checked_request(index: dict, binding: dict) -> dict:
    """Reopen the immutable export request identified by this exact logical assignment."""
    from cut_preview_io import bound_json
    require(set(index) in (KEYS, KEYS | {'presentation'}) and type(index['schemaVersion']) is int
            and index['schemaVersion'] == 1 and index['kind'] == 'native-long-section-media',
            'invalid media manifest fields')
    require(type(index['frameRange']) is list and len(index['frameRange']) == 2
            and all(type(frame) is int for frame in index['frameRange']), 'invalid manifest logical range')
    require(type(index['generation']) is int and all(index[key] == binding[key] for key in ('sectionId', 'generation', 'inputIdentity', 'frameRange')),
            'media manifest logical generation differs')
    rehash(index['request'])
    request = bound_json(Path(index['request']['path']), index['request']['sha256'])
    require(index['request']['path'] == str(Path(request['output']) / 'export-request.json')
            and request['revision']['mode'] == 'initial-long'
            and index['planIdentity'] == request['revision']['identity'], 'media manifest request differs')
    return request


def window_observations(request: dict, row: dict) -> list[dict]:
    """Revalidate existing StageEvidence and exact picture/audio; an index creates no new authority."""
    require(type(row) is dict and set(row) == WINDOW_KEYS and type(row['phase']) is str
            and segment_phase(row['phase']) is not None, 'invalid media manifest window')
    phase = row['phase']
    direct = Path(request['output']) / f'{phase}-stage.json'
    seal = direct if direct.exists() else Path(request['revision'].get('windowDonors', {}).get(phase, str(direct)))
    validate_pin(row['seal'])
    require(row['seal']['path'] == str(seal), 'media manifest names a different window seal')
    rehash(row['seal'])
    value = current_window(request, phase)
    require(type(row['frameRange']) is list and len(row['frameRange']) == 2
            and all(type(frame) is int for frame in row['frameRange'])
            and row['frameRange'] == [value['window']['startFrame'], value['window']['endFrame']],
            'media manifest window range differs')
    observations = []
    for kind, key, source in (('encoded-playback', 'picture', 'piece'), ('audio-listening', 'audio', 'audio')):
        rehash(row[key])
        require(row[key]['path'] == value[source]['path'] and row[key]['sha256'] == value[source]['sha256'],
                'media manifest does not name current sealed bytes')
        observations.append({'kind': kind, 'path': row[key]['path'], 'sha256': row[key]['sha256'],
                             'frameRange': row['frameRange']})
    return observations


def read_media_manifest(binding: dict) -> list[dict]:
    """Return the exact tiled encoded observations after revalidating every underlying window."""
    index = read_index(binding['mediaManifest'])
    request = checked_request(index, binding)
    rows = index['windows']
    require(type(rows) is list and 1 <= len(rows) <= 768, 'invalid media manifest window count')
    observations, cursor, phases = [], binding['frameRange'][0], set()
    for row in rows:
        expected = window_observations(request, row)
        require(row['phase'] not in phases and row['frameRange'][0] == cursor,
                'media manifest windows overlap or omit frames')
        cursor = row['frameRange'][1]
        phases.add(row['phase'])
        observations.extend(expected)
    require(cursor == binding['frameRange'][1], 'media manifest does not cover the logical section')
    require(len({row['path'] for row in observations}) == len(observations), 'duplicate media manifest path')
    if 'presentation' in index:
        from studio.production.section_chunk_presentation import presentation_observations
        presentation_observations(request, index['presentation'], binding['frameRange'])
    return observations
