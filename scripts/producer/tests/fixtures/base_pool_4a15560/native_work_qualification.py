"""Host pool-qualification records and live qualification sessions.

Pool size comes only from a record the qualification harness writes after every
concurrent real export passed. The record is bound to exact host identity (CPU model,
core counts, physical RAM, OS version and build) and to the pool policy constants; an
absent, unreadable, mismatched or inconsistent record means exclusive mode (one native
member at a time). Only the canonical host namespace reads the record, so isolated or
test namespaces never inherit this host's qualification. Sessions let the harness run
its declared jobs under a candidate size while it holds the session lock.
"""
from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
from pathlib import Path

import native_work_lease as lease_module
from headless.durable_files import (
    DurableFileError, open_private_dir, private_child_dir, read_private_file, write_pending_replace,
)
from native_work_pool_policy import POOL_CLASSES, PoolMode, feasible_slots, policy_identity

RECORD_NAME = 'host-qualification-v1.json'
RECORD_KIND = 'sniper-native-pool-host-qualification'
SESSION_KIND = 'sniper-native-pool-qualification-session'
RECORD_LIMIT = 4 * 1024 * 1024
MAXIMUM_SESSION_JOBS = 16


class PoolRecordError(ValueError):
    """A qualification record or session is not exact, complete evidence."""


def record_directory() -> Path | None:
    """Return the persistent per-user record folder for the canonical namespace only."""
    if lease_module.state_root() != lease_module.default_state_root():
        return None
    return Path(pwd.getpwuid(os.geteuid()).pw_dir) / '.project-sniper' / 'native-pool'


def _require(condition: bool, message: str) -> None:
    """Raise the record-specific error for every rejected field."""
    if not condition:
        raise PoolRecordError(message)


def configuration_slots(value: object) -> dict:
    """Translate the stored configuration into bounded, memory-feasible slot counts."""
    _require(isinstance(value, dict) and set(value) == {'heavySlots', 'audioSlots'},
             'configuration must name heavySlots and audioSlots only')
    return {'heavy': value['heavySlots'], 'audio': value['audioSlots']}


def _canonical(value: object) -> bool:
    """Accept only absolute canonical path strings, never relative or linked spellings."""
    return isinstance(value, str) and os.path.isabs(value) and os.path.realpath(value) == value


def _validate_evidence(evidence: object, slots: dict) -> None:
    """Require complete, passing, full-export evidence that exercised the size."""
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
    _require(isinstance(evidence.get('summarySha256'), str)
             and re.fullmatch(r'[0-9a-f]{64}', evidence['summarySha256']) is not None,
             'evidence summary digest is missing')


def validate_record(value: object, host: dict) -> dict:
    """Return slots for an exact record of this host and policy; raise otherwise."""
    _require(isinstance(value, dict) and value.get('schemaVersion') == 1
             and value.get('kind') == RECORD_KIND, 'unsupported record schema')
    _require(value.get('host') == host, 'record host identity does not match this host')
    _require(value.get('policy') == policy_identity(), 'record policy differs from current pool policy')
    slots = configuration_slots(value.get('configuration'))
    _require(feasible_slots(slots, host['memsizeBytes']), 'record slots exceed bounds or the memory budget')
    _validate_evidence(value.get('evidence'), slots)
    return slots


def committed_mode(host: dict) -> PoolMode:
    """Read the persistent record; any defect is recorded and means exclusive mode."""
    directory = record_directory()
    if directory is None:
        return PoolMode('exclusive', rejected='non-canonical pool namespace never reads the host record')
    if not os.path.lexists(directory / RECORD_NAME):
        return PoolMode('exclusive')
    try:
        descriptor = open_private_dir(str(directory))
        try:
            data = read_private_file(descriptor, RECORD_NAME, RECORD_LIMIT)
        finally:
            os.close(descriptor)
        slots = validate_record(json.loads(data), host)
    except (DurableFileError, OSError, ValueError, KeyError, TypeError) as error:
        return PoolMode('exclusive', rejected=f'{type(error).__name__}: {error}')
    return PoolMode('qualified', slots, {'path': str(directory / RECORD_NAME),
                                         'sha256': hashlib.sha256(data).hexdigest()})


def write_record(value: dict, host: dict) -> dict:
    """Durably publish one validated record in the private per-user folder."""
    validate_record(value, host)
    directory = record_directory()
    _require(directory is not None, 'records are written only for the canonical host namespace')
    directory.parent.mkdir(mode=0o700, exist_ok=True)
    parent = os.open(directory.parent, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        child = private_child_dir(parent, directory.name)
    finally:
        os.close(parent)
    data = (json.dumps(value, indent=2, sort_keys=True) + '\n').encode()
    try:
        write_pending_replace(child, (RECORD_NAME + '.pending', RECORD_NAME), data)
    finally:
        os.close(child)
    return {'path': str(directory / RECORD_NAME), 'sha256': hashlib.sha256(data).hexdigest()}


def validate_session(value: object, host: dict, now: float) -> dict:
    """Return candidate slots for a live, unexpired session of this host."""
    _require(isinstance(value, dict) and value.get('schemaVersion') == 1
             and value.get('kind') == SESSION_KIND, 'unsupported session schema')
    _require(re.fullmatch(r'[0-9a-f]{32}', str(value.get('nonce'))) is not None, 'session nonce is invalid')
    _require(value.get('host') == host, 'session host identity does not match this host')
    slots = configuration_slots(value.get('configuration'))
    _require(feasible_slots(slots, host['memsizeBytes']), 'session slots exceed bounds or the memory budget')
    jobs = value.get('jobs')
    _require(isinstance(jobs, list) and 1 <= len(jobs) <= MAXIMUM_SESSION_JOBS, 'session job list is invalid')
    _require(all(isinstance(job, dict) and set(job) == {'project', 'attempt'}
                 and _canonical(job['project']) and _canonical(job['attempt']) for job in jobs),
             'session jobs need canonical project and attempt paths')
    expires = value.get('expiresAtEpoch')
    _require(type(expires) in (int, float) and now < expires, 'session has expired')
    return slots


def session_member(session: dict, project: str, root: str | None) -> bool:
    """Match a declared job's owners: same project, root at or inside its attempt folder.

    Export owners write to the attempt itself or to a folder inside it (the audio stage
    uses <attempt>/audio-stage); both paths are canonical, so this is exact containment.
    """
    if root is None:
        return False
    return any(job['project'] == project and Path(root).is_relative_to(job['attempt'])
               for job in session['jobs'])


def session_mode(session: dict, slots: dict) -> PoolMode:
    """Describe the candidate capacity used only for declared session jobs."""
    return PoolMode('qualification-session', slots, {'session': session['nonce']})


def empty_slots() -> dict:
    """Slot counts for an idle view, used in receipts and harness summaries."""
    return {lane: 0 for lane in POOL_CLASSES}
