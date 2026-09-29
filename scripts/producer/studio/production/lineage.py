"""Which output a native project is, across formats: Short selections and Long manifests with lineage.

A project folder declares exactly one plan: ``SHORT-PROJECT.json`` (a Short, identified as before by its
canvas source and cut seconds, ``native_budget_selection``) or ``LONG-PROJECT.json`` (a Long). A Long is
identified by its manifest and lineage, not by the single-source Short selection: the exact bytes of
``LONG-PROJECT.json`` (its content), and the prepared ``LONG-REQUEST.json`` it binds (``requestPacket``,
checked against its SHA-256) together with every admitted source recording that request lists (one or
more). Legacy Longs without a request packet cannot be identified and are refused.

Mixed identity requires the same format. Two Long lineages are the same Long (a revision, which stays
with its output and its counters) when they bind the same request, or when their recording sets share at
least half of their union or 90% of the smaller set: the Short revision thresholds applied to recordings,
so re-preparing a request or adding or dropping one recording cannot open fresh counters. ``same_short``
is unchanged and compares Shorts only: a 60-second Short cut inside a 600-second Long is never that Long.
When it was authorized as the Long's derivation, the Short's output row records it (``derivedFrom``); its
counters stay its own.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cut_preview_io import bound_json, read_bytes
from studio.native_budget_schema import BOUNDS, SHA256
from studio.native_budget_selection import SAME_SHORT_SHARE, SUBSET_SHARE, same_short
from studio.production.formats import output_format

PLANS = {'SHORT-PROJECT.json': 'short', 'LONG-PROJECT.json': 'long'}


def project_format(project: Path) -> str:
    """The one declared plan of a project folder; none, both or a linked plan is refused."""
    plans = [name for name in PLANS if (project / name).exists() or (project / name).is_symlink()]
    if len(plans) != 1 or (project / plans[0]).is_symlink():
        raise ValueError(f'{project} needs exactly one SHORT-PROJECT.json or LONG-PROJECT.json (not a link)')
    return PLANS[plans[0]]


def long_identity(project: Path) -> dict:
    """A Long's content hash (its LONG-PROJECT.json bytes) and lineage (request and recordings)."""
    try:
        plan_bytes = read_bytes(project / 'LONG-PROJECT.json')
        plan = json.loads(plan_bytes.decode('utf-8'))
        packet = plan.get('requestPacket') if type(plan) is dict else None
        if type(packet) is not dict or set(packet) != {'path', 'sha256'} or not _digest(packet['sha256']):
            raise ValueError('a Long without a request packet (legacy) has no lineage')
        request_path = Path(packet['path'])
        if not request_path.is_absolute() or request_path.is_symlink():
            raise ValueError('the Long request packet path is not absolute or is a link')
        request = bound_json(request_path, packet['sha256'])
    except RuntimeError as error:
        raise ValueError(f'Long manifest or request changed or unreadable: {error}') from error
    return {'projectHash': hashlib.sha256(plan_bytes).hexdigest(), 'outputSeconds': canvas_seconds(plan.get('canvas')),
            'lineage': {'request': packet['sha256'], 'sources': _sources(request)}}


def canvas_seconds(canvas: object) -> float | None:
    """The program duration a Long's canvas declares, or None while the prepared scaffold has no canvas yet."""
    if canvas is None:
        return None
    numerator, denominator = map(int, canvas['frameRate'].split('/'))
    if numerator <= 0 or denominator <= 0 or type(canvas['totalFrames']) is not int:
        raise ValueError('a Long canvas declares a positive frame rate and whole frames')
    return canvas['totalFrames'] * denominator / numerator


def _sources(request: dict) -> list[str]:
    """The sorted unique SHA-256 digests of every admitted source recording the request lists."""
    rows = request.get('sources')
    if type(rows) is not list or not 0 < len(rows) <= BOUNDS['claims']:
        raise ValueError(f'a Long request lists 1-{BOUNDS["claims"]} admitted source recordings')
    digests = [row.get('sha256') if type(row) is dict else None for row in rows]
    if not all(map(_digest, digests)):
        raise ValueError('every Long source recording names its SHA-256')
    return sorted(set(digests))


def _digest(value: object) -> bool:
    """A lowercase SHA-256 hex digest."""
    return type(value) is str and SHA256.fullmatch(value) is not None


def same_long(first: dict, second: dict) -> bool:
    """True when one lineage is a revision of the other: the same request, or mostly the same recordings."""
    if first['request'] == second['request']:
        return True
    a, b = set(first['sources']), set(second['sources'])
    shared = len(a & b)
    return shared / len(a | b) >= SAME_SHORT_SHARE or shared / min(len(a), len(b)) >= SUBSET_SHARE


def same_project(row: dict, identity: dict) -> bool:
    """Same folder, or the same content (when both have a content hash)."""
    same_content = identity['projectHash'] is not None and row['projectHash'] == identity['projectHash']
    return row['key'] == identity['key'] or same_content


def output_match(clip: dict, identity: dict) -> str | None:
    """'project' (this folder or identical content), 'revision' (same format, same output) or None."""
    if any(same_project(row, identity) for row in clip['projects']):
        return 'project'
    if output_format(clip) != identity['format']:
        return None
    if identity['format'] == 'short':
        return 'revision' if any(same_short(row['selection'], identity['selection']) for row in clip['projects']) \
            else None
    lineage = clip['output']['lineage']
    return 'revision' if lineage is not None and same_long(lineage, identity['lineage']) else None
