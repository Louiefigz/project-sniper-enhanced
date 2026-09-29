"""Measured evidence for one pool qualification batch, read from the owners' own receipts.

Per job: every owner receipt at the attempt or one folder inside it (the audio stage runs
in <attempt>/audio-stage): label, pool class and mode, queue, pressure-wait and elapsed
seconds, one-minute load average at admission, verified cleanup and failure category;
every resource sample; what the job exercised (format and output seconds from its plan,
picture pixels, normalized owner stages, source-cache state, own or prepared audio) and
the bytes its attempt folder holds. Batch: the peak number of jobs with a heavy owner
admitted at the same instant, peak simultaneous heavy and audio owners and audio owners
overlapping heavy ones (own audio stages counted separately), the aggregate owned-memory
peak (each owner's maximum in a five-second bucket, summed across every owner, so
simultaneous owners of one job add up), the highest kernel pressure level, the lowest
free-memory percentage and the lowest free disk. Samples are the owners' five-second
readings; spikes between readings are not observed. CPU: the load average each owner's
admission recorded, plus the owner receipt's identity-bound CPU summary ('cpu', owned CPU
seconds, peak owned cores, peak host busy fraction) when the engine records one; owners
without it contribute nothing to those figures.

Cache state: 'cold' when every source entry was decoded during the batch (by this job or a
concurrent one it waited for), 'warm' when every entry was a store hit, 'partial' for a
mix; a job with no source-cache receipt records none and cannot qualify a profile.
"""
from __future__ import annotations

import json
import os
import stat
from datetime import datetime
from pathlib import Path

from cut_preview_io import bound_json, read_bytes
from native_work_profiles import STATUS_FORMATS
from native_work_workload import plan_bounds, stage_label

BUCKET_SECONDS = 5.0
FULL_STATUSES = frozenset(STATUS_FORMATS)
PREVIEW_STATUS = 'native-motion-previews-complete'
DECODED = frozenset({'published-by-this-job', 'published-by-another-live-job'})
OWNER_PATTERNS = ('*.render.json', '*/*.render.json')
SAMPLE_PATTERNS = ('*.resources.jsonl', '*/*.resources.jsonl')


def _epoch(value: object) -> float | None:
    """Receipt UTC timestamps as epoch seconds; absent stays absent."""
    return datetime.fromisoformat(value).timestamp() if isinstance(value, str) else None


def _owner(path: Path) -> dict:
    """Summarize one owner receipt without interpreting its media."""
    value = bound_json(path)
    pool = value.get('pool') if isinstance(value.get('pool'), dict) else {}
    cleanup = value.get('cleanup') if isinstance(value.get('cleanup'), dict) else {}
    load = pool.get('loadAverage') if isinstance(pool.get('loadAverage'), list) else [None]
    cpu = value.get('cpu') if isinstance(value.get('cpu'), dict) else {}
    return {'label': path.name[:-len('.render.json')], 'status': value.get('status'),
            'class': pool.get('class'), 'mode': pool.get('mode'), 'member': pool.get('member'),
            'admittedAtEpoch': pool.get('admittedAtEpoch'), 'completedAtEpoch': _epoch(value.get('completedAt')),
            'queueSeconds': value.get('queueSeconds'), 'pressureWaitSeconds': value.get('pressureWaitSeconds'),
            'elapsedSeconds': value.get('elapsedSeconds'), 'failureCategory': value.get('failureCategory'),
            'loadAverage1m': load[0] if load else None, 'ownedCpuSeconds': cpu.get('observedOwnedCpuSeconds'),
            'peakOwnedCores': cpu.get('peakOwnedCores'), 'peakHostBusyFraction': cpu.get('peakHostBusyFraction'),
            'cleanupVerified': cleanup.get('verified') is True and value.get('leaseCleanupVerified') is True}


def _files(attempt: Path, patterns: tuple[str, ...]) -> list[Path]:
    """Files at the attempt or one folder inside it, in path order."""
    return sorted(path for pattern in patterns for path in attempt.glob(pattern))


def owners(attempt: Path) -> list[dict]:
    """All owner receipts of one attempt, in path order."""
    return [_owner(path) for path in _files(attempt, OWNER_PATTERNS)]


def samples(attempt: Path, job: str) -> list[dict]:
    """Every resource reading the attempt's owners recorded, tagged with its owner file."""
    rows = []
    for path in _files(attempt, SAMPLE_PATTERNS):
        owner = f'{job}/{path.relative_to(attempt)}'
        for line in read_bytes(path).decode().splitlines():
            value = json.loads(line)
            rows.append({'job': job, 'owner': owner, 'at': value['measured_at'],
                         'owned': value['owned_footprint_bytes'], 'pressure': value['kernel_pressure_level'],
                         'free': value['free_percent'], 'disk': value['disk_free_bytes']})
    return rows


def cache_state(attempt: Path) -> dict:
    """Source-cache outcomes of every acquisition receipt; state None when none was recorded."""
    outcomes: dict[str, set] = {}
    for path in _files(attempt, ('source-cache.json', '*/source-cache.json')):
        for entry in bound_json(path).get('entries') or []:
            outcomes.setdefault(entry.get('contentKey'), set()).add(entry.get('outcome'))
    decoded = sum(1 for values in outcomes.values() if values & DECODED)
    hits = sum(1 for values in outcomes.values() if values == {'store-hit'})
    state = None
    if outcomes and decoded + hits == len(outcomes):
        state = 'cold' if not hits else 'warm' if not decoded else 'partial'
    return {'cacheState': state, 'decodedEntries': decoded, 'storeHitEntries': hits}


def _audio(attempt: Path, rows: list[dict]) -> dict:
    """Whether the job ran its own audio stage, or took prepared/imported audio."""
    request = bound_json(attempt / 'export-request.json') if (attempt / 'export-request.json').is_file() else {}
    stage = request.get('audioStage') if isinstance(request.get('audioStage'), dict) else {}
    own = stage.get('mode') == 'attempt' and any(row['label'] == 'audio-stage' and row['class'] == 'audio'
                                                 for row in rows)
    prepared = stage.get('mode') not in (None, 'attempt') \
        or bool(request.get('audioDonor') or request.get('preparedMaster'))
    return {'ownAudioStage': own, 'preparedAudio': prepared}


def _attempt_bytes(attempt: Path) -> int:
    """Bytes the attempt's regular files occupy: symlinks not followed, hard links counted once."""
    files = (os.lstat(os.path.join(folder, name)) for folder, _directories, names in os.walk(attempt)
             for name in names)
    return sum({(info.st_dev, info.st_ino): info.st_size for info in files if stat.S_ISREG(info.st_mode)}.values())


def job_evidence(job: dict, attempt: Path) -> dict:
    """Delivery status, owner timings, exercised workload and totals for one exporter invocation."""
    delivery = bound_json(attempt / 'delivery.json') if (attempt / 'delivery.json').is_file() else {}
    rows = owners(attempt) if attempt.is_dir() else []
    kind, seconds, pixels = plan_bounds(Path(job['project'])) if job.get('project') else (None, None, None)
    facts = {**cache_state(attempt), **_audio(attempt, rows), 'attemptBytes': _attempt_bytes(attempt)} \
        if attempt.is_dir() else {'cacheState': None, 'ownAudioStage': False, 'preparedAudio': False, 'attemptBytes': 0}
    return {**job, 'status': delivery.get('status'), 'deliveryElapsedSeconds': delivery.get('elapsedSeconds'),
            'owners': rows, 'queueSeconds': sum(row['queueSeconds'] or 0 for row in rows),
            'ownerSeconds': sum(row['elapsedSeconds'] or 0 for row in rows),
            'allOwnersCleanupVerified': bool(rows) and all(row['cleanupVerified'] for row in rows),
            'fullExport': delivery.get('status') in FULL_STATUSES,
            'format': STATUS_FORMATS.get(delivery.get('status')), 'planFormat': kind,
            'durationSeconds': seconds, 'pixels': pixels,
            'stages': sorted({stage_label(row['label']) for row in rows}), **facts}


def _owner_events(jobs: list[dict]) -> list[tuple]:
    """(instant, change, job, counter) for every owner with an admission and completion.

    The counter is its class, or 'audio-stage' for an audio-class own audio stage (the only
    audio work that backs a mixed class claim; preview packaging is audio-class too).
    """
    rows = [(job['id'], row, 'audio-stage' if row['class'] == 'audio' and row['label'] == 'audio-stage'
             else row['class']) for job in jobs for row in job['owners']
            if row['class'] in ('heavy', 'audio') and row['admittedAtEpoch'] and row['completedAtEpoch']]
    return sorted((event for job, row, counter in rows
                   for event in ((row['admittedAtEpoch'], 1, job, counter),
                                 (row['completedAtEpoch'], -1, job, counter))),
                  key=lambda item: (item[0], item[1]))


def _peaks(peaks: dict, active: dict, holding: int) -> None:
    """Raise every running maximum to the current instant's counts."""
    audio = active['audio'] + active['audio-stage']
    for key, value in (('jobsWithHeavyPeak', holding), ('heavyOwnersPeak', active['heavy']),
                       ('audioOwnersPeak', audio), ('audioWithHeavyPeak', audio if active['heavy'] else 0),
                       ('audioStageWithHeavyPeak', active['audio-stage'] if active['heavy'] else 0)):
        peaks[key] = max(peaks[key], value)


def overlap(jobs: list[dict]) -> dict:
    """Peak jobs holding heavy work, heavy and audio owners, and audio (or own audio-stage)
    owners beside heavy ones. Ends sort before starts at one instant, so back-to-back owners
    never overlap."""
    heavy_jobs: dict[str, int] = {}
    active = {'heavy': 0, 'audio': 0, 'audio-stage': 0}
    peaks = dict.fromkeys(('jobsWithHeavyPeak', 'heavyOwnersPeak', 'audioOwnersPeak', 'audioWithHeavyPeak',
                           'audioStageWithHeavyPeak'), 0)
    for _at, change, job, counter in _owner_events(jobs):
        active[counter] += change
        if counter == 'heavy':
            heavy_jobs[job] = heavy_jobs.get(job, 0) + change
        _peaks(peaks, active, sum(1 for count in heavy_jobs.values() if count > 0))
    return peaks


def peak_concurrency(jobs: list[dict]) -> int:
    """Most jobs holding an admitted heavy owner at the same instant."""
    return overlap(jobs)['jobsWithHeavyPeak']


def resource_summary(rows: list[dict]) -> dict:
    """Aggregate owned memory per five-second bucket (per-owner maximum, summed) plus extremes."""
    buckets: dict[int, dict[str, int]] = {}
    for row in rows:
        bucket = buckets.setdefault(int(row['at'] // BUCKET_SECONDS), {})
        bucket[row['owner']] = max(bucket.get(row['owner'], 0), row['owned'])
    totals = [sum(bucket.values()) for bucket in buckets.values()]
    return {'samples': len(rows), 'bucketSeconds': BUCKET_SECONDS,
            'aggregatePeakOwnedBytes': max(totals, default=0),
            'maximumKernelPressureLevel': max((row['pressure'] for row in rows), default=None),
            'minimumFreePercent': min((row['free'] for row in rows), default=None),
            'minimumDiskFreeBytes': min((row['disk'] for row in rows), default=None),
            'scope': 'owner five-second samples; spikes between readings are unobserved'}


def batch_evidence(jobs: list[dict], attempts: dict[str, Path]) -> dict:
    """Per-job evidence plus batch concurrency and resource extremes."""
    evidence = [job_evidence(job, attempts[job['id']]) for job in jobs]
    rows = [row for job in evidence for row in samples(attempts[job['id']], job['id'])
            if attempts[job['id']].is_dir()]
    peaks = overlap(evidence)
    return {'jobs': evidence, 'peakConcurrentJobs': peaks['jobsWithHeavyPeak'], 'overlap': peaks,
            **resource_summary(rows)}


def studio_views() -> list[dict]:
    """Managed Studio views registered in this pool namespace now (project and state only)."""
    from studio import managed_preview_registry as registry
    with registry.transaction(registry.monotonic_until(10)) as handle:
        return sorted(({'project': row['project'], 'state': row['state']} for row in registry.entries(handle)),
                      key=lambda row: row['project'])
