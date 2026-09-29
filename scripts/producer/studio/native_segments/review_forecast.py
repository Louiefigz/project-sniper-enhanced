"""Conservative existing-rate forecast and fixed owner-space admission for review packages.

The model charges the existing final-processing rate for every review package's
whole continuous duration. It is deliberately not a measured remux speed claim.
No original clock, launch counter or storage ceiling is changed.
"""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from studio.native_budget_family_state import require
from studio.native_budget_forecast import route_seconds
from studio.native_budget_section_schema import MAX_SECTION_OWNERS
from studio.native_segments.long_plan import identity, initial_long_plan


def project_work(project: Path, context: dict) -> dict | None:
    """Cold derive the full expected package inventory before any counted family is charged."""
    from studio.native_long_chunks import chunk_admission, read_chunk_contract
    from studio.native_segments.review_scopes import declared_scopes
    contract = read_chunk_contract(project)
    if contract is None:
        return None
    require(contract['context'] == context, 'review forecast assignment authority changed')
    geometry = contract['geometry']
    revision = initial_long_plan(geometry['canvas'], identity(geometry['canvas']), geometry['encoderBoundaries'])
    request = {'sectionProduction': context, 'sectionChunks': chunk_admission(contract), 'revision': revision}
    scopes = declared_scopes(request)
    rate = Fraction(geometry['canvas']['frameRate'])
    return {'scopes': scopes, 'seconds': {row['id']: float(Fraction(row['frameRange'][1] - row['frameRange'][0]) / rate)
                                        for row in scopes}, 'windows': len(revision['renderWindows'])}


def package_seconds(work: dict | None, rates: dict, section_id: str | None = None) -> float:
    """Use existing conservative rates, including one startup per exact scope."""
    if work is None:
        return 0.0
    scopes = work['scopes'] if section_id == '*' else [row for row in work['scopes']
             if (len(row['sectionIds']) > 1 if section_id is None else row['sectionIds'] == [section_id])]
    return sum(route_seconds(rates, 'final', work['seconds'][row['id']]) for row in scopes)


def require_owner_room(clip: dict, settings: dict) -> None:
    """Refuse an impossible fixed work inventory before expensive media or launch debits."""
    work = settings.get('reviewWork')
    if work is None:
        return
    previews = sum(len(row['windows']) for row in settings['previewInventory'])
    members = len(settings['context']['assignments']) + 1
    required = 2 * work['windows'] + len(work['scopes']) + 2 * previews + 2 * members + 3
    require(len(clip.get('sectionOwners', [])) + required <= MAX_SECTION_OWNERS,
            'Frozen section and review-package inventory exceeds existing owner-history capacity')


def pending_work(family: dict) -> dict | None:
    """Recover declared demand from a frozen real invocation, not a guessed duration."""
    from studio.production.section_plan import read_plan
    if not family['invocations']:
        return None
    project = Path(family['invocations'][0]['project'])
    if not (project / 'LONG-CHUNKS.json').is_file():
        return None
    context = read_plan(Path(family['plan']['path']))
    return project_work(project, context)


def preview_ranges(project: Path, context: dict, section_id: str | None, windows: list[dict]) -> list[dict]:
    """Freeze continuous authored transition context before preview-family admission.

    Ordinary region samples remain useful, but a protected transition is never
    replaced with disconnected samples merely because it is longer than twelve seconds.
    """
    work = project_work(project, context)
    if work is None:
        return windows
    scopes = [row for row in work['scopes'] if row['kind'] != 'chunk'
              and (len(row['sectionIds']) > 1 if section_id is None else row['sectionIds'] == [section_id])]
    spans = [[row['startFrame'], row['endFrame']] for row in windows] + [row['frameRange'] for row in scopes]
    merged = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    require(len(merged) <= 768, 'continuous authored preview inventory exceeds its existing bound')
    return [{'startFrame': start, 'endFrame': end} for start, end in merged]
