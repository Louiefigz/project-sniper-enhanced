"""Recorded independent section QC and a frozen assembly barrier, never automatic approval.

Existing prebuild and moving-preview review admission still applies. This layer
binds section judgments to the encoded picture and exact full-master PCM. Task
identity, watching and listening are reviewer declarations, not authenticated
observations; the engine verifies current bytes, scope and required records.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_runtime import digest
from studio.native_segments.owners import current_window, revision_windows
from studio.native_stage_evidence import require

CHECKS = frozenset({'sourceFidelity', 'captions', 'visuals', 'motion', 'audio', 'neighboringContext'})


class SectionReviewPending(RuntimeError):
    """Preserve completed section seals while the operator records independent QC."""

    category = 'section-review-pending'
    phase = 'section-review'


def review_pins(file: Path) -> dict[str, str]:
    """Pin the supplied judgments and actual referenced media/evidence before registration."""
    bundle = bound_json(file)
    require(bundle.get('schemaVersion') == 1 and isinstance(bundle.get('reviews'), list)
            and 0 < len(bundle['reviews']) <= 768, 'invalid section review bundle')
    pins = {str(file): digest(file)}
    for row in bundle['reviews']:
        for reference in [row['media'], *row['evidence']]:
            require(set(reference) == {'path', 'sha256'} and Path(reference['path']).is_absolute(),
                    'invalid section review evidence binding')
            require(Path(reference['path']).resolve(strict=True) == Path(reference['path'])
                    and not Path(reference['path']).is_symlink(), 'section evidence path is not canonical')
            require(digest(Path(reference['path'])) == reference['sha256'], 'section review evidence changed')
            pins[reference['path']] = reference['sha256']
    return pins


def validate_review(row: dict, window: dict, piece: dict, audio: dict | None = None) -> None:
    """Require separate recorded authorship and current complete assigned-section judgments."""
    require(row.get('sectionId') == window['id'] and row.get('generation') == window['generation']
            and row.get('inputIdentity') == window['inputIdentity']
            and row.get('frameRange') == [window['startFrame'], window['endFrame']]
            and row.get('media', {}).get('sha256') == piece['sha256'], 'stale section review')
    author, reviewer = row.get('authorTaskId'), row.get('reviewerTaskId')
    require(isinstance(author, str) and bool(author.strip()) and isinstance(reviewer, str)
            and bool(reviewer.strip()) and author != reviewer, 'section QC requires an independent reviewer')
    checks = row.get('checks')
    require(row.get('status') == 'pass' and isinstance(checks, dict) and set(checks) == CHECKS
            and all(value is True for value in checks.values()) and bool(row.get('evidence')),
            'section QC has missing or failing assigned checks')
    assessments = row.get('assessments')
    require(isinstance(assessments, dict) and set(assessments) == CHECKS
            and all(isinstance(value, str) and 0 < len(value.strip()) <= 2000
                    for value in assessments.values()), 'section QC needs specific recorded assessments')
    validate_observations(row, window, piece, audio)


def validate_observations(row: dict, window: dict, piece: dict, audio: dict | None) -> None:
    """Require recorded playback/listening of exact media; the engine cannot prove an observer watched."""
    observations = row.get('observations')
    require(isinstance(observations, list) and len(observations) == 2 and audio is not None,
            'section QC needs exact encoded playback and audio listening records')
    by_kind = {item.get('kind'): item for item in observations}
    require(set(by_kind) == {'encoded-playback', 'audio-listening'}, 'section QC evidence types differ')
    references = {item['path']: item['sha256'] for item in row['evidence']}
    for kind, media in (('encoded-playback', piece), ('audio-listening', audio)):
        item = by_kind[kind]
        require(item.get('sha256') == media['sha256'] and references.get(item.get('path')) == media['sha256']
                and item.get('frameRange') == [window['startFrame'], window['endFrame']],
                'section observation does not bind complete current media')


def assembly_snapshot(request: dict, production_record: dict | None = None) -> dict:
    """Accept every required current seal and its pinned independent review, without omissions."""
    from studio.native_export_history import require_current_section_attempt
    require_current_section_attempt(request)
    if request.get('sectionProduction'):
        return registered_snapshot(request, production_record)
    file = request.get('sectionReviews')
    if not file:
        raise SectionReviewPending('All completed sections remain saved. Record independent section QC '
                                   'and resume with --section-reviews; final assembly is blocked.')
    pins = review_pins(Path(file))
    require(all(request['pins'].get(path) == sha for path, sha in pins.items()),
            'section reviews were not frozen before export')
    require(bound_json(Path(request['output']) / 'export-request.json')['revision'] == request['revision'],
            'section generation changed after request publication')
    rows = bound_json(Path(file))['reviews']
    windows = revision_windows(request)
    require(len(rows) == len(windows) and len({row['sectionId'] for row in rows}) == len(rows),
            'section reviews omit or duplicate required sections')
    by_id = {row['sectionId']: row for row in rows}
    sections = []
    for window in windows:
        value = current_window(request, f"segment-picture-{window['index']}")
        row = by_id.get(window['id'])
        require(row is not None, 'missing required section QC')
        require(row.get('planIdentity') == request['revision']['identity'],
                'section neighboring-context review belongs to an older plan')
        validate_review(row, window, value['piece'], value.get('audio'))
        sections.append({'window': window, 'sha256': value['piece']['sha256']})
    result = {'planIdentity': request['revision']['identity'], 'sections': sections, 'reviewPins': pins}
    return result


def registered_snapshot(request: dict, production_record: dict | None = None) -> dict:
    """Bind registered independent logical reviews to every current technical window."""
    from studio.production.sections import assembly_task_snapshot
    require(bound_json(Path(request['output']) / 'export-request.json')['revision'] == request['revision'],
            'section generation changed after request publication')
    sections = []
    for window in revision_windows(request):
        value = current_window(request, f"segment-picture-{window['index']}")
        sections.append({'window': window, 'sha256': value['piece']['sha256']})
    return {'planIdentity': request['revision']['identity'], 'sections': sections,
            'production': assembly_task_snapshot(request, production_record)}
