"""What a hand-off binds: the delivered MP4, the project files its delivery bound, receipts, findings.

The delivered output is labeled by the review player's own evaluator (``review_player_inventory``):
CHECKED FOR REVIEW (a technical pass; editorial approval is check-final's to report) only when the
maintained receipt reader re-verifies now, a draft always a draft. Each
evaluation uses fresh caches, because a cached admission is keyed by the delivery and MP4 alone
and would hide a changed project. The executable identity is every project file the delivery's
immutable request pins, the top-level authored sources whose set and bytes the receipt readers
compare, and every visible ``.html``/``.htm`` file (Studio stamps any composition it previews,
pinned or not). Nothing follows a link: a linked or special file, or a linked folder anywhere in
the project, is named in the identity (never hashed or walked through) and differs from the delivery.
"""
from __future__ import annotations

import hashlib
import os
import stat
from pathlib import Path

from cross_runtime_canonical_json import canonical_compact_json
from cut_preview_io import bound_json, real_directory
from studio.native_preflight_inputs import runtime_record
from studio.native_runtime import digest
from studio.review_player_inventory import Attempt, Evaluator, attempt_folder

ATTEMPT_ID = 'HandOff'
MAX_FINDINGS = 64
NOT_REGULAR = 'not-a-regular-file'
LINKED_FOLDER = 'linked-folder'
SOURCE_SUFFIXES = {'.html', '.js', '.css', '.json'}
MARKUP_SUFFIXES = {'.html', '.htm'}


def require(value: bool, message: str) -> None:
    """Refuse a hand-off that cannot bind what it must show."""
    if not value:
        raise ValueError(f'Hand-off: {message}')


def evaluate(attempt: Path) -> dict:
    """The review player's label, playability and receipt result for this attempt, computed afresh.

    An attempt that is no longer playable has no receipt result; its label is the reason.
    """
    row = Evaluator().evaluate(Attempt(ATTEMPT_ID, 'hand-off', attempt))
    return {'receipts': {'verified': None, 'reason': row['label']}, **row}


def delivered(attempt: Path) -> tuple[dict, dict, Path]:
    """Admit a playable delivered attempt and its canonical project before any view opens."""
    attempt = attempt_folder(str(attempt))
    real_directory(attempt)
    row = evaluate(attempt)
    require(row['playable'] is True, f"nothing deliverable to hand off: {row['label']}"
            + (f" ({row['detail']})" if row.get('detail') else ''))
    request = bound_json(attempt / 'export-request.json')
    project = Path(request['project'])
    real_directory(project)
    require((project / 'index.html').is_file(), 'the delivered project has no index.html to open in Studio')
    return row, request, project


def admit_record(record: Path, protected: tuple[Path, ...]) -> Path:
    """A fresh record file outside the delivered attempt and project, checked before any view opens."""
    record = record.absolute()
    real_directory(record.parent)
    require(not record.exists() and not record.is_symlink(), 'the record path already exists')
    require(not any(record.is_relative_to(root) for root in protected),
            'the record must be written outside the delivered attempt and project')
    return record


def mp4_binding(row: dict, delivery: dict) -> dict:
    """The exact delivered bytes the review player verified against the delivery receipt."""
    require(row['sha256'] == delivery.get('sha256') and row['file'] == delivery.get('output'),
            'the MP4 differs from its delivery receipt')
    return {'path': row['file'], 'sha256': row['sha256'], 'bytes': row['bytes'],
            'durationSeconds': row['durationSeconds'], 'matchesDelivery': True}


def bound_files(project: Path, request: dict) -> dict[str, str]:
    """Every project file the delivery's immutable request pins, by relative name."""
    pins = request.get('pins')
    require(isinstance(pins, dict) and bool(pins), 'the delivery request has no pinned inputs')
    return {str(Path(name).relative_to(project)): sha for name, sha in sorted(pins.items())
            if Path(name) != project and Path(name).is_relative_to(project)}


def _current(project: Path, name: str) -> str | None:
    """A file's bytes without following links: None when missing, named when linked or not regular."""
    file = project / name
    try:
        info = os.lstat(file)
    except FileNotFoundError:
        return None
    if not stat.S_ISREG(info.st_mode) or file.resolve() != file:
        return NOT_REGULAR
    return digest(file)


def _top_level_sources(project: Path) -> set[str]:
    """Top-level authored-source names the receipt readers compare (runtime records excluded)."""
    with os.scandir(project) as entries:
        return {entry.name for entry in entries if Path(entry.name).suffix in SOURCE_SUFFIXES
                and not entry.is_dir(follow_symlinks=False) and not runtime_record(entry.name, True)}


def _walk(project: Path) -> tuple[set[str], set[str]]:
    """Visible markup files and linked folders, never descending into links, hidden folders or node_modules."""
    markup, linked = set(), set()
    for folder, dirs, files in os.walk(project, followlinks=False):
        base = Path(folder).relative_to(project)
        linked |= {str(base / name) for name in dirs if (Path(folder) / name).is_symlink()}
        dirs[:] = [name for name in dirs if not name.startswith('.') and name != 'node_modules'
                   and not (Path(folder) / name).is_symlink()]
        markup |= {str(base / name) for name in files if Path(name).suffix.lower() in MARKUP_SUFFIXES
                   and not name.startswith('.')}
    return markup, linked


def identity(project: Path, bound: dict[str, str]) -> dict:
    """Hash the bound files, top-level sources and every visible markup file exactly as they are now."""
    markup, linked = _walk(project)
    files = {name: _current(project, name) for name in sorted({*bound, *_top_level_sources(project), *markup})}
    files.update({name: LINKED_FOLDER for name in linked})
    files = dict(sorted(files.items()))
    return {'sha256': hashlib.sha256(canonical_compact_json(files).encode()).hexdigest(), 'files': files}


def changed(before: dict, after: dict) -> list[str]:
    """Names whose bytes, presence or membership differ between two identities."""
    names = before['files'].keys() | after['files'].keys()
    return sorted(name for name in names if before['files'].get(name) != after['files'].get(name))


def differs_from_delivery(bound: dict[str, str], snapshot: dict) -> list[str]:
    """Pinned project files whose bytes are not the ones the delivery bound, and every linked folder."""
    linked = [name for name, value in snapshot['files'].items() if value == LINKED_FOLDER]
    return sorted({*(name for name, sha in bound.items() if snapshot['files'].get(name) != sha), *linked})


def open_findings(delivery: dict) -> list:
    """The delivery's open findings, bounded; checked before any view opens."""
    findings = delivery.get('openFindings') or []
    require(isinstance(findings, list) and len(findings) <= MAX_FINDINGS
            and all(isinstance(row, dict) for row in findings), 'malformed open findings in the delivery')
    return findings


def output_state(row: dict, delivery: dict, findings: list) -> dict:
    """The visible checked/draft label and open findings; execution review never speaks for content approval."""
    return {'deliveryStatus': delivery.get('status'), 'reviewState': row['kind'], 'label': row['label'],
            'openFindings': findings, 'notes': row['notes'], 'executionReview': {
                'scope': 'review of this render\'s visual and technical execution, not of the approved title/script',
                'editorialReview': delivery.get('editorialReview') or 'not-recorded-in-delivery',
                'humanApprovedRenderedOutput': delivery.get('humanApproved') is True}}


def pending_findings(file: Path | None) -> dict:
    """Findings still open at hand-off (critics pending or unresolved), bound to their file."""
    if file is None:
        return {'findings': [], 'source': None}
    from studio.native_short_draft_export import supplied_findings
    rows, binding = supplied_findings(file)
    return {'findings': [{**row, 'source': 'handoff-pending-findings'} for row in rows], 'source': binding}
