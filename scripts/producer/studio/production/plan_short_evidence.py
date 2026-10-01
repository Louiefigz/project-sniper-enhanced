"""The sealed shared-evidence record's part of a Short's plan record (P3a S2 ``sourceFacts``; X53, X211(3); M-081).

The record pinned at ``homes.sharedEvidence`` is read through L-Q's reader (``role_packet_evidence_record.located``,
then ``role_packet_evidence_speakers.mapped_intervals``, U-T4). ``sourceFacts``: each interval on this Short's source
mapped through its cuts onto output frames (P2-08's frame rule inverted), one entry per segment it reaches, in P2-07's
vocabulary. ``speaker-evidence`` (a whole-output framing entry): what P2-08's picture rules read beyond one fact, i.e.
every person with a face region on this source (named or not), the bound speaker observations, and every interval on
this source. P2 fields fail closed (W3-D8): the plan binds ``sharedEvidence`` exactly when homes pins a record, and a
phrase the record protects on retained words needs ``canvas.captionProtectedPhrases``.
"""
from __future__ import annotations

from fractions import Fraction
from math import ceil, floor

from cut_preview_io import digest
from studio.production.coordination_catalog import SPEAKER_EVIDENCE
from studio.production.plan_fields import check, derived_entry, read_pinned_json, refuse


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


def _record(evidence: dict) -> tuple[dict, list[dict]]:
    """The located sealed record and its intervals (version 1 read through the read-only mapping)."""
    from role_packet_evidence_record import located
    from role_packet_evidence_speakers import mapped_intervals
    record = read_pinned_json(evidence, 'sourceFacts')
    try:
        located({'path': evidence['path']}, record)
        return record, mapped_intervals(record['schemaVersion'], record['speakers'])
    except (ValueError, KeyError, TypeError) as error:
        refuse('sourceFacts', f'{evidence["path"]} is not a sealed shared-evidence record: {error}')


def _phrases_problem(native_plan: dict, record: dict, ours: set[str]) -> None:
    """A phrase the record protects on words this Short retains needs the plan's protected-phrase field (P2-05)."""
    retained = {row[2] for row in native_plan['canvas']['occurrences']}
    held = [row for row in record.get('captionPhrases') or [] if row['source'] in ours
            and set(range(row['sourceWordIndexes'][0], row['sourceWordIndexes'][1] + 1)) <= retained]
    check(not held or 'captionProtectedPhrases' in native_plan['canvas'], 'derived',
          f'canvas.captionProtectedPhrases is missing although the sealed record protects {len(held)} phrase(s) on '
          'retained words (P2-05, P2-08; W3-D8)')


def _facts(native_plan: dict, intervals: list[dict], people: dict, ours: set[str]) -> list[dict]:
    """One fact per (interval on this source, output segment it reaches); the digest covers the people it names."""
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


def sealed_sections(native_plan: dict, evidence: dict | None) -> tuple[list[dict], list[dict]]:
    """``(sourceFacts, framing entries)`` from the pinned record; both empty when the plan binds none."""
    from role_packet_speech import planned_source
    binding = native_plan.get('sharedEvidence')
    check((binding is None) == (evidence is None), 'derived',
          'the native plan binds sharedEvidence (P2-08) exactly when homes pins a sealed record')
    if evidence is None:
        return [], []
    check(binding['path'] == evidence['path'] and binding['sha256'] == evidence['sha256'], 'derived',
          'homes.sharedEvidence is not the record the native plan binds')
    record, intervals = _record(evidence)
    ours = {row['id'] for row in record['sources'] if row['sourceSha256'] == planned_source(native_plan)}
    _phrases_problem(native_plan, record, ours)
    people = {row['id']: row for row in record['speakers']['people']}
    regions = [row for row in record['speakers']['people'] if (row.get('faceRegion') or {}).get('source') in ours]
    observed = (record.get('coverage') or {}).get('observations')
    summary = {'people': regions, 'observations': observed, 'intervals': [row for row in intervals if row['source'] in ours]}
    return _facts(native_plan, intervals, people, ours), [derived_entry(SPEAKER_EVIDENCE, None, summary)]
