"""A Short's content sections, derived by code from its executable homes (P3a S2 §4.0.2; MASTER-PLAN M-081).

The record stores the derivation; the freeze recomputes it and requires byte equality (``derived_problem``), so the
integration owner never hand-writes a Short content section. The table is ``coordination_catalog.SHORT_DERIVATION``
as X201, X205 and X211 correct it:
- a region entry digests its unit row, its composition's bytes and its catalog rows' dropped fields (F-1, X211(2));
  compositions outside every region form one global entry; without ``REVIEW-REGIONS.json`` they form one global
  ``project`` unit; the regions are the pinned bytes, validated by ``native_short_regions.checked_rows`` (one read);
- ``preparedSources`` (its sha256) joins ``audio-finishing``, ``caption-style`` and every picture view (X211(1));
- a motion covers its tween and the held end pose, to its target cue's end (X211(5));
- the sealed record gives ``sourceFacts`` and the ``speaker-evidence`` framing entry (``plan_short_evidence``);
- every path the table does not derive is a global ``key-<path>`` graphics entry (``plan_short_unlisted``).
An absent optional structure derives a fixed shape (no beats: one beat over the clock; no scenes: no holds or
transitions; no caption groups: only ``caption-style``), never a guess; an unknown writer key stops by name.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import digest
from studio.native_runtime import digest as file_digest
from studio.native_short_regions import DERIVATION, REGIONS, checked_rows
from studio.production.coordination_catalog import PROJECT_UNIT, SHORT_DERIVATION, UNMAPPED_COMPOSITIONS
from studio.production.plan_fields import PREFIX, check, derived_entry, read_pinned_json, refuse
from studio.production.plan_short_evidence import sealed_sections
from studio.production.plan_short_unlisted import catalog_unprojected, prepared_digest, unlisted, vocabulary_problem

CAPTION_STYLE = ('captionCorrections', 'captionMode', 'captionViews', 'captionProtectedPhrases', 'captionSuppressions')
SPEECH = (('occurrencesSha256', 'occurrences'), ('cutsSha256', 'cuts'), ('segmentsSha256', 'segments'))


def occurrence_frames(native_plan: dict, ids: list[int]) -> list[int]:
    """``[first startFrame, last endFrame]`` of a caption group or beat, from ``canvas.occurrences``."""
    rows = {row[0]: row for row in native_plan['canvas']['occurrences']}
    check(bool(ids) and ids[0] in rows and ids[-1] in rows, 'derived', f'occurrences {ids[:4]} are not in the plan')
    return [rows[ids[0]][3], rows[ids[-1]][4]]


def _story(native_plan: dict) -> list[dict]:
    """``strategy.pacing.beats``; no beats derive one beat over the whole clock holding every word."""
    canvas = native_plan['canvas']
    beats = (native_plan['strategy'].get('pacing') or {}).get('beats')
    if not beats:
        words = [row[0] for row in canvas['occurrences']]
        return [{'id': 'beat-0', 'range': [0, canvas['totalFrames']], 'occurrenceIds': words, 'purpose': None,
                 'digest': digest(None)}]
    return [{'id': f'beat-{index}', 'range': [beat['startFrame'], beat['endFrame']],
             'occurrenceIds': list(beat['occurrenceIds']), 'purpose': None, 'digest': digest(beat)}
            for index, beat in enumerate(beats)]


def _scenes(native_plan: dict) -> tuple[list[dict], list[dict]]:
    """Holds (one per scene) and transitions (one per shared scene boundary), from ``strategy.scenes``."""
    scenes = native_plan['strategy'].get('scenes') or []
    holds = [{'id': f'scene-{index}', 'range': [scene['startFrame'], scene['endFrame']],
              'holdFrames': scene['holdFrames'], 'digest': digest(scene)} for index, scene in enumerate(scenes)]
    transitions = [{'id': f'boundary-{index}', 'boundaryFrame': scene['endFrame'],
                    'range': [scene['startFrame'], after['endFrame']], 'digest': digest([scene, after])}
                   for index, (scene, after) in enumerate(zip(scenes, scenes[1:]))
                   if scene['endFrame'] == after['startFrame']]
    return holds, transitions


def _captions(native_plan: dict, prepared: str | None) -> list[dict]:
    """One entry per caption group (frames of its first and last word) and one whole-output ``caption-style``."""
    canvas = native_plan['canvas']
    rows = {row[0]: row for row in canvas['occurrences']}
    groups = [derived_entry(f'group-{index}', occurrence_frames(native_plan, group),
                            {'group': group, 'words': [rows[item] for item in group]})
              for index, group in enumerate(canvas['captionGroups'])]
    style = {**{key: canvas.get(key) for key in CAPTION_STYLE}, 'prepared': prepared}
    return [*groups, derived_entry('caption-style', None, style)]


def _compositions(project: Path) -> dict[str, str]:
    """Every ``compositions/*.html`` file of the project with its content digest."""
    folder = project / 'compositions'
    files = sorted(folder.glob('*.html')) if folder.is_dir() else []
    return {file.relative_to(project).as_posix(): file_digest(file) for file in files}


def _regions(native_plan: dict, project: Path, rows: list[dict]) -> list[dict]:
    """Region units (unit row, composition bytes, dropped catalog fields), then compositions no region covers."""
    files = _compositions(project)
    if not rows:
        return [{'id': PROJECT_UNIT, 'range': None, 'isolation': 'global', 'digest': digest(files)}]
    catalog = catalog_unprojected(native_plan, {row['file'] for row in rows})
    units = [{'id': f'region-{index}', 'range': [row['startFrame'], row['endFrame']],
              'isolation': 'scoped' if row['isolation']['status'] == 'scoped' else 'global',
              'digest': digest({'unit': row, 'bytes': file_digest(project / row['file']), 'catalog': catalog.get(row['file'])})}
             for index, row in enumerate(rows)]
    unmapped = {name: sha for name, sha in files.items() if name not in {row['file'] for row in rows}}
    extra = [{'id': UNMAPPED_COMPOSITIONS, 'range': None, 'isolation': 'global', 'digest': digest(unmapped)}]
    return units + (extra if unmapped else [])


def _motion_range(canvas: dict, motion: dict) -> list[int]:
    """The tween and its held end pose: from the motion's start to its target cue's end (X211(5))."""
    target = next((cue for cue in [*canvas['text'], *canvas['shapes']] if cue['id'] == motion['id']), None)
    end = motion['startFrame'] + motion['durationFrames']
    check(target is not None and target['startFrame'] <= motion['startFrame'] and end <= target['endFrame'], 'derived',
          f'motion {motion["id"]!r} has no text or shape cue whose window holds it (the writer refuses it too)')
    return [motion['startFrame'], target['endFrame']]


def _graphics(native_plan: dict, project: Path, rows: list[dict]) -> list[dict]:
    """Regions, then the canvas title card, text, shapes and motion (scoped), visual sources, and unlisted keys."""
    canvas, cues = native_plan['canvas'], []
    if canvas.get('titleCard') is not None:
        cues.append(derived_entry('title-card', [0, canvas['titleCard']['endFrame']], canvas['titleCard']))
    for name, key in (('text', 'text'), ('shape', 'shapes')):
        cues += [derived_entry(f'{name}-{index}', [row['startFrame'], row['endFrame']], row)
                 for index, row in enumerate(canvas[key])]
    cues += [derived_entry(f'motion-{index}', _motion_range(canvas, row), row) for index, row in enumerate(canvas['motion'])]
    cues.append(derived_entry('visual-sources', None, (native_plan.get('visualSources') or {}).get('decisions')))
    keys = [{'id': f'key-{path}', 'range': None, 'isolation': 'global', 'digest': digest(value)}
            for path, value in sorted(unlisted(native_plan, {row['file'] for row in rows}).items())]
    return _regions(native_plan, project, rows) + [{**cue, 'isolation': 'scoped'} for cue in cues] + keys


def _region_rows(homes: dict, project: Path, canvas: dict) -> list[dict]:
    """The pinned REVIEW-REGIONS.json's units, validated against the executable mounts (one read, the pinned bytes)."""
    check((homes['regions'] is not None) == (project / REGIONS).is_file(), 'derived',
          'regions must be pinned exactly when the project has REVIEW-REGIONS.json')
    if homes['regions'] is None:
        return []
    mapping = read_pinned_json(homes['regions'], 'derived')
    check(set(mapping) == {'schemaVersion', 'derivation', 'units'} and mapping['schemaVersion'] == 2
          and mapping['derivation'] == DERIVATION and type(mapping['units']) is list and 1 <= len(mapping['units']) <= 128,
          'derived', 'invalid native Short review region map')
    return checked_rows(project, mapping['units'], canvas)


def short_sections(homes: dict) -> dict:
    """``{clock, speech, story, holds, framing, captions, graphics, transitions, audio, sourceFacts}`` of a Short.

    ``homes`` is a shape-valid Short record's ``homes``; every pin is rehashed and every refusal is named.
    """
    plan = read_pinned_json(homes['nativePlan'], 'derived')
    try:
        return _sections(plan, Path(homes['project']), homes)
    except ValueError as error:
        if str(error).startswith(PREFIX):
            raise
        refuse('derived', f'the native plan or project cannot be derived: {error}')
    except (KeyError, TypeError, IndexError, AttributeError, ZeroDivisionError, RuntimeError, OSError) as error:
        refuse('derived', f'the native plan is not a well-formed native Short plan ({type(error).__name__}: {error})')


def _sections(plan: dict, project: Path, homes: dict) -> dict:
    """The derivation proper, over a read native plan."""
    canvas, prepared = plan['canvas'], prepared_digest(plan)
    vocabulary_problem(plan)
    rows = _region_rows(homes, project, canvas)
    holds, transitions = _scenes(plan)
    facts, evidence = sealed_sections(plan, homes['sharedEvidence'])
    views = [derived_entry(f'view-{index}', [row['startFrame'], row['endFrame']], {'view': row, 'prepared': prepared})
             for index, row in enumerate(canvas['pictureViews'])]
    return {'clock': {'frameRate': canvas['frameRate'], 'totalFrames': canvas['totalFrames']},
            'speech': {name: digest(canvas[key]) for name, key in SPEECH},
            'story': _story(plan), 'holds': holds, 'framing': views + evidence,
            'captions': _captions(plan, prepared), 'graphics': _graphics(plan, project, rows), 'transitions': transitions,
            'audio': [derived_entry('audio-finishing', None, {'finishing': plan.get('audioFinishing'), 'prepared': prepared})],
            'sourceFacts': facts}


def derived_problem(plan: dict) -> str | None:
    """A Short record's derived sections must equal ``short_sections(homes)`` byte for byte (freeze-time check)."""
    if plan['format'] != 'short':
        return None
    derived = short_sections(plan['homes'])
    differs = [section for section in SHORT_DERIVATION if plan[section] != derived[section]]
    return f'{PREFIX}: derived: derived section {differs[0]} differs from its executable home' if differs else None
