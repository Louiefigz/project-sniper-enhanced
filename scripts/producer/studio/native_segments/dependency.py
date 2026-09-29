"""Picture dependency closure between a delivered ancestor project and its revised project.

The rendered picture is a function of index.html, the compositions and assets it mounts, the
renderer configuration and the canvas clock (frame rate and frame count) that capture reads
from SHORT-PROJECT.json. Everything else a rebuild rewrites (the project manifest, derived
review regions, reports, review references) is classified as not rendered, unless a rendered
document names it, so an ordinary rebuild does not widen a local change to the whole program.
The file inventory is the static preflight's (``native_preflight_inputs.inventory``): Finder
and Studio runtime files (.DS_Store, AppleDouble ``._*``, the Studio server record, the root
.thumbnails/.transcode-cache/.waveform-cache caches, .hyperframes) are not project inputs.

A changed composition is local only when both projects prove it scoped with the same global
parts (``isolation`` equal: status, rule and ``globalSha256``, as ``native_short_regions``
hashes them): a changed @font-face, at-rule, bare ``*`` rule, script or root attribute widens.
Unknown files, renderer configuration, source authority, the picture clock, same-name asset
byte changes and a removed asset the documents still name widen to the whole program with a
stated reason; nothing is widened or narrowed silently. Audio is decided separately by the
sealed audio-input identity.
"""
from __future__ import annotations

import hashlib
import json
from fractions import Fraction
from pathlib import Path

from cut_preview_io import bound_json
from studio.native_preflight_inputs import inventory as project_files
from studio.native_runtime import digest
from studio.native_segments.dom import composition_mounts, timed_changes
from studio.native_stage_evidence import require

PLAN = 'SHORT-PROJECT.json'
LONG_PLAN = 'LONG-PROJECT.json'
REGIONS = 'REVIEW-REGIONS.json'
ENTRY = 'index.html'
NOT_RENDERED = frozenset({'PROJECT-MANIFEST.json', REGIONS, 'ASSET-USE-REPORT.json', 'BRIEF.md',
                          'DIRECTOR-LIBRARY.json', 'PACING-REPORT.json', 'STORY-REPORT.json', 'STORYBOARD.md',
                          'VISUAL-PLAN.json', 'VISUAL-PLAN-APPLICATION.json', 'PREBUILD-REVIEW.json'})
GLOBAL_FILES = {'hyperframes.json': 'renderer configuration changed',
                'PREPARED-SOURCES.json': 'prepared source ranges or authority changed (a cut, trim or source replacement)'}


def inventory(root: Path) -> dict[str, str]:
    """Relative path to digest of every project input (the static preflight's inventory and exclusions)."""
    files, _directories = project_files(root)
    return {file.relative_to(root).as_posix(): digest(file) for file in files}


def documents(project: Path) -> str:
    """The rendered documents' text (index.html and every composition), for finding named paths."""
    parts = [(project / ENTRY).read_text()]
    parts += [file.read_text() for file in sorted((project / 'compositions').glob('*.html'))]
    return '\n'.join(parts)


def canvas_clock(project: Path) -> tuple[str, int]:
    """The picture clock capture reads from the plan: frame rate and frame count."""
    plans = [name for name in (PLAN, LONG_PLAN) if (project / name).is_file()]
    require(len(plans) == 1, 'section project requires exactly one Short or Long plan')
    canvas = bound_json(project / plans[0])['canvas']
    return canvas['frameRate'], canvas['totalFrames']


def unit_row(project: Path, file: str) -> dict | str:
    """The single schema-2 region unit of a composition file, or why there is none."""
    if not (project / REGIONS).is_file():
        return f'{file}: no scoped review-region evidence in {project.name}'
    from studio.native_region_contract import read_region_map
    plan = LONG_PLAN if (project / LONG_PLAN).exists() else PLAN
    try:
        regions = read_region_map(project, bound_json(project / plan)['canvas'])
    except ValueError as error:
        return f'{file}: region isolation could not be rederived: {error}'
    units = [row for row in regions if row.get('file') == file]
    if len(units) != 1 or units[0]['isolation']['status'] != 'scoped':
        return f'{file}: no single scoped isolation proof in {project.name}'
    return units[0]


def composition_ranges(file: str, projects: tuple[Path, Path], rate: Fraction) -> tuple[list, str | None]:
    """Unit and mount ranges of a changed composition proved scoped with unchanged global parts; else a reason."""
    rows = [unit_row(project, file) for project in projects]
    problem = next((row for row in rows if isinstance(row, str)), None)
    if problem:
        return [], problem
    if rows[0]['isolation'] != rows[1]['isolation']:
        return [], (f'{file}: its global parts changed (the isolation proof\'s global hash differs: styles outside '
                    'its host such as @font-face, at-rules or bare *, its scripts or its root attributes)')
    ranges = [[row['startFrame'], row['endFrame']] for row in rows]
    for project in projects:
        ranges += composition_mounts((project / ENTRY).read_text(), file, rate)
    return sorted(ranges), None


def picture_inputs(project: Path, files: dict[str, str], audio: set[str] | None = None) -> str:
    """One digest over every rendered input and the canvas clock (identifies a window's pixels)."""
    rendered = {name: sha for name, sha in files.items()
                if (name == ENTRY or name in GLOBAL_FILES or name.startswith(('compositions/', 'assets/')))
                and name not in (audio or set())}
    value = {'files': rendered, 'clock': list(canvas_clock(project))}
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def classify(name: str, inventories: tuple[dict, dict], named: str,
             audio: set[str] | None = None) -> tuple[str, str]:
    """One changed file's class and reason (``named`` is the text of both projects' rendered documents)."""
    before, after = inventories
    if name in (audio or set()):
        return 'audio-only', 'declared Long audio absent from every rendered document'
    if name in GLOBAL_FILES:
        return 'global', GLOBAL_FILES[name]
    if name == 'LONG-CHUNKS.json' and name not in named:
        return 'long-chunks', 'cold-validated Long chunk and shared transition decisions'
    if name in NOT_RENDERED or name.startswith('references/'):
        if name in named:
            return 'global', 'a file the rendered documents name changed'
        return 'not-rendered', 'derived metadata or review reference; no rendered document names it'
    if name in (PLAN, LONG_PLAN):
        return 'plan', 'plan: only the canvas clock is a picture input'
    if name == ENTRY:
        return 'dom', 'rendered document'
    if name.startswith('compositions/') and name.endswith('.html'):
        return 'composition', 'mounted composition'
    if name.startswith('assets/'):
        return asset_class(name, (before, after), named)
    return 'global', 'unclassified project file'


def asset_class(name: str, inventories: tuple[dict, dict], named: str) -> tuple[str, str]:
    """A changed, removed or added asset: same-name changes and removals still named widen."""
    before, after = inventories
    if name in before and name in after:
        return 'global', 'asset bytes changed under the same name'
    if name not in after and name in named:
        return 'global', 'an asset was removed while a rendered document still names it'
    return 'asset-inventory', 'asset added or removed and no rendered document names it'


def file_ranges(row: dict, projects: tuple[Path, Path], rate: Fraction) -> tuple[list, str | None]:
    """Frame ranges of one changed composition or document; a reason instead when it widens."""
    if row['class'] == 'composition':
        return composition_ranges(row['file'], projects, rate)
    if row['class'] == 'long-chunks':
        from studio.native_long_chunks import chunk_contract_changes
        return chunk_contract_changes(*projects)
    if row['class'] != 'dom':
        return [], None
    diff = timed_changes((projects[0] / ENTRY).read_text(), (projects[1] / ENTRY).read_text(), rate)
    return diff['ranges'], diff['reason'] if diff['global'] else None


def audio_only_files(projects: tuple[Path, Path], named: str) -> set[str]:
    """Exclude only explicit Long audio files with no use in any picture document."""
    files = set()
    for project in projects:
        if not (project / LONG_PLAN).is_file():
            continue
        file = bound_json(project / LONG_PLAN).get('audio', {}).get('file')
        if isinstance(file, str) and file and file not in named:
            require(not Path(file).is_absolute() and '..' not in Path(file).parts,
                    'Long audio file escapes its immutable project')
            files.add(file)
    return files


def picture_changes(parent: Path, child: Path) -> dict:
    """Changed files with their classes, the semantic frame ranges, or a whole-program widening."""
    before, after = inventory(parent), inventory(child)
    named = documents(parent) + '\n' + documents(child)
    names = sorted(name for name in before.keys() | after.keys() if before.get(name) != after.get(name))
    audio = audio_only_files((parent, child), named)
    rows = [dict(zip(('file', 'class', 'reason'),
                    (name, *classify(name, (before, after), named, audio)))) for name in names]
    rate = Fraction(canvas_clock(child)[0])
    reasons, ranges = [row['reason'] + f' ({row["file"]})' for row in rows if row['class'] == 'global'], []
    if any(row['class'] == 'long-chunks' for row in rows):
        from studio.native_long_chunks import chunk_contract_changes
        ranges, reason = chunk_contract_changes(parent, child)
        reasons += [reason] if reason else []
    if canvas_clock(parent) != canvas_clock(child):
        reasons.append('picture clock changed (frame rate or frame count)')
    if names and (parent / LONG_PLAN).exists():
        reason = long_locality_problem(parent) or long_locality_problem(child)
        if reason:
            reasons.append('Long dynamic locality is unsupported: ' + reason)
    for row in rows:
        if reasons:
            break
        if row['class'] == 'long-chunks':
            continue
        found, reason = file_ranges(row, (parent, child), rate)
        reasons += [reason] if reason else []
        ranges += found
    total, identity = canvas_clock(child)[1], picture_inputs(child, after, audio)
    if reasons:
        return {'files': rows, 'global': True, 'reasons': reasons, 'ranges': [[0, total]], 'pictureInputs': identity}
    clipped = [[max(0, start), min(total, end)] for start, end in ranges if start < total and end > 0]
    return {'files': rows, 'global': False, 'reasons': [], 'ranges': merge(clipped), 'pictureInputs': identity}


def long_locality_problem(project: Path) -> str | None:
    """Read the admitted region contract, retaining legacy static inline-only behavior."""
    from studio.native_region_contract import read_region_map, static_problem
    from studio.native_segments.dom import parse
    if not (project / REGIONS).exists():
        return static_problem(parse(documents(project)))
    try:
        rows = read_region_map(project, bound_json(project / LONG_PLAN)['canvas'])
        return next((row['isolation']['reason'] for row in rows if row['isolation']['status'] == 'global'), None)
    except ValueError as error:
        return str(error)


def merge(ranges: list[list[int]]) -> list[list[int]]:
    """Sorted, non-overlapping union of half-open ranges."""
    merged = []
    for start, end in sorted(ranges):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged
