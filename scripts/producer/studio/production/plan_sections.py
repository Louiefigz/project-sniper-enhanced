"""Closed validators for the shared plan record's sections (P3a S2, §4.0.2; MASTER-PLAN M-081).

Short content sections are derived by code (``plan_short_projection``); a Long's are authored. Where the two shapes
differ, a validator takes ``authored`` (True for a Long). Coordination-only sections (``unresolved``, ``ownership``,
``contributions``, ``conflicts``, ``workPlan``, ``decisions``) are checked here for shape and bounds; the ledger and
trail cross-checks named in §4.0.2 belong to the steps that own those readers (S6 decisions, S7 conflicts, S8 caps
and contributions). ``sourceFacts`` uses P2-07's vocabulary verbatim (X53): ``established`` needs basis
``listening`` or ``operator-statement``, so ``transcript-only`` is never established, and a null speaker is exactly
an unresolved one.
"""
from __future__ import annotations

from role_packet_evidence_speakers import BASES, CERTAINTIES
from studio.native_budget_schema import BOUNDS as BUDGET_BOUNDS
from studio.production.coordination_catalog import (
    ENTRY_SECTIONS, PLAN_BOUNDS, RESPONSIBILITIES, TEXT_BYTES, WORK_COUNTERS,
)
from studio.production.plan_fields import (
    PREFIX, authored_digest, check, closed, contiguous, count, frame_range, hex64, identifier, identifiers,
    maybe_range, maybe_text, pin, rows, text,
)

ESTABLISHED_BASES = ('listening', 'operator-statement')
MAX_OCCURRENCES = 8_192          # beat word lists: no stated bound; the lane chose one above 30 min of speech (U-T7)
GRAPHIC_SOURCES = ('catalog', 'reference', 'custom')
FEASIBILITY = ('feasible', 'infeasible', 'unverified')
AUDIO_KINDS = ('dialogue', 'music', 'sfx', 'gain', 'duck', 'cleanup')
BLOCKS = ('final', 'execution', 'none')
DISPOSITIONS = ('accepted', 'accepted-with-changes', 'rejected', 'deferred')
CONFLICT_KINDS = ('same-entry', 'lane-overlap', 'hold-crosses-boundary', 'declared')


def _entries(value: object, section: str, keys: tuple[str, ...]) -> list[dict]:
    """A bounded list of closed entries with an id and a digest each."""
    found = rows(value, section, (0, PLAN_BOUNDS[section]))
    for row in found:
        closed(row, keys, section)
        identifier(row['id'], section)
        hex64(row['digest'], section)
    return found


def _isolation(entry: dict, section: str) -> None:
    """``scoped`` or ``global``; a global entry joins the global digest."""
    check(entry['isolation'] in ('scoped', 'global'), section, f'{entry["id"]} isolation must be scoped or global')


def validate_story(value: object, clock: dict) -> list[dict]:
    """1..64 beats tiling the clock; ``occurrenceIds`` a word-id list or null, ``purpose`` text(500) or null."""
    beats = _entries(value, 'story', ('id', 'range', 'occurrenceIds', 'purpose', 'digest'))
    check(len(beats) >= 1, 'story', 'needs at least one beat')
    for beat in beats:
        frame_range(beat['range'], clock, 'story')
        ids = beat['occurrenceIds']
        check(ids is None or type(ids) is list and len(ids) <= MAX_OCCURRENCES
              and all(type(item) is int and item >= 0 for item in ids), 'story', 'occurrenceIds must list word ids')
        maybe_text(beat['purpose'], TEXT_BYTES['purpose'], 'story')
    contiguous([beat['range'] for beat in beats], clock, 'story')
    return beats


def validate_framing(value: object, clock: dict) -> list[dict]:
    """At most 128 entries ``{id, range, digest}``: picture views; whole-output (null range) speaker evidence and decisions."""
    views = _entries(value, 'framing', ('id', 'range', 'digest'))
    for view in views:
        maybe_range(view['range'], clock, 'framing')
    return views


def _graphic_rule(rule: dict, clock: dict) -> None:
    """A Long graphics rule: reveal inside its range, source, feasibility and evidence (§4.0.2)."""
    start, end = frame_range(rule['range'], clock, 'graphics')
    reveal = rule['revealFrame']
    check(type(reveal) is int and start <= reveal < end, 'graphics', f'{rule["id"]} reveal must lie in [{start}, {end})')
    check(type(rule['hiddenUntilReveal']) is bool, 'graphics', f'{rule["id"]} hiddenUntilReveal must be a boolean')
    identifier(rule['lane'], 'graphics')
    source = closed(rule['source'], ('kind', 'ref'), 'graphics')
    check(source['kind'] in GRAPHIC_SOURCES, 'graphics', f'source kind must be one of {list(GRAPHIC_SOURCES)}')
    text(source['ref'], TEXT_BYTES['rule'], 'graphics')
    check(rule['feasibility'] in FEASIBILITY, 'graphics', f'feasibility must be one of {list(FEASIBILITY)}')
    for item in rows(rule['evidence'], 'graphics', (0, 16)):
        text(item, TEXT_BYTES['evidence'], 'graphics')


def validate_graphics(value: object, clock: dict, authored: bool = False) -> list[dict]:
    """At most 128 entries: Short derived ``{id, range, isolation, digest}``; Long authored rules."""
    keys = ('id', 'lane', 'range', 'revealFrame', 'hiddenUntilReveal', 'source', 'feasibility', 'evidence',
            'isolation', 'digest') if authored else ('id', 'range', 'isolation', 'digest')
    entries = _entries(value, 'graphics', keys)
    for entry in entries:
        _isolation(entry, 'graphics')
        if authored:
            _graphic_rule(entry, clock)
        else:
            maybe_range(entry['range'], clock, 'graphics')
    return entries


def _audio_event(event: dict, clock: dict, inputs: list[dict]) -> None:
    """A Long audio event: kind, range, an input asset pin or null, a level in -60..+12 dB or null."""
    check(event['kind'] in AUDIO_KINDS, 'audio', f'kind must be one of {list(AUDIO_KINDS)}')
    frame_range(event['range'], clock, 'audio')
    check(event['asset'] is None or event['asset'] in inputs, 'audio', f'{event["id"]} asset must be a plan input')
    level = event['levelDb']
    check(level is None or type(level) in (int, float) and -60 <= level <= 12, 'audio', 'levelDb must be -60..+12')
    _isolation(event, 'audio')


def validate_audio(value: object, clock: dict, inputs: list[dict], authored: bool = False) -> list[dict]:
    """At most 64 entries: Short ``{id, range, digest}``; Long events (``kind``, ``asset``, ``levelDb``, ``isolation``)."""
    keys = ('id', 'kind', 'range', 'asset', 'levelDb', 'isolation', 'digest') if authored else ('id', 'range', 'digest')
    entries = _entries(value, 'audio', keys)
    for entry in entries:
        if authored:
            _audio_event(entry, clock, inputs)
        else:
            maybe_range(entry['range'], clock, 'audio')
    return entries


def validate_transitions(value: object, clock: dict, sections: list[dict], authored: bool = False) -> list[dict]:
    """At most 64 boundaries with ``a < boundaryFrame < b``; a Long's also carry sides, state and owner."""
    keys = ('id', 'boundaryFrame', 'range', 'outgoing', 'incoming', 'state', 'owner', 'digest') if authored \
        else ('id', 'boundaryFrame', 'range', 'digest')
    entries = _entries(value, 'transitions', keys)
    for entry in entries:
        start, end = frame_range(entry['range'], clock, 'transitions')
        frame = entry['boundaryFrame']
        check(type(frame) is int and start < frame < end, 'transitions', f'{entry["id"]} boundary is not inside its range')
        if authored:
            identifier(entry['outgoing'], 'transitions')
            identifier(entry['incoming'], 'transitions')
            check(entry['state'] in ('planned', 'frozen'), 'transitions', 'state must be planned or frozen')
            owner_of_row(entry['owner'], sections, 'transitions')
    return entries


def validate_holds(value: object, ids: set[str], clock: dict, authored: bool = False) -> list[dict]:
    """At most 128 holds: Short ``{id, range, holdFrames}``; Long ``{id, subject, range, minimumFrames}``."""
    keys = ('id', 'subject', 'range', 'minimumFrames', 'digest') if authored else ('id', 'range', 'holdFrames', 'digest')
    entries = _entries(value, 'holds', keys)
    for entry in entries:
        start, end = frame_range(entry['range'], clock, 'holds')
        if not authored:
            count(entry['holdFrames'], clock['totalFrames'], 'holds')
            continue
        check(entry['subject'] in ids, 'holds', f'{entry["id"]} subject {entry["subject"]!r} names no entry')
        minimum = entry['minimumFrames']
        check(type(minimum) is int and 1 <= minimum <= end - start, 'holds', f'{entry["id"]} is shorter than its minimum')
    return entries


def validate_captions(value: object, clock: dict, authored: bool = False) -> list[dict]:
    """At most 512 entries: Short ``{id, range, digest}``; Long rules add ``rule`` text(500)."""
    entries = _entries(value, 'captions', ('id', 'range', 'rule', 'digest') if authored else ('id', 'range', 'digest'))
    for entry in entries:
        maybe_range(entry['range'], clock, 'captions')
        if authored:
            text(entry['rule'], TEXT_BYTES['rule'], 'captions')
    return entries


def validate_source_facts(value: object, clock: dict) -> list[dict]:
    """At most 128 facts in P2-07's vocabulary (X53); a null speaker is exactly an unresolved one."""
    entries = _entries(value, 'sourceFacts', ('id', 'range', 'speaker', 'certainty', 'basis', 'digest'))
    for entry in entries:
        frame_range(entry['range'], clock, 'sourceFacts')
        check(entry['certainty'] in CERTAINTIES and entry['basis'] in BASES, 'sourceFacts',
              f'{entry["id"]} certainty and basis must be P2-07 values {list(CERTAINTIES)} / {list(BASES)}')
        check((entry['speaker'] is None) == (entry['certainty'] == 'unresolved'), 'sourceFacts',
              f'{entry["id"]}: speaker is null exactly when certainty is unresolved')
        maybe_text(entry['speaker'], TEXT_BYTES['speaker'], 'sourceFacts')
        check(entry['certainty'] != 'established' or entry['basis'] in ESTABLISHED_BASES, 'sourceFacts',
              f'{entry["id"]}: established needs basis listening or operator-statement (not {entry["basis"]})')
    return entries


def validate_unresolved(value: object, clock: dict) -> list[dict]:
    """At most 64 evidence gaps, each owned by a responsibility and tied to a logged decision."""
    found = rows(value, 'unresolved', (0, PLAN_BOUNDS['unresolved']))
    for row in found:
        closed(row, ('id', 'responsibility', 'range', 'statement', 'blocks', 'decisionId'), 'unresolved')
        identifier(row['id'], 'unresolved')
        check(row['responsibility'] in RESPONSIBILITIES, 'unresolved', f'{row["id"]} names no responsibility')
        maybe_range(row['range'], clock, 'unresolved')
        text(row['statement'], TEXT_BYTES['statement'], 'unresolved')
        check(row['blocks'] in BLOCKS, 'unresolved', f'blocks must be one of {list(BLOCKS)}')
        identifier(row['decisionId'], 'unresolved')
    return found


def owner_of_row(value: object, sections: list[dict], rule: str) -> dict:
    """``{"task": id}``, or ``{"section": id}`` naming one of a Long's sections."""
    check(type(value) is dict and len(value) == 1 and set(value) <= {'task', 'section'}, rule,
          'owner must be {"task": id} or {"section": id}')
    kind, name = next(iter(value.items()))
    identifier(name, rule)
    check(kind == 'task' or name in {row['id'] for row in sections}, rule, f'owner section {name!r} is not a section')
    return value


def validate_ownership(value: object, clock: dict, sections: list[dict]) -> list[dict]:
    """At most 64 rows; each responsibility's rows tile ``[0, totalFrames)`` exactly (one owner per frame, A8)."""
    found = rows(value, 'ownership', (0, PLAN_BOUNDS['ownership']))
    for row in found:
        closed(row, ('responsibility', 'range', 'owner'), 'ownership')
        check(row['responsibility'] in RESPONSIBILITIES, 'ownership', f'{row["responsibility"]!r} is not a responsibility')
        frame_range(row['range'], clock, 'ownership')
        owner_of_row(row['owner'], sections, 'ownership')
    for responsibility in RESPONSIBILITIES:
        edge = 0
        for start, end in sorted(row['range'] for row in found if row['responsibility'] == responsibility):
            check(start <= edge, 'ownership', f'responsibility {responsibility} has no owner for frames {edge}-{start}')
            check(start == edge, 'ownership', f'responsibility {responsibility} has two owners at frame {start}')
            edge = end
        check(edge == clock['totalFrames'], 'ownership',
              f'responsibility {responsibility} has no owner for frames {edge}-{clock["totalFrames"]}')
    return found


def validate_contributions(value: object) -> list[dict]:
    """At most 32 dispositions of assignment results; anything but ``accepted`` names its decision."""
    found = rows(value, 'contributions', (0, PLAN_BOUNDS['contributions']))
    for row in found:
        closed(row, ('taskId', 'responsibility', 'result', 'disposition', 'decisionId'), 'contributions')
        identifier(row['taskId'], 'contributions')
        check(row['responsibility'] in RESPONSIBILITIES, 'contributions', f'{row["responsibility"]!r} is not one')
        pin(row['result'], 'contributions')
        check(row['disposition'] in DISPOSITIONS, 'contributions', f'disposition must be one of {list(DISPOSITIONS)}')
        check(row['decisionId'] is not None or row['disposition'] == 'accepted', 'contributions',
              f'{row["taskId"]} {row["disposition"]} needs a plan-disposition decision')
        if row['decisionId'] is not None:
            identifier(row['decisionId'], 'contributions')
    return found


def validate_conflicts(value: object, clock: dict) -> list[dict]:
    """At most 32 recorded conflicts with sorted parties and entry ids, each resolved or blocking by decision."""
    found = rows(value, 'conflicts', (0, PLAN_BOUNDS['conflicts']))
    for row in found:
        closed(row, ('id', 'kind', 'parties', 'entryIds', 'range', 'status', 'decisionId'), 'conflicts')
        identifier(row['id'], 'conflicts')
        check(row['kind'] in CONFLICT_KINDS, 'conflicts', f'kind must be one of {list(CONFLICT_KINDS)}')
        for key in ('parties', 'entryIds'):
            ids = identifiers(row[key], 'conflicts', (0, 64))
            check(ids == sorted(ids), 'conflicts', f'{row["id"]} {key} must be sorted')
        maybe_range(row['range'], clock, 'conflicts')
        check(row['status'] in ('resolved', 'blocking'), 'conflicts', 'status must be resolved or blocking')
        identifier(row['decisionId'], 'conflicts')
    identifiers([row['id'] for row in found], 'conflicts', (0, PLAN_BOUNDS['conflicts']))
    return found


def validate_work_plan(value: object, version: int) -> dict:
    """Remaining charges per counter and the one-repair reserve, which applies to version 1 only (§4.0.8)."""
    plan = closed(value, ('remaining', 'reserve'), 'workPlan')
    for key in closed(plan['remaining'], WORK_COUNTERS, 'workPlan'):
        count(plan['remaining'][key], BUDGET_BOUNDS['tasks'], 'workPlan')
    check(plan['reserve'] == ('one-repair' if version == 1 else 'none'), 'workPlan',
          'reserve is one-repair at version 1 and none after it')
    return plan


def entry_rows(plan: dict) -> list[tuple[str, dict]]:
    """Every ``(section, entry)`` of the content sections and ``unresolved``, for slices and conflicts."""
    return [(section, entry) for section in ENTRY_SECTIONS for entry in plan[section]]


def entry_digest_problem(plan: dict) -> str | None:
    """A Long's authored entries each carry the digest of their other fields; a Short's are derived (checked at freeze
    by byte equality with ``plan_short_projection.short_sections``)."""
    if plan['format'] != 'long':
        return None
    stale = [f'{section}/{entry["id"]}' for section, entry in entry_rows(plan)
             if section != 'unresolved' and entry['digest'] != authored_digest(entry)]
    return f'{PREFIX}: digest: entries {stale[:8]} do not recompute' if stale else None
