"""Owner-bound cache observation arithmetic; this module collects no physical IO.

Raw read passes must be emitted by the pinned measured worker. The current
calibration worker records unavailable observations, which cannot be adopted.
Future instrumentation must independently prove process and traversal coverage.
"""
from __future__ import annotations

from native_work_service_pins import fields, pin, require, text


def unobserved_cache(inputs: list[dict], filesystem: dict, host: dict) -> dict:
    """Record known working-set identity without inventing pass counts or physical counters."""
    return {'schemaVersion': 1, 'kind': 'native-service-owned-cache-observation', 'host': host,
            'filesystem': filesystem, 'method': 'working-set-unknown', 'regime': 'unknown',
            'workingSet': inputs, 'readPasses': None,
            'notes': 'Generated files may be warm. Complete logical read volume and kernel-attributed '
                     'physical read bytes are unavailable; these observations cannot support rate adoption.'}


def logical_bytes(reads: object, working_set: list[dict]) -> int | None:
    """Sum actual returned byte counts, retaining repeated reads separately from distinct bytes."""
    if reads is None:
        return None
    require(type(reads) is list and 0 < len(reads) <= 16384, 'Invalid bounded logical read inventory')
    total = 0
    for row in reads:
        fields(row, 'input returnedBytes')
        require(row['input'] in working_set and type(row['returnedBytes']) is int
                and 0 <= row['returnedBytes'] <= row['input']['bytes'], 'Logical read exceeds admitted input')
        total += row['returnedBytes']
    return total


def physical_bytes(samples: object, identities: list[dict]) -> int | None:
    """Recompute kernel deltas for the exact owner process inventory; zero is an observation."""
    if samples is None:
        return None
    require(type(samples) is list and 0 < len(samples) <= 1024, 'Invalid bounded kernel IO inventory')
    observed, total = [], 0
    for row in samples:
        fields(row, 'method identity before after')
        require(row['method'] == 'proc_pid_rusage-v2' and row['identity'] in identities,
                'Physical IO sample lacks exact owned process identity')
        before, after = row['before'], row['after']
        fields(before, 'processStart absoluteTime diskReadBytes')
        fields(after, 'processStart absoluteTime diskReadBytes')
        require(all(type(value) is int and value >= 0 for value in [*before.values(), *after.values()])
                and before['processStart'] > 0 and before['processStart'] == after['processStart']
                and before['absoluteTime'] < after['absoluteTime']
                and before['diskReadBytes'] <= after['diskReadBytes'], 'Invalid same-process kernel IO delta')
        observed.append(row['identity'])
        total += after['diskReadBytes'] - before['diskReadBytes']
    require(len(observed) == len(identities) and all(observed.count(row) == 1 for row in identities),
            'Kernel IO omitted or duplicated owned processes')
    return total


def observation_facts(observation: dict, inputs: list[dict], identities: list[dict]) -> dict:
    """Derive public cache facts only from exact owner-bound inputs and raw observations."""
    fields(observation, 'schemaVersion kind host filesystem method regime workingSet readPasses notes')
    require(type(observation['schemaVersion']) is int and observation['schemaVersion'] == 1
            and observation['kind'] == 'native-service-owned-cache-observation'
            and observation['method'] == 'working-set-unknown' and observation['regime'] == 'unknown',
            'Invalid owner cache observation contract')
    require(observation['workingSet'] == inputs and type(inputs) is list and 0 < len(inputs) <= 128
            and len({row['path'] for row in inputs}) == len(inputs), 'Owner working set differs from measured inputs')
    for row in inputs:
        pin(row)
    require(text(observation['notes'], 2048), 'Cache method limitations were not recorded')
    passes = observation['readPasses']
    require(passes is None or type(passes) is list and 0 < len(passes) <= 64, 'Invalid observed read-pass inventory')
    readings = [_read_pass(row, inputs, identities) for row in passes or []]
    return {'schemaVersion': 1, 'kind': 'native-service-cache-observations',
            **{key: observation[key] for key in ('host', 'filesystem', 'method', 'regime', 'notes')},
            'workingSetBytes': sum(row['bytes'] for row in inputs),
            'readBytes': _total(readings, 0), 'physicalReadBytes': _total(readings, 1),
            'passes': len(passes) if passes is not None else None}


def _read_pass(row: dict, inputs: list[dict], identities: list[dict]) -> tuple[int | None, int | None]:
    """Read one worker-recorded traversal, never equating file size with bytes returned."""
    fields(row, 'logicalReads kernelSamples')
    return logical_bytes(row['logicalReads'], inputs), physical_bytes(row['kernelSamples'], identities)


def _total(rows: list[tuple], index: int) -> int | None:
    """An unobserved member makes the full total unavailable rather than zero."""
    return sum(row[index] for row in rows) if rows and all(row[index] is not None for row in rows) else None
