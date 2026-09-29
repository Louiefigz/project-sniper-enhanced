"""Host pool-qualification records, profile-selected pool modes and live sessions.

Pool size comes only from a record the qualification harness writes after every
concurrent real export passed. Records are bound to exact host identity (CPU model,
core counts, physical RAM, OS version and build) and to the pool policy constants.
Schema 2 (host-qualification-v2.json) holds versioned profiles, each bound to the frozen
engine identity and the workload bounds its jobs exercised (native_work_profiles.py);
admission selects the profile that covers each request. The legacy schema-1 file
(host-qualification-v1.json) is read as one engine-unbound profile serving whatever no
schema-2 profile covers: the formats it delivered (Shorts on the current host), unbound
supporting owners and older clients' unrecorded owners. A format a schema-2 profile covers
is served by schema 2 only. An absent, unreadable, mismatched or inconsistent record
contributes no profile (recorded in 'rejected'); a request no profile covers gets exclusive
mode with the reasons in its receipt (native_work_pool_mix.py decides whether it may
start). A valid schema-1 record also means older pool clients run qualified, so members
they cannot understand take a compatibility fence (native_work_pool_fence.py). Only the
canonical host namespace reads the records, so isolated or test namespaces never inherit
this host's qualification. Sessions let the harness run its declared jobs under a
candidate size while it holds the session lock.
"""
from __future__ import annotations

import hashlib
import json
import os
import pwd
import re
from dataclasses import dataclass
from pathlib import Path

import native_work_lease as lease_module
import native_work_profiles as profiles
import native_work_workload as workloads
from headless.durable_files import (
    DurableFileError, open_private_dir, private_child_dir, read_private_file, write_pending_replace,
)
from native_work_pool_policy import POOL_CLASSES, PoolMode, feasible_slots, policy_identity
from native_work_profiles import PoolRecordError, configuration_slots  # noqa: F401  (public API)

RECORD_NAME = 'host-qualification-v1.json'
RECORD_V2_NAME = 'host-qualification-v2.json'
RECORD_KIND = 'sniper-native-pool-host-qualification'
SESSION_KIND = 'sniper-native-pool-qualification-session'
RECORD_LIMIT = 4 * 1024 * 1024
MAXIMUM_SESSION_JOBS = 16
RECORD_FILES = {1: RECORD_NAME, 2: RECORD_V2_NAME}


def record_directory() -> Path | None:
    """Return the persistent per-user record folder for the canonical namespace only."""
    if lease_module.state_root() != lease_module.default_state_root():
        return None
    return Path(pwd.getpwuid(os.geteuid()).pw_dir) / '.project-sniper' / 'native-pool'


def _require(condition: bool, message: str) -> None:
    """Raise the record-specific error for every rejected field."""
    if not condition:
        raise PoolRecordError(message)


def _canonical(value: object) -> bool:
    """Accept only absolute canonical path strings, never relative or linked spellings."""
    return isinstance(value, str) and os.path.isabs(value) and os.path.realpath(value) == value


def _header(value: object, host: dict, version: int) -> None:
    """Schema, kind, exact host and current pool policy."""
    _require(isinstance(value, dict) and value.get('schemaVersion') == version
             and value.get('kind') == RECORD_KIND, 'unsupported record schema')
    _require(value.get('host') == host, 'record host identity does not match this host')
    _require(value.get('policy') == policy_identity(), 'record policy differs from current pool policy')


def validate_record(value: object, host: dict) -> dict:
    """Return slots for an exact legacy schema-1 record of this host and policy; raise otherwise."""
    _header(value, host, 1)
    slots = configuration_slots(value.get('configuration'))
    _require(feasible_slots(slots, host['memsizeBytes']), 'record slots exceed bounds or the memory budget')
    profiles.validate_evidence(value.get('evidence'), slots)
    return slots


def validate_profiles(value: object, host: dict) -> tuple[dict, ...]:
    """Return the usable profiles of an exact schema-2 record; raise on any defect."""
    _header(value, host, 2)
    rows = value.get('profiles')
    _require(isinstance(rows, list) and 1 <= len(rows) <= profiles.MAXIMUM_PROFILES,
             f'record needs 1-{profiles.MAXIMUM_PROFILES} profiles')
    usable = tuple(profiles.validate_profile(row, host['memsizeBytes']) for row in rows)
    _require(len({row['id'] for row in usable}) == len(usable), 'profile ids must be unique')
    return usable


@dataclass(frozen=True)
class Committed:
    """The host's usable profiles, where they came from and why a record was not used."""

    profiles: tuple = ()
    source: dict | None = None
    rejected: str | None = None
    legacy_qualified: bool = False  # a valid schema-1 record: older pool clients run qualified

    @property
    def needs_engine(self) -> bool:
        """Engine-bound profiles need the request's engine identity to be computed."""
        return any(profile['engine'] is not None for profile in self.profiles)


def _read(directory: Path, name: str) -> tuple[object, bytes]:
    """Read one private record file within its bound."""
    descriptor = open_private_dir(str(directory))
    try:
        data = read_private_file(descriptor, name, RECORD_LIMIT)
    finally:
        os.close(descriptor)
    return json.loads(data), data


def _load(directory: Path, version: int, host: dict) -> tuple:
    """(validated content, source) of one record file, (None, None) when absent; raises on defects.

    Schema 2 yields its usable profiles; schema 1 yields (record, slots).
    """
    name = RECORD_FILES[version]
    if not os.path.lexists(directory / name):
        return None, None
    value, data = _read(directory, name)
    content = validate_profiles(value, host) if version == 2 else (value, validate_record(value, host))
    return content, {'path': str(directory / name), 'sha256': hashlib.sha256(data).hexdigest(),
                     'schemaVersion': version}


def _read_version(directory: Path, version: int, host: dict) -> tuple:
    """(content, source, rejection) of one record file; a defect is recorded, not raised."""
    try:
        return (*_load(directory, version, host), None)
    except (DurableFileError, OSError, ValueError, KeyError, TypeError) as error:
        return None, None, f'{RECORD_FILES[version]}: {type(error).__name__}: {error}'


def committed(host: dict) -> Committed:
    """Read both records: schema-2 profiles, then the legacy profile for what they do not bound."""
    directory = record_directory()
    if directory is None:
        return Committed(rejected='non-canonical pool namespace never reads the host record')
    modern, modern_source, modern_error = _read_version(directory, 2, host)
    legacy, legacy_source, legacy_error = _read_version(directory, 1, host)
    usable = modern or ()
    bounded = {kind for profile in usable for kind in profile['workload']['formats']}
    extra = profiles.legacy_profile(*legacy, bounded) if legacy else None
    sources = [row for row in (modern_source, legacy_source if extra else None) if row]
    rejected = '; '.join(error for error in (modern_error, legacy_error) if error) or None
    return Committed((*usable, *([extra] if extra else [])), {'records': sources} if sources else None, rejected,
                     legacy is not None)


def mode_for(record: Committed, workload: dict, present: list[tuple] = ()) -> tuple[PoolMode, list[tuple]]:
    """The pool mode one workload gets, and the members outside its profile.

    Args:
        record: The committed profiles (committed()).
        workload: native_work_workload.describe() of the request.
        present: (nonce, workload, state) of every member (native_work_pool_mix.members).

    Returns:
        A qualified mode naming its profile with the (nonce, state) of members it does not
        cover, or exclusive mode with every unmatched reason.
    """
    source = record.source or {}
    if not record.profiles:
        return PoolMode('exclusive', record={**source, 'workload': workload}, rejected=record.rejected), []
    profile, unmatched, outside = profiles.select(record.profiles, workload, list(present))
    if profile is None:
        return PoolMode('exclusive', record={**source, 'workload': workload, 'unmatched': unmatched},
                        rejected='no qualification profile covers this workload'), []
    engine = profile['engine']['identity'] if profile['engine'] else None
    return PoolMode('qualified', dict(profile['slots']),
                    {**source, 'profile': profile['id'], 'legacy': profile['legacy'], 'engine': engine,
                     'workload': workload}), outside


def committed_mode(host: dict, workload: dict) -> PoolMode:
    """The mode the committed records give one workload, ignoring running members."""
    return mode_for(committed(host), workload)[0]


def forecast_mode(host: dict, output_seconds: float | None = None, fmt: str = 'short') -> PoolMode:
    """The forecast mode from known facts; Long geometry and stages require a bound project.

    Args:
        host: This host's identity.
        output_seconds: The longest authored output the forecast covers. None asks for the
            most any Short render could get (each profile at its own longest Short): the
            ceiling for native_batch --pool-slots, re-checked with real durations per launch.
        fmt: Explicit format; the two-argument Short default is unchanged.

    Returns:
        The covering profile's mode, or exclusive mode with the unmatched reasons.
    """
    record = committed(host)
    engine = workloads.current_engine() if record.needs_engine else None
    workload = workloads.forecast_workload(engine, output_seconds, fmt)
    if fmt == 'long':
        return PoolMode('exclusive', record={**(record.source or {}), 'workload': workload},
                        rejected='Long forecast lacks project-bound owner stages and picture geometry')
    if output_seconds is not None:
        return mode_for(record, workload)[0]
    limits = {None} | {(profile['workload']['formats'].get('short') or {}).get('maxDurationSeconds')
                       for profile in record.profiles}
    modes = [mode_for(record, workloads.forecast_workload(engine, limit))[0] for limit in limits]
    return max(modes, key=lambda mode: mode.slots.get('heavy', mode.slots.get('*', 1)))


def write_record(value: dict, host: dict) -> dict:
    """Durably publish one validated record (schema 1 or 2) in the private per-user folder."""
    version = value.get('schemaVersion') if isinstance(value, dict) else None
    _require(version in RECORD_FILES, 'unsupported record schema')
    if version == 2:
        validate_profiles(value, host)
    else:
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
    name = RECORD_FILES[version]
    try:
        write_pending_replace(child, (name + '.pending', name), data)
    finally:
        os.close(child)
    return {'path': str(directory / name), 'sha256': hashlib.sha256(data).hexdigest()}


def existing_profiles(host: dict) -> list[dict]:
    """Stored profiles of a valid schema-2 record, to merge a new one; raise if it is invalid."""
    directory = record_directory()
    _require(directory is not None, 'records are written only for the canonical host namespace')
    if not os.path.lexists(directory / RECORD_V2_NAME):
        return []
    value, _data = _read(directory, RECORD_V2_NAME)
    validate_profiles(value, host)
    return list(value['profiles'])


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
