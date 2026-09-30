"""A Short's content sections, derived by code from its executable homes (P3a S2 §4.0.2; MASTER-PLAN M-081).

The record stores the derivation; the freeze recomputes it and requires byte equality (``derived_problem``), so the
integration owner never hand-writes a Short content section. The table is ``coordination_catalog.SHORT_DERIVATION``
as X201 corrects it: a region entry digests its unit row and its composition file's bytes (declared reveals live in
those files, F-1); compositions outside every region form one global entry; with no ``REVIEW-REGIONS.json`` the
compositions form one global ``project`` unit; ``audio`` is only ``audio-finishing`` (F-2); ``plan_projection`` is
called with the region rows' files as ``local`` (F-3); every plan path the table does not derive is a global
``key-<path>`` graphics entry (F-4, F-5). An absent optional structure derives a fixed shape (no beats: one beat over
the clock; no scenes: no holds or transitions; no caption groups: only ``caption-style``), never a guess.

``sourceFacts`` reads the sealed shared-evidence record pinned in ``homes.sharedEvidence`` through L-Q's reader
(``role_packet_evidence_record.located``, then ``role_packet_evidence_speakers.mapped_intervals``, U-T4) and maps
each interval on the plan's own source through the plan's cuts onto output frames, one entry per segment it reaches
(P2-08's frame rule inverted). Its digest also covers the people the interval names.
"""
from __future__ import annotations

from fractions import Fraction
from math import ceil, floor
from pathlib import Path

from cut_preview_io import bound_json, digest
from studio.native_runtime import digest as file_digest
from studio.native_short_regions import EXECUTABLE_PLAN, REGIONS, plan_projection, region_map
from studio.production.coordination_catalog import (
    PLAN_DERIVED, PROJECT_UNIT, PROJECTION_DERIVED, SHORT_DERIVATION, UNMAPPED_COMPOSITIONS,
)
from studio.production.plan_fields import PREFIX, check, pin, refuse
from studio.production.section_results import rehash

PROJECTED_KEYS = (*EXECUTABLE_PLAN, 'assets', 'catalogFiles')   # read whole by plan_projection
CAPTION_STYLE = ('captionCorrections', 'captionMode', 'captionViews', 'captionProtectedPhrases', 'captionSuppressions')
SPEECH = (('occurrencesSha256', 'occurrences'), ('cutsSha256', 'cuts'), ('segmentsSha256', 'segments'))


def read_pinned_json(value: object, rule: str) -> dict:
    """Rehash a pin (canonical path, no link, exact bytes and size) and parse its JSON object."""
    found = pin(value, rule)
    try:
        rehash(found)
        return bound_json(Path(found['path']), found['sha256'], maximum=found['bytes'])
    except (ValueError, RuntimeError, OSError) as error:
        refuse(rule, f'{found["path"]}: {error}')


def _entry(entry_id: str, span: list | None, source: object) -> dict:
    """A derived entry: code-assigned id, frames and the digest of what it was derived from."""
    return {'id': entry_id, 'range': span, 'digest': digest(source)}


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


def _captions(native_plan: dict) -> list[dict]:
    """One entry per caption group (frames of its first and last word) and one whole-output ``caption-style``."""
    canvas = native_plan['canvas']
    rows = {row[0]: row for row in canvas['occurrences']}
    groups = [_entry(f'group-{index}', occurrence_frames(native_plan, group),
                     {'group': group, 'words': [rows[item] for item in group]})
              for index, group in enumerate(canvas['captionGroups'])]
    return [*groups, _entry('caption-style', None, {key: canvas.get(key) for key in CAPTION_STYLE})]


def _compositions(project: Path) -> dict[str, str]:
    """Every ``compositions/*.html`` file of the project with its content digest."""
    folder = project / 'compositions'
    files = sorted(folder.glob('*.html')) if folder.is_dir() else []
    return {file.relative_to(project).as_posix(): file_digest(file) for file in files}


def _regions(project: Path, rows: list[dict]) -> list[dict]:
    """Region units (their unit row and composition bytes, F-1), then compositions no region covers (global)."""
    files = _compositions(project)
    if not rows:
        return [{'id': PROJECT_UNIT, 'range': None, 'isolation': 'global', 'digest': digest(files)}]
    units = [{'id': f'region-{index}', 'range': [row['startFrame'], row['endFrame']],
              'isolation': 'scoped' if row['isolation']['status'] == 'scoped' else 'global',
              'digest': digest({'unit': row, 'bytes': file_digest(project / row['file'])})}
             for index, row in enumerate(rows)]
    unmapped = {name: sha for name, sha in files.items() if name not in {row['file'] for row in rows}}
    extra = [{'id': UNMAPPED_COMPOSITIONS, 'range': None, 'isolation': 'global', 'digest': digest(unmapped)}]
    return units + (extra if unmapped else [])


def _remainder(source: dict, derived: dict) -> dict[str, object]:
    """Paths of ``source`` the derivation does not cover: a whole key, or the uncovered sub-keys of a mapped one."""
    found: dict[str, object] = {}
    for key, value in source.items():
        covered = derived.get(key)
        if covered == ():
            continue
        if covered is None or not isinstance(value, dict):
            found[key] = value
            continue
        found.update({f'{key}.{sub}': item for sub, item in value.items() if sub not in covered})
    return found


def unlisted(native_plan: dict, local: set[str]) -> dict[str, object]:
    """Every plan path the table does not derive, with its value: the projection's (F-3) and the rest's (F-5)."""
    from role_packet_native import GENERATED_BINDINGS
    found = _remainder(plan_projection(native_plan, local), PROJECTION_DERIVED)
    rest = {key: value for key, value in native_plan.items()
            if key not in PROJECTED_KEYS and key not in GENERATED_BINDINGS}
    found.update({f'plan.{path}': value for path, value in _remainder(rest, PLAN_DERIVED).items()})
    return found


def unlisted_keys(native_plan: dict) -> list[str]:
    """Paths of the native plan that SHORT_DERIVATION does not name; each is a global ``key-<path>`` entry."""
    return sorted(unlisted(native_plan, set()))


def _graphics(native_plan: dict, project: Path, rows: list[dict]) -> list[dict]:
    """Regions, then the canvas title card, text, shapes and motion (scoped), visual sources, and unlisted keys."""
    canvas, cues = native_plan['canvas'], []
    if canvas.get('titleCard') is not None:
        cues.append(_entry('title-card', [0, canvas['titleCard']['endFrame']], canvas['titleCard']))
    for name, key in (('text', 'text'), ('shape', 'shapes')):
        cues += [_entry(f'{name}-{index}', [row['startFrame'], row['endFrame']], row) for index, row in enumerate(canvas[key])]
    cues += [_entry(f'motion-{index}', [row['startFrame'], row['startFrame'] + row['durationFrames']], row)
             for index, row in enumerate(canvas['motion'])]
    cues.append(_entry('visual-sources', None, (native_plan.get('visualSources') or {}).get('decisions')))
    keys = [{'id': f'key-{path}', 'range': None, 'isolation': 'global', 'digest': digest(value)}
            for path, value in sorted(unlisted(native_plan, {row['file'] for row in rows}).items())]
    return _regions(project, rows) + [{**cue, 'isolation': 'scoped'} for cue in cues] + keys


def _output_spans(interval: dict, canvas: dict) -> list[tuple[int, int, int]]:
    """``(segment, a, b)`` for each cut the interval's source seconds reach (P2-08: f = start + (t - cut) * rate / speed)."""
    rate, spans = Fraction(canvas['frameRate']), []
    for index, (cut, segment) in enumerate(zip(canvas['cuts'], canvas['segments'])):
        low = max(Fraction(interval['startSeconds']), Fraction(cut['start']))
        high = min(Fraction(interval['endSeconds']), Fraction(cut['end']))
        scale = rate / Fraction(cut['speed'])
        first = segment['startFrame'] + floor((low - Fraction(cut['start'])) * scale)
        last = min(segment['endFrameExclusive'], segment['startFrame'] + ceil((high - Fraction(cut['start'])) * scale))
        spans += [(index, first, last)] if low < high and first < last else []
    return spans


def source_facts(native_plan: dict, evidence: dict | None) -> list[dict]:
    """The sealed record's intervals on this Short's source, one entry per output segment each reaches (X53 names)."""
    if evidence is None:
        return []
    from role_packet_evidence_record import located
    from role_packet_evidence_speakers import mapped_intervals
    from role_packet_speech import planned_source
    record = read_pinned_json(evidence, 'sourceFacts')
    try:
        located({'path': evidence['path']}, record)
        intervals = mapped_intervals(record['schemaVersion'], record['speakers'])
    except (ValueError, KeyError, TypeError) as error:
        refuse('sourceFacts', f'{evidence["path"]} is not a sealed shared-evidence record: {error}')
    ours = {row['id'] for row in record['sources'] if row['sourceSha256'] == planned_source(native_plan)}
    people = {row['id']: row for row in record['speakers']['people']}
    facts = []
    for number, interval in enumerate(intervals):
        check(interval['basis'] is not None, 'sourceFacts', f'interval {number} of a version 1 record has no basis; '
              'seal a version 2 record (P2-07)')
        named = [people[item] for item in sorted({interval['speaker'], *interval['visible']} - {None})]
        facts += [{'id': f'interval-{number}-{segment}', 'range': [start, end], 'speaker': interval['speaker'],
                   'certainty': interval['certainty'], 'basis': interval['basis'],
                   'digest': digest({'interval': interval, 'segment': segment, 'people': named})}
                  for segment, start, end in _output_spans(interval, native_plan['canvas'])
                  if interval['source'] in ours]
    return facts


def short_sections(homes: dict) -> dict:
    """``{clock, speech, story, holds, framing, captions, graphics, transitions, audio, sourceFacts}`` of a Short.

    ``homes`` is a shape-valid Short record's ``homes``. Each pin is rehashed; ``REVIEW-REGIONS.json`` is read through
    ``native_short_regions.region_map`` (absent: the whole project is one global unit).
    """
    plan, project = read_pinned_json(homes['nativePlan'], 'derived'), Path(homes['project'])
    if homes['regions'] is not None:
        read_pinned_json(homes['regions'], 'derived')
    check((homes['regions'] is not None) == (project / REGIONS).is_file(), 'derived',
          'regions must be pinned exactly when the project has REVIEW-REGIONS.json')
    try:
        return _sections(plan, project, homes['sharedEvidence'])
    except ValueError as error:
        if str(error).startswith(PREFIX):
            raise
        refuse('derived', f'the native plan or project cannot be derived: {error}')
    except (KeyError, TypeError, IndexError, AttributeError, ZeroDivisionError, RuntimeError, OSError) as error:
        refuse('derived', f'the native plan is not a well-formed native Short plan ({type(error).__name__}: {error})')


def _sections(plan: dict, project: Path, evidence: dict | None) -> dict:
    """The derivation proper, over a read native plan."""
    canvas = plan['canvas']
    rows = region_map(project, canvas)
    holds, transitions = _scenes(plan)
    return {'clock': {'frameRate': canvas['frameRate'], 'totalFrames': canvas['totalFrames']},
            'speech': {name: digest(canvas[key]) for name, key in SPEECH},
            'story': _story(plan), 'holds': holds,
            'framing': [_entry(f'view-{index}', [row['startFrame'], row['endFrame']], row)
                        for index, row in enumerate(canvas['pictureViews'])],
            'captions': _captions(plan), 'graphics': _graphics(plan, project, rows), 'transitions': transitions,
            'audio': [_entry('audio-finishing', None, plan.get('audioFinishing'))],
            'sourceFacts': source_facts(plan, evidence)}


def derived_problem(plan: dict) -> str | None:
    """A Short record's derived sections must equal ``short_sections(homes)`` byte for byte (freeze-time check)."""
    if plan['format'] != 'short':
        return None
    derived = short_sections(plan['homes'])
    differs = [section for section in SHORT_DERIVATION if plan[section] != derived[section]]
    return f'{PREFIX}: derived: derived section {differs[0]} differs from its executable home' if differs else None
