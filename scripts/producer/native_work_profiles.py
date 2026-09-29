"""Versioned host qualification profiles and their applicability at pool admission.

A profile states: on this host and pool policy, with this frozen engine, N heavy and M
audio members ran together for workloads inside these exercised bounds, and every job
passed, matched its serial reference and cleaned up. The bounds are re-derived from the
per-job evidence on every read, so a record cannot claim more than its jobs exercised:
the class mix and, per format, the owner stages, the longest output, the largest picture
and the source-cache states. Admission (native_work_pool.decide) uses a profile only for a
request inside every bound (native_work_workload.describe) and only beside live members
the same profile covers; any other request gets the conservative exclusive mode (one
member at a time, the pre-pool rule) with the unmatched reasons in its receipt. Nothing
widens to a nearby profile.

Class mix: 'heavy-only' covers heavy owners only. 'mixed' also covers audio owners and
requires evidence of the jobs' own 'audio-stage' owners overlapping heavy owners; a batch
that imported prepared audio, or had only heavy owners (or only audio packaging beside
them), cannot claim it.

The legacy schema-1 record predates engine binding and bounds. It is read as one profile
covering the formats its jobs delivered plus unbound supporting owners and owners whose
older client recorded no workload (the pool's behaviour before profiles, minus Longs).
It keeps serving every format no schema-2 profile covers (native_work_qualification).
"""
from __future__ import annotations

import math
import re

from native_work_pool_policy import POOL_CLASSES, feasible_slots

FORMATS = ('short', 'long')
STATUS_FORMATS = {'native-short-checked-for-review': 'short', 'native-long-checked-for-review': 'long'}
CLASS_MIXES = {'heavy-only': ('heavy',), 'mixed': ('heavy', 'audio'), 'legacy': POOL_CLASSES}
CACHE_STATES = ('cold', 'partial', 'warm')
METRICS = {'cpu': ('logicalCpus', 'maximumAdmissionLoad1m'),
           'memory': ('aggregatePeakOwnedBytes', 'minimumFreePercent', 'maximumKernelPressureLevel'),
           'disk': ('minimumDiskFreeBytes', 'maximumAttemptBytes'),
           'throughput': ('outputSeconds', 'batchWallSeconds', 'outputSecondsPerWallSecond'),
           'failures': ('failedJobs', 'failedOwners'), 'cleanup': ('owners', 'unverifiedOwners')}
PROFILE_KEYS = frozenset({'id', 'engine', 'configuration', 'workload', 'evidence', 'harness', 'writtenAt'})
PROFILE_ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9._-]{0,95}')
HEX64 = re.compile(r'[0-9a-f]{64}')
MAXIMUM_PROFILES = 16


class PoolRecordError(ValueError):
    """A qualification record, profile or session is not exact, complete evidence."""


def _require(condition: bool, message: str) -> None:
    """Raise the record-specific error for every rejected field."""
    if not condition:
        raise PoolRecordError(message)


def nonnegative_number(value: object) -> bool:
    """A finite, nonnegative int or float (never a bool)."""
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def configuration_slots(value: object) -> dict:
    """Translate the stored configuration into slot counts (bounds are checked separately)."""
    _require(isinstance(value, dict) and set(value) == {'heavySlots', 'audioSlots'},
             'configuration must name heavySlots and audioSlots only')
    return {'heavy': value['heavySlots'], 'audio': value['audioSlots']}


def validate_evidence(evidence: object, slots: dict) -> None:
    """Require complete, passing, full-export evidence that exercised the heavy size."""
    _require(isinstance(evidence, dict), 'evidence must be an object')
    _require(evidence.get('allJobsPassed') is True and evidence.get('fullExports') is True,
             'evidence must come from passing full exports')
    jobs = evidence.get('jobs')
    _require(isinstance(jobs, list) and len(jobs) >= slots['heavy'], 'evidence has too few jobs')
    _require(all(isinstance(job, dict) and job.get('passed') is True
                 and job.get('referenceMatched') is True for job in jobs),
             'every qualification job must pass and match its serial reference')
    peak = evidence.get('peakConcurrentJobs')
    _require(type(peak) is int and peak >= slots['heavy'], 'evidence did not exercise the slot count')
    _require(HEX64.fullmatch(str(evidence.get('summarySha256'))) is not None, 'evidence summary digest is missing')


def _job_facts(job: dict) -> None:
    """Each job states what it exercised: format, stages, duration, picture, cache, audio."""
    _require(job.get('format') in FORMATS, 'job format must be short or long')
    stages = job.get('stages')
    _require(isinstance(stages, list) and stages and all(isinstance(item, str) and item for item in stages),
             'job owner stages were not recorded')
    _require(nonnegative_number(job.get('durationSeconds')) and job['durationSeconds'] > 0
             and type(job.get('pixels')) is int and job['pixels'] > 0,
             'job output duration and picture size are required')
    _require(job.get('cacheState') in CACHE_STATES, 'job source-cache state (cold, partial or warm) was not recorded')
    _require(type(job.get('ownAudioStage')) is bool, 'job audio-stage provenance was not recorded')


def _format_bounds(jobs: list[dict]) -> dict:
    """Stages, longest output, largest picture and cache states of one format's jobs."""
    return {'stages': sorted({stage for job in jobs for stage in job['stages']}),
            'maxDurationSeconds': max(job['durationSeconds'] for job in jobs),
            'maxPixels': max(job['pixels'] for job in jobs),
            'cacheStates': sorted({job['cacheState'] for job in jobs})}


def derived_bounds(jobs: list[dict], class_mix: str) -> dict:
    """The workload bounds a set of passing jobs exercised, exactly, per format."""
    kinds = sorted({job['format'] for job in jobs})
    return {'classMix': class_mix,
            'formats': {kind: _format_bounds([job for job in jobs if job['format'] == kind]) for kind in kinds}}


def mixed_reasons(evidence: dict, slots: dict) -> list[str]:
    """Why evidence cannot support a mixed (heavy plus audio) claim; empty when it can."""
    overlap = evidence.get('overlap') if isinstance(evidence.get('overlap'), dict) else {}
    reasons = [] if any(job.get('ownAudioStage') is True for job in evidence.get('jobs', [])) else \
        ['no job ran its own audio stage (only heavy owners or prepared audio)']
    peak = overlap.get('audioStageWithHeavyPeak')
    if not (type(peak) is int and peak >= slots['audio']):
        reasons.append(f"audio-stage owners never overlapped heavy owners {slots['audio']} at a time")
    return reasons


def _metrics(evidence: dict) -> None:
    """CPU, memory, disk, throughput, failures and cleanup are all recorded and clean."""
    for name, keys in METRICS.items():
        value = evidence.get(name)
        _require(isinstance(value, dict) and all(nonnegative_number(value.get(key)) for key in keys),
                 f'evidence {name} metrics are incomplete')
    _require(evidence['failures']['failedJobs'] == 0 and evidence['failures']['failedOwners'] == 0,
             'qualification evidence recorded failures')
    _require(evidence['cleanup']['owners'] > 0 and evidence['cleanup']['unverifiedOwners'] == 0,
             'every qualification owner must have verified cleanup')


def validate_profile(profile: object, physical: int) -> dict:
    """Return the usable profile (with slots) or raise; bounds must equal the evidence."""
    _require(isinstance(profile, dict) and set(profile) == PROFILE_KEYS, 'profile fields are not exact')
    _require(isinstance(profile['id'], str) and PROFILE_ID.fullmatch(profile['id']) is not None,
             'profile id is invalid')
    engine = profile['engine']
    _require(isinstance(engine, dict) and set(engine) == {'identity', 'files'}
             and HEX64.fullmatch(str(engine['identity'])) is not None and type(engine['files']) is int
             and engine['files'] > 0, 'profile engine identity is invalid')
    slots = configuration_slots(profile['configuration'])
    _require(feasible_slots(slots, physical), 'profile slots exceed bounds or the memory budget')
    evidence = profile['evidence']
    validate_evidence(evidence, slots)
    for job in evidence['jobs']:
        _job_facts(job)
    _metrics(evidence)
    mix = profile['workload'].get('classMix') if isinstance(profile['workload'], dict) else None
    _require(mix in ('heavy-only', 'mixed'), 'profile class mix must be heavy-only or mixed')
    _require(profile['workload'] == derived_bounds(evidence['jobs'], mix),
             'profile bounds differ from what its jobs exercised')
    reasons = mixed_reasons(evidence, slots) if mix == 'mixed' else []
    _require(not reasons, 'a mixed qualification needs its own audio-stage owners overlapping heavy owners: '
             + '; '.join(reasons))
    return {**profile, 'slots': slots, 'legacy': False}


def legacy_profile(record: dict, slots: dict, bounded: set[str]) -> dict | None:
    """The schema-1 record as one engine-unbound profile for what schema 2 does not bound.

    Args:
        record: The validated schema-1 record.
        slots: Its configured slot counts.
        bounded: Formats some schema-2 profile covers; those stay strictly schema 2.

    Returns:
        The profile over its delivered formats plus 'unbound' and 'unrecorded' owners, or
        None when schema 2 bounds all of them.
    """
    jobs = record['evidence']['jobs']
    formats = {STATUS_FORMATS[job['status']] for job in jobs if job.get('status') in STATUS_FORMATS}
    served = sorted((formats | {'unbound', 'unrecorded'}) - bounded)
    return {'id': 'legacy-v1', 'legacy': True, 'engine': None, 'slots': slots,
            'workload': {'classMix': 'legacy', 'formats': {kind: None for kind in served}}} if served else None


def _bound(value: object, maximum: object, name: str) -> list[str]:
    """An exercised maximum applies only to a known value at or below it."""
    if value is None:
        return [f'{name} are unknown; the profile is bounded at {maximum}']
    return [f'{name} {value} exceed the exercised {maximum}'] if value > maximum else []


def _format_mismatches(limits: dict | None, workload: dict) -> list[str]:
    """Stage, duration, picture and cache bounds of the workload's format (None: unbounded legacy)."""
    if limits is None:
        return []
    reasons = [] if workload.get('stage') in limits['stages'] else [f"stage {workload.get('stage')} was not exercised"]
    reasons += _bound(workload.get('durationSeconds'), limits['maxDurationSeconds'], 'output seconds')
    reasons += _bound(workload.get('pixels'), limits['maxPixels'], 'picture pixels')
    if 'cold' not in limits['cacheStates']:
        reasons.append('only warm or partial source caches were exercised; admission cannot establish a warm cache')
    return reasons


def mismatches(profile: dict, workload: dict) -> list[str]:
    """Every reason a profile does not cover a workload; empty means it applies."""
    bounds, engine, reasons = profile['workload'], profile['engine'], []
    if engine is not None and workload.get('engine') != engine['identity']:
        reasons.append(f"engine {str(workload.get('engine'))[:12]} is not the qualified engine "
                       f"{engine['identity'][:12]}")
    if workload.get('class') not in CLASS_MIXES[bounds['classMix']]:
        reasons.append(f"{workload.get('class')} owners are outside the {bounds['classMix']} class mix")
    if workload.get('format') not in bounds['formats']:
        return reasons + [f"format {workload.get('format')} was not exercised ({', '.join(bounds['formats'])})"]
    return reasons + _format_mismatches(bounds['formats'][workload['format']], workload)


def select(profiles: tuple, workload: dict, present: list[tuple]) -> tuple[dict | None, list[str], list[tuple]]:
    """Choose (profile, unmatched reasons, (nonce, state) of members outside it) for one request.

    Args:
        profiles: The committed usable profiles.
        workload: The request's workload.
        present: (nonce, recorded workload or None, 'live'/'quarantined') of every member.

    Among applicable profiles prefer one that also covers every member, then the most
    slots for the request's class, then the id, so the choice is deterministic.
    """
    unmatched, candidates = [], []
    for profile in profiles:
        reasons = mismatches(profile, workload)
        if reasons:
            unmatched.append(f"{profile['id']}: {'; '.join(reasons)}")
            continue
        outside = [(nonce, status) for nonce, other, status in present
                   if other is None or mismatches(profile, other)]
        candidates.append(((bool(outside), -profile['slots'][workload['class']], profile['id']), profile, outside))
    if not candidates:
        return None, unmatched[:MAXIMUM_PROFILES], []
    _key, profile, outside = min(candidates, key=lambda row: row[0])
    return profile, [], outside
