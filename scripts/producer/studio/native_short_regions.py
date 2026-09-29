"""Content-addressed preview dependencies for native Short projects (packet schema 2).

The TypeScript writer derives REVIEW-REGIONS.json (schema 2) from the staged mounts
and the cold reader re-derives it at every check-export, which also verifies each
composition's isolation verdict. This reader re-checks every interval against the
executable mounts. Shared inputs hash only what an executable path can read, by
content: no project, revision-folder or prepared-source path enters a unit hash.
"""
from __future__ import annotations

import math
import re
from html.parser import HTMLParser
from fractions import Fraction
from pathlib import Path

from cut_preview_io import bound_json, digest
from studio.native_clip_lineage import packet_subject
from studio.native_preflight_inputs import inventory
from studio.native_runtime import digest as file_digest
from studio.native_stage_evidence import require

REGIONS = 'REVIEW-REGIONS.json'
DERIVATION = 'mounted-composition-intervals-v1'
ISOLATION_RULE = 'hyperframes-0.8.31-scoped-composition-v2'
DECIMAL = re.compile(r'(?:0|[1-9]\d*)(?:\.\d+)?')
REGION_FILE = re.compile(r'compositions/([a-z0-9][a-z0-9-]{0,79})\.html')
# Approval, lineage and documentation files that no render, capture or audio path reads.
NON_EXECUTABLE = frozenset({'PROJECT-MANIFEST.json', 'PREBUILD-REVIEW.json', REGIONS, 'BRIEF.md',
                            'STORYBOARD.md', 'PACING-REPORT.json', 'STORY-REPORT.json',
                            'ASSET-USE-REPORT.json', 'STYLE-APPLICATION.json',
                            'VISUAL-PLAN-APPLICATION.json', 'VISUAL-PLAN.json',
                            'GUIDED-PROPOSAL.json', 'DIRECTOR-LIBRARY.json'})
EXECUTABLE_PLAN = ('schemaVersion', 'request', 'canvas', 'audioFinishing', 'extension',
                   'expectations', 'catalogTitle')
BRIEF = ('selectedTreatment', 'selectionReason', 'rejectedTreatment', 'viewerBenefit',
         'hookReasonToWatch', 'payoff')


class MountScan(HTMLParser):
    """Record every composition mount with whether any ancestor carries its own clock."""

    def __init__(self) -> None:
        """Initialize the parsed mount inventory and timing ancestry."""
        super().__init__()
        self.mounts: list[dict] = []
        self.stack: list[tuple[str, bool]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        """Record a mount and retain its ancestor timing state."""
        values = dict(attrs)
        if 'data-composition-src' in values:
            self.mounts.append({**values, '__timed__': any(timed for _tag, timed in self.stack)})
        if tag not in {'meta', 'link', 'img', 'input', 'br', 'hr', 'source', 'area', 'base', 'embed',
                       'wbr', 'param', 'track', 'col'}:
            self.stack.append((tag, 'data-start' in values))

    def handle_endtag(self, tag: str) -> None:
        """Close the matching element and any unclosed descendants."""
        for index in range(len(self.stack) - 1, -1, -1):
            if self.stack[index][0] == tag:
                del self.stack[index:]
                return

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """Self-closing elements never enclose a mount."""
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


def mount_rows(project: Path) -> list[dict]:
    """Parse the executable document once; callers decide which mounts are usable."""
    scan = MountScan()
    scan.feed((project / 'index.html').read_text())
    return scan.mounts


def mount_frames(attributes: dict, rate: Fraction) -> tuple[int, int] | None:
    """The pinned runtime's render-seek bounds: floor(seconds * fps + 1e-9) on IEEE doubles."""
    start, duration = attributes.get('data-start'), attributes.get('data-duration')
    if not all(isinstance(value, str) and DECIMAL.fullmatch(value) for value in (start, duration)) \
            or 'data-end' in attributes or 'data-hidden' in attributes or rate.denominator != 1:
        return None
    begin, fps = float(start), float(rate)
    return math.floor(begin * fps + 1e-9), math.floor((begin + float(duration)) * fps + 1e-9)


def validate_row(row: dict, mounts: list[dict], clock: tuple[Fraction, int]) -> None:
    """A generated row must name one unique root-clock mount and its exact render interval."""
    rate, total = clock
    require(type(row) is dict and set(row) == {'id', 'file', 'startFrame', 'endFrame', 'isolation'},
            'invalid native review region row')
    match = REGION_FILE.fullmatch(row['file']) if isinstance(row['file'], str) else None
    require(match is not None and row['id'] == match[1] and not row['id'].startswith('project-'),
            'review region identity must be its composition file stem')
    actual = [mount for mount in mounts if mount['data-composition-src'] == row['file']]
    require(len(actual) == 1 and not actual[0]['__timed__']
            and mount_frames(actual[0], rate) == (row['startFrame'], row['endFrame'])
            and type(row['startFrame']) is int and type(row['endFrame']) is int
            and 0 <= row['startFrame'] < row['endFrame'] <= total,
            'review region must cover its one actual root-clock composition mount')
    isolation = row['isolation'] if type(row['isolation']) is dict else {}
    scoped = set(isolation) == {'status', 'rule', 'globalSha256'} and isolation['status'] == 'scoped' \
        and isolation['rule'] == ISOLATION_RULE and isinstance(isolation['globalSha256'], str) \
        and re.fullmatch(r'[0-9a-f]{64}', isolation['globalSha256']) is not None
    unproven = set(isolation) == {'status', 'reason'} and isolation['status'] == 'global' \
        and isinstance(isolation['reason'], str)
    require(scoped or unproven, 'review region isolation verdict is malformed')


def region_map(project: Path, canvas: dict) -> list[dict]:
    """Read the generated schema-2 map; absent means one whole-project dependency unit."""
    file = project / REGIONS
    if not file.exists():
        return []
    mapping = bound_json(file)
    require(set(mapping) == {'schemaVersion', 'derivation', 'units'} and mapping['schemaVersion'] == 2
            and mapping['derivation'] == DERIVATION and isinstance(mapping['units'], list)
            and 1 <= len(mapping['units']) <= 128, 'invalid native Short review region map')
    return checked_rows(project, mapping['units'], canvas)


def checked_rows(project: Path, rows: list[dict], canvas: dict) -> list[dict]:
    """Validate rows against the executable mounts; also used by read-only replays."""
    mounts, clock = mount_rows(project), (Fraction(canvas['frameRate']), canvas['totalFrames'])
    for row in rows:
        validate_row(row, mounts, clock)
    require(len({row['id'] for row in rows}) == len(rows), 'duplicate native review region')
    return rows


def plan_projection(plan: dict, local: set[str]) -> dict:
    """Executable plan fields plus the editorial brief; paths and derived hashes are omitted."""
    projection = {key: plan.get(key) for key in EXECUTABLE_PLAN}
    projection['assets'] = [{key: row.get(key) for key in ('file', 'role', 'sha256')}
                            for row in plan.get('assets', [])]
    projection['catalogFiles'] = [{'file': row.get('file'), 'catalogId': row.get('catalogId'),
                                   'sha256': None if row.get('file') in local else row.get('sha256')}
                                  for row in plan.get('catalogFiles', [])]
    strategy, sources = plan.get('strategy') or {}, plan.get('visualSources') or {}
    story = strategy.get('story') or {}
    projection['brief'] = {**{key: strategy.get(key) for key in BRIEF},
                           'story': {key: story.get(key) for key in ('viewerQuestion', 'payoff', 'continuity')},
                           'requestSha256': (plan.get('requestPacket') or {}).get('sha256'),
                           'visualSourceDecisions': sources.get('decisions')}
    return projection


def shared_inputs(project: Path, plan: dict, rows: list[dict]) -> dict:
    """Hash every executable file by content; scoped compositions contribute only global parts."""
    scoped = {row['file']: row['isolation']['globalSha256'] for row in rows if row['isolation']['status'] == 'scoped'}
    unproven = {row['file'] for row in rows} - set(scoped)
    shared = {}
    files, _directories = inventory(project)
    for file in files:
        relative = file.relative_to(project).as_posix()  # Map rows use HTML-style separators on every OS.
        if relative in NON_EXECUTABLE:
            continue
        if relative == 'SHORT-PROJECT.json':
            shared[relative] = digest(plan_projection(plan, set(scoped) | unproven))
        elif relative == 'PREPARED-SOURCES.json':
            shared[relative] = digest({key: value for key, value in bound_json(file).items() if key != 'package'})
        elif relative in scoped:
            shared[relative] = {'isolation': ISOLATION_RULE, 'global': scoped[relative]}
        else:
            shared[relative] = file_digest(file)  # Unproved isolation makes every byte a global dependency.
    return shared


def short_packet(request: dict, rows: list[dict] | None = None) -> dict:
    """Schema-2 packet: logical subject, content shared hash, units and risk events."""
    from studio.native_preview_events import risk_events
    from studio.native_preview_schedule import SCHEDULE_RULE, dependency_units
    from studio.native_review_regions import implementation_digest
    project = Path(request['project'])
    plan = bound_json(project / 'SHORT-PROJECT.json')
    canvas = plan['canvas']
    rows = region_map(project, canvas) if rows is None else checked_rows(project, rows, canvas)
    shared = shared_inputs(project, plan, rows)
    shared['runtime'] = digest({key: request.get(key) for key in
                                ('runtime', 'tools', 'captureMode', 'sourceCacheMode', 'audioProfile')})
    shared['implementation'] = implementation_digest(request)
    base = digest(shared)
    events = risk_events(plan, rows, mount_rows(project))
    sources = {row['file']: file_digest(project / row['file']) for row in rows}
    return {'schemaVersion': 2, 'scope': 'native-preview-dependencies-not-editorial-approval',
            'subject': packet_subject(project), 'canvas': canvas, 'sharedHash': base,
            'scheduleRule': SCHEDULE_RULE, 'events': events,
            'units': dependency_units(rows, (canvas, base), sources, events)}
