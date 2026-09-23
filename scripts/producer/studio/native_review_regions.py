"""Conservative scene dependencies for bounded previews, never final-QC authority."""
from __future__ import annotations

import re
import json
import html
from copy import deepcopy
from fractions import Fraction
from html.parser import HTMLParser
from pathlib import Path

from cut_preview_io import bound_json, digest
from studio.native_preflight_inputs import inventory
from studio.native_runtime import digest as file_digest

REGIONS = 'REVIEW-REGIONS.json'
GENERATED = {'PROJECT-MANIFEST.json', 'PREBUILD-REVIEW.json'}
VOID_TAGS = {'meta', 'link', 'img', 'input', 'br', 'hr', 'source', 'area', 'base', 'embed', 'wbr', 'param', 'track', 'col'}


class Mounts(HTMLParser):
    """Inspect literal composition mounts; nested timed mounts stay global."""

    def __init__(self) -> None:
        super().__init__()
        self.rows: list[dict] = []
        self.timed: list[tuple[str, bool]] = []

    def handle_starttag(self, tag: str, attrs: list) -> None:
        values = dict(attrs)
        if 'data-composition-src' in values:
            if any(timed for _tag, timed in self.timed):
                raise ValueError('Review regions require root-clock composition mounts')
            self.rows.append(values)
        if tag not in VOID_TAGS:
            self.timed.append((tag, 'data-start' in values and values.get('data-start') != '0'))

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self.timed) - 1, -1, -1):
            if self.timed[index][0] == tag:
                del self.timed[index:]
                return

    def handle_startendtag(self, tag: str, attrs: list) -> None:
        """Self-closing elements cannot corrupt the enclosing timing scope."""
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)


def region_rows(project: Path, canvas: dict) -> list[dict]:
    """Require exact local files and their actual complete mounted time intervals."""
    file = project / REGIONS
    if not file.exists():
        return []
    mapping = bound_json(file)
    if set(mapping) != {'schemaVersion', 'units'} or mapping['schemaVersion'] != 1:
        raise ValueError('Invalid native review region map')
    rows = mapping['units']
    if not isinstance(rows, list) or not 1 <= len(rows) <= 256:
        raise ValueError('Review regions require 1–256 units')
    mounts = Mounts()
    mounts.feed((project / 'index.html').read_text())
    rate, total = Fraction(canvas['frameRate']), canvas['totalFrames']
    seen: set[str] = set()
    for row in rows:
        validate_region(row, (project, mounts.rows), (rate, total), seen)
    return rows


def validate_region(row: dict, sources: tuple, clock: tuple, seen: set[str]) -> None:
    """Validate one dependency declaration against executable mount attributes."""
    project, mounts = sources
    rate, total = clock
    if set(row) != {'id', 'file', 'startFrame', 'endFrame'} or not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}', row['id']) \
            or row['id'].startswith('project-context-'):
        raise ValueError('Invalid review region identity')
    start, end, relative = row['startFrame'], row['endFrame'], row['file']
    if row['id'] in seen or type(start) is not int or type(end) is not int or not 0 <= start < end <= total:
        raise ValueError('Invalid review region interval or duplicate ID')
    seen.add(row['id'])
    file = project / relative
    if not re.fullmatch(r'compositions/[a-zA-Z0-9_.-]+\.html', relative) or file.resolve() != file or not file.is_file():
        raise ValueError('Review region requires a canonical local composition')
    actual = [mount for mount in mounts if mount['data-composition-src'] == relative]
    if len(actual) != 1 or Fraction(actual[0].get('data-start', '-1')) * rate != start \
            or Fraction(actual[0].get('data-duration', '-1')) * rate != end - start:
        raise ValueError('Review region must cover its one actual complete composition mount')


def global_markup(file: Path) -> str:
    """Keep executable structure global; declared instance values and literal copy are local."""
    text = file.read_text()
    def variables(match: re.Match) -> str:
        values = json.loads(html.unescape(match.group(2)))
        if not isinstance(values, list) or any(not isinstance(row, dict) for row in values):
            raise ValueError('Native review requires a typed composition variable declaration')
        schema = [{key: value for key, value in row.items() if key != 'default'} for row in values]
        return 'data-composition-variables=' + match.group(1) + html.escape(json.dumps(schema)) + match.group(1)
    text = re.sub(r"data-composition-variables\s*=\s*([\"'])(.*?)\1", variables, text, flags=re.S)
    # Preserve script/style bodies verbatim, including strings and selector dependencies.
    blocks: list[str] = []

    def retain(match: re.Match) -> str:
        blocks.append(match.group())
        return f'<sniper-global-block-{len(blocks)}/>'

    structure = re.sub(r'<(script|style)\b[^>]*>.*?</\1\s*>', retain, text, flags=re.S | re.I)
    structure = re.sub(r'>[^<]*<', '><', structure)
    return digest({'structure': structure, 'executable': blocks})


def short_metadata(plan: dict, local: set[str]) -> str:
    """Separate generated approval pins from pixels; full-plan admission still checks them."""
    authored = deepcopy(plan)
    authored.pop('prebuildReview', None)
    if 'visualSources' in authored:
        authored['visualSources'] = source_decisions(authored['visualSources'])
    for row in authored.get('catalogFiles', []):
        if row['file'] in local:
            row.pop('sha256', None)
    return digest(authored)


def source_decisions(receipt: dict) -> dict:
    """Keep current intent/reference/catalog choices global without the subject-hash cycle."""
    value = deepcopy(receipt)
    value.pop('subjectSha256', None)
    return value


def region_packet(request: dict) -> dict:
    """Bind all unassigned inputs globally and only declared literal-copy files locally."""
    project = Path(request['project'])
    long = request.get('adapter') == 'native-long'
    plan = bound_json(project / ('LONG-PROJECT.json' if long else 'SHORT-PROJECT.json'))
    canvas = plan['canvas']
    rows = region_rows(project, canvas)
    local = {row['file'] for row in rows}
    files, _directories = inventory(project)
    shared = {}
    for file in files:
        relative = str(file.relative_to(project))
        if relative in GENERATED:
            continue  # Existing source and whole-plan review admission checks these separately.
        if relative == 'SHORT-PROJECT.json':
            shared[relative] = short_metadata(plan, local)
        elif relative == 'VISUAL-SOURCES.json':
            shared[relative] = digest(source_decisions(bound_json(file)))
        else:
            shared[relative] = global_markup(file) if relative in local else file_digest(file)
    shared['runtime'] = digest({key: request.get(key) for key in ('runtime', 'tools', 'captureMode', 'sourceCacheMode', 'audioProfile')})
    # Pin invoked code and dependencies too, without introducing a review-receipt cycle.
    repo = Path(__file__).resolve().parents[3]
    roots = [repo / name for name in ('scripts', 'src', 'schemas')]
    roots.append(Path(request['runtime']))
    shared['implementation'] = digest({name: sha for name, sha in request['pins'].items()
                                       if any(Path(name).is_relative_to(root) for root in roots)
                                       or name in request['tools'].values()})
    base = digest(shared)
    units = dependency_units(rows, project, canvas, base)
    return {'schemaVersion': 1, 'scope': 'native-preview-dependencies-not-editorial-approval',
            'project': str(project), 'canvas': canvas, 'sharedHash': base, 'units': units}


def dependency_units(rows: list[dict], project: Path, canvas: dict, base: str) -> list[dict]:
    """Bind every graphic visible in a unit's preview, including contextual neighbors."""
    total, rate = canvas['totalFrames'], Fraction(canvas['frameRate'])
    if not rows:
        return [{'id': 'project', 'startFrame': 0, 'endFrame': total, 'hash': base}]
    span = max(1, round(rate * 4))
    positions = sorted({0, max(0, total // 2 - span // 2), max(0, total - span)})
    contexts = [{'id': f'project-context-{index}', 'startFrame': start,
                 'endFrame': min(total, start + span)} for index, start in enumerate(positions)]
    sources = {row['file']: file_digest(project / row['file']) for row in rows}
    units = []
    for row in [*contexts, *rows]:
        probe = {'canvas': canvas, 'units': [{**row, 'hash': 'changed'}]}
        windows = preview_windows(probe)
        dependencies = {other['file']: sources[other['file']] for other in rows
                        if any(other['startFrame'] < window['endFrame']
                               and window['startFrame'] < other['endFrame'] for window in windows)}
        units.append({'id': row['id'], 'startFrame': row['startFrame'], 'endFrame': row['endFrame'],
                      'hash': digest({'shared': base, 'region': row, 'sources': dependencies})})
    return units


def preview_windows(packet: dict, previous: dict | None = None) -> list[dict]:
    """Merge changed regions plus two seconds of context; bound long regions by samples."""
    old = {row['id']: row['hash'] for row in (previous or {}).get('units', [])}
    rate = Fraction(packet['canvas']['frameRate'])
    pad, maximum = max(1, round(rate * 2)), max(1, round(rate * 12))
    total = packet['canvas']['totalFrames']
    spans = []
    for row in packet['units']:
        if old.get(row['id']) == row['hash']:
            continue
        start, end = max(0, row['startFrame'] - pad), min(total, row['endFrame'] + pad)
        if end - start <= maximum:
            spans.append((start, end))
        else:
            for point in (start, (start + end) // 2, max(start, end - 2 * pad)):
                spans.append((max(start, point), min(end, point + 2 * pad)))
    merged: list[list[int]] = []
    for start, end in sorted(set(spans)):
        if merged and start <= merged[-1][1] and max(end, merged[-1][1]) - merged[-1][0] <= maximum:
            merged[-1][1] = max(end, merged[-1][1])
        else:
            merged.append([start, end])
    return [{'startFrame': start, 'endFrame': end} for start, end in merged]
