"""Turn one judged qualification batch into a versioned host profile, or say why not.

The profile binds the engine identity frozen before the batch started (and re-read after
it ended), the candidate configuration, the claimed class mix and the workload bounds its
jobs exercised (native_work_profiles.derived_bounds), with CPU, memory, disk, throughput,
failure and cleanup measurements. A 'mixed' claim is refused unless the batch's own
audio-stage owners overlapped heavy owners. The profile is merged into the host's schema-2
record: a profile with the same id is replaced and the others are kept; an existing
schema-2 record that no longer validates is never overwritten (move it aside first).
"""
from __future__ import annotations

from datetime import datetime, timezone

import native_work_qualification as qualification
from native_work_profiles import MAXIMUM_PROFILES, derived_bounds, mixed_reasons, nonnegative_number

JOB_KEYS = ('id', 'project', 'attempt', 'reference', 'status', 'passed', 'referenceMatched', 'wallSeconds',
            'queueSeconds', 'format', 'stages', 'durationSeconds', 'pixels', 'cacheState', 'decodedEntries',
            'storeHitEntries', 'ownAudioStage', 'preparedAudio', 'attemptBytes')
CPU_SCOPE = ('one-minute load average recorded at each owner admission; owned CPU seconds, peak owned cores '
             'and peak host busy fraction from owner receipts that carry the identity-bound CPU summary '
             '(ownersWithCpu of owners; None when no owner recorded one)')
STUDIO_SCOPE = ('managed Studio views registered in this pool namespace at batch start and end; the harness '
                'records their overlap, it generates no Studio load')


def _job_refusals(job: dict) -> list[str]:
    """What one job did not record that a profile bound needs."""
    reasons = []
    if job.get('format') is None or job.get('planFormat') != job.get('format'):
        reasons.append(f"job {job['id']}: delivered status {job.get('status')!r} from a "
                       f"{job.get('planFormat')} project is not a Short or Long final export")
    if job.get('durationSeconds') is None or job.get('pixels') is None:
        reasons.append(f"job {job['id']}: its project plan does not state output duration and picture size")
    if job.get('cacheState') is None:
        reasons.append(f"job {job['id']}: no source-cache receipt records a cold, partial or warm cache")
    return reasons


def profile_refusals(summary: dict, claim: str, engines: tuple[dict, dict]) -> list[str]:
    """Every reason the batch cannot become a profile beyond the pool-size refusals."""
    before, after = engines
    reasons = ['the engine changed during the qualification batch'] if before != after else []
    for job in summary['jobs']:
        reasons += _job_refusals(job)
    if claim == 'mixed':
        slots = qualification.configuration_slots(summary['configuration'])
        reasons += [f'mixed class claim refused: {reason}' for reason in mixed_reasons(summary, slots)]
    return reasons


def _throughput(jobs: list[dict], wall: float) -> dict:
    """Authored output seconds per batch wall second, overall and by cache state."""
    output = sum(job['durationSeconds'] for job in jobs)
    states: dict[str, dict] = {}
    for job in jobs:
        row = states.setdefault(job['cacheState'], {'jobs': 0, 'outputSeconds': 0.0, 'jobWallSeconds': 0.0})
        row['jobs'] += 1
        row['outputSeconds'] += job['durationSeconds']
        row['jobWallSeconds'] += job['wallSeconds'] or 0.0
    return {'outputSeconds': output, 'batchWallSeconds': wall,
            'outputSecondsPerWallSecond': output / wall if wall > 0 else 0.0, 'byCacheState': states}


def _cpu(owners: list[dict], logical: int) -> dict:
    """Admission load plus the owners' recorded CPU summaries, where present."""
    loads = [owner['loadAverage1m'] for owner in owners if nonnegative_number(owner['loadAverage1m'])]
    measured = [owner for owner in owners if nonnegative_number(owner.get('ownedCpuSeconds'))]
    def peak(key: str) -> float | None:
        """Largest recorded value of one owner CPU field."""
        return max((owner[key] for owner in measured if nonnegative_number(owner.get(key))), default=None)
    return {'logicalCpus': logical, 'maximumAdmissionLoad1m': max(loads, default=None),
            'maximumAdmissionLoadPerCpu': max(loads) / logical if loads else None,
            'ownedCpuSeconds': sum(owner['ownedCpuSeconds'] for owner in measured) if measured else None,
            'peakOwnedCores': peak('peakOwnedCores'), 'peakHostBusyFraction': peak('peakHostBusyFraction'),
            'ownersWithCpu': len(measured), 'scope': CPU_SCOPE}


def metrics(summary: dict) -> dict:
    """CPU, memory, disk, throughput, failure, cleanup and Studio-overlap figures of one batch."""
    jobs = summary['jobs']
    owners = [owner for job in jobs for owner in job['owners']]
    return {
        'cpu': _cpu(owners, summary['host']['logicalCpus']),
        'studio': {'viewsAtStart': summary.get('studioViewsAtStart'), 'viewsAtEnd': summary.get('studioViewsAtEnd'),
                   'scope': STUDIO_SCOPE},
        'memory': {key: summary[key] for key in ('aggregatePeakOwnedBytes', 'minimumFreePercent',
                                                 'maximumKernelPressureLevel', 'bucketSeconds', 'samples')},
        'disk': {'minimumDiskFreeBytes': summary['minimumDiskFreeBytes'],
                 'maximumAttemptBytes': max((job['attemptBytes'] for job in jobs), default=None),
                 'totalAttemptBytes': sum(job['attemptBytes'] for job in jobs)},
        'throughput': _throughput(jobs, summary['batchWallSeconds']),
        'failures': {'failedJobs': sum(1 for job in jobs if not job.get('passed')),
                     'failedOwners': sum(1 for owner in owners if owner['failureCategory']),
                     'deadlineExceeded': summary['deadlineExceeded']},
        'cleanup': {'owners': len(owners),
                    'unverifiedOwners': sum(1 for owner in owners if not owner['cleanupVerified'])}}


def build_profile(summary: dict, summary_sha: str, claim: str) -> dict:
    """One schema-2 profile from a judged, refusal-free batch summary."""
    jobs = [{key: row.get(key) for key in JOB_KEYS} for row in summary['jobs']]
    bounds = derived_bounds(jobs, claim)
    configuration = summary['configuration']
    engine = summary['engine']
    evidence = {'allJobsPassed': summary['allJobsPassed'], 'fullExports': summary['fullExports'],
                'peakConcurrentJobs': summary['peakConcurrentJobs'], 'overlap': summary['overlap'], 'jobs': jobs,
                'summarySha256': summary_sha, 'evidenceDirectory': summary['evidenceDirectory'], **metrics(summary)}
    name = (f"{'_'.join(bounds['formats'])}-{claim}-h{configuration['heavySlots']}a{configuration['audioSlots']}"
            f"-{engine['identity'][:12]}")
    return {'id': name, 'engine': engine, 'configuration': configuration, 'workload': bounds,
            'evidence': evidence, 'harness': summary['harness'],
            'writtenAt': datetime.now(timezone.utc).isoformat()}


def write_profile(summary: dict, summary_sha: str, claim: str) -> dict:
    """Merge the batch's profile into the host's schema-2 record and publish it."""
    profile = build_profile(summary, summary_sha, claim)
    host = summary['host']
    kept = [row for row in qualification.existing_profiles(host) if row['id'] != profile['id']]
    if len(kept) >= MAXIMUM_PROFILES:
        raise qualification.PoolRecordError(f'the host record already holds {MAXIMUM_PROFILES} other profiles')
    record = {'schemaVersion': 2, 'kind': qualification.RECORD_KIND, 'host': host, 'policy': summary['policy'],
              'profiles': [*kept, profile]}
    written = qualification.write_record(record, host)
    legacy = qualification.record_directory() / qualification.RECORD_NAME
    return {**written, 'profile': profile['id'], 'profilesKept': [row['id'] for row in kept],
            'supersedesLegacyRecord': str(legacy) if legacy.exists() else None}
