"""Measured joint coverage and independent held-out adoption for service cells."""
from __future__ import annotations

from native_work_service_pins import document, fields, identity, pin, require, text
from native_work_service_runs import validate_cache, validate_run
from native_work_service_schema import BOUND_DIMENSIONS, within_bounds


def validate_evidence(row: dict, host: dict, policy: dict) -> None:
    """Recompute measured bounds/ceilings and require separately recorded validation."""
    fields(row['measurement'], 'manifest')
    manifest = document(row['measurement']['manifest'])
    fields(manifest, 'schemaVersion kind host policy engine tools harness runs failures')
    require(type(manifest['schemaVersion']) is int and manifest['schemaVersion'] == 1
            and manifest['kind'] == 'native-long-review-package-measurements', 'Invalid measurements manifest')
    require(manifest['host'] == host and manifest['policy'] == policy
            and all(manifest[key] == row[key] for key in ('engine', 'tools', 'harness')),
            'Measurement manifest provenance differs')
    entries = manifest['runs']
    require(type(entries) is list and 0 < len(entries) <= 256, 'Invalid measured run inventory')
    require(all(type(entry) is dict and text(entry.get('id'), 96) for entry in entries), 'Invalid measured run id')
    require(len({entry['id'] for entry in entries}) == len(entries), 'Duplicate measured run')
    provenance = {key: row[key] for key in ('engine', 'tools', 'harness')}
    runs = {entry['id']: validate_run(entry, provenance) for entry in entries}
    failures = validate_failures(manifest['failures'], runs)
    for run in runs.values():
        validate_reference(run, runs)
    for cell in row['cells']:
        validate_coverage(cell, runs)
    validate_adoption(row, runs, (host, failures))


def validate_failures(entries: object, runs: dict) -> list[str]:
    """Retain failed attempts as evidence without treating them as successful time samples."""
    require(type(entries) is list and len(entries) <= 256, 'Failure evidence exceeds bound')
    names = []
    for entry in entries:
        fields(entry, 'id owner diagnostic')
        require(text(entry['id'], 96) and entry['id'] not in runs and entry['id'] not in names,
                'Duplicate or invalid failure id')
        names.append(entry['id'])
        validate_failure(entry)
    return sorted(names)


def validate_failure(entry: dict) -> None:
    """A failure row must name actual retained owner or diagnostic bytes."""
    require(entry['owner'] is not None or entry['diagnostic'] is not None, 'Failure has no retained evidence')
    if entry['owner'] is not None:
        owner = document(entry['owner'])
        require(owner.get('status') == 'failed' and bool(owner.get('completedAt')),
                'Failure evidence is not a terminal failed owner')
    if entry['diagnostic'] is not None:
        pin(entry['diagnostic'])


def validate_reference(run: dict, runs: dict) -> None:
    """Reference equivalence uses actual same-input serial owner evidence."""
    reference = run['referenceId']
    if reference is None:
        require(run['comparison'] is None and run['referenceMatched'] is False
                and run['contract']['execution']['ownedConcurrency'] == 1,
                'A reference must be an honest serial baseline')
        return
    require(type(reference) is str and reference in runs and reference != run['id'], 'Unknown run reference')
    source = runs[reference]
    require(run['comparison'] == source['inspection'], 'Owner compared against another serial reference')
    require(source['referenceId'] is None and source['contract']['execution']['ownedConcurrency'] == 1,
            'Reference chain is not a serial baseline')
    left = {key: value for key, value in source['contract'].items() if key != 'execution'}
    right = {key: value for key, value in run['contract'].items() if key != 'execution'}
    require(run['referenceMatched'] is True and source['unit'] == run['unit'] and left == right
            and source['dimensions'] == run['dimensions'] and source['inputPins'] == run['inputPins'],
            'Run does not match its same-input serial reference')


def validate_coverage(cell: dict, runs: dict) -> None:
    """Use jointly exercised maxima and held-out cases, never Cartesian invented coverage."""
    names = cell['runIds'] + cell['heldOutRunIds']
    require(all(name in runs for name in names), 'Service cell names unknown measured runs')
    training = [runs[name] for name in cell['runIds']]
    held = [runs[name] for name in cell['heldOutRunIds']]
    require(all(run['role'] == 'training' for run in training)
            and all(run['role'] == 'held-out' and run['referenceId'] is not None for run in held),
            'Service cell training/held-out roles differ')
    require(all(run['contract'] == cell['contract'] and run['unit'] == cell['unit']
                and within_bounds(run['dimensions'], cell['bounds']) for run in training + held),
            'Measured run lies outside exact service cell conditions')
    dimensions = [run['dimensions'] for run in training]
    bounds = cell['bounds']
    require(bounds['minFrames'] == min(value['frames'] for value in dimensions),
            'Service minimum frame range was not exercised')
    require(any(all(value[key] == bounds[name] for name, key in BOUND_DIMENSIONS.items())
                for value in dimensions), 'Service upper bounds were not jointly exercised')
    ceiling = round(max(run['timing']['serviceSeconds'] for run in training) * cell['marginFactor'], 6)
    require(cell['ceilingSeconds'] == ceiling, 'Service ceiling differs from measured arithmetic')
    require(all(run['timing']['serviceSeconds'] <= ceiling for run in held), 'Held-out service exceeds ceiling')
    require(all(all(run['preparation'] != original['preparation'] and run['pictureIdentity'] != original['pictureIdentity']
                    for original in training) for run in held), 'Held-out work repeats training media')


def validate_adoption(row: dict, runs: dict, context: tuple) -> None:
    """Require a separate independent artifact covering every held-out and cache proof."""
    adoption = fields(row['adoption'], 'validation recordedBy recordedAt')
    require(text(adoption['recordedBy'], 128) and text(adoption['recordedAt']), 'Invalid rate adoption recorder')
    value = document(adoption['validation'])
    fields(value, 'schemaVersion kind measurement rateIdentity heldOutRunIds validator cacheEvidence failureIds passed')
    require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1
            and value['kind'] == 'native-long-review-package-service-validation' and value['passed'] is True,
            'Rate validation is not passing independent evidence')
    body = {key: item for key, item in row.items() if key not in ('adoption', 'writtenAt')}
    require(value['measurement'] == row['measurement']['manifest'] and value['rateIdentity'] == identity(body),
            'Independent validation binds another rate or measurement')
    validator = fields(value['validator'], 'recordedBy implementation')
    require(validator['recordedBy'] == adoption['recordedBy'], 'Independent validator recorder differs')
    pin(validator['implementation'])
    require(validator['implementation'] != row['harness'], 'Measurement harness cannot adopt its own rate')
    expected = sorted({name for cell in row['cells'] for name in cell['heldOutRunIds']})
    require(value['heldOutRunIds'] == expected, 'Independent validation omitted held-out cases')
    host, failures = context
    require(value['failureIds'] == failures, 'Independent validation omitted failed attempts')
    selected = sorted({name for cell in row['cells'] for name in cell['runIds'] + cell['heldOutRunIds']})
    cache = {identity(validate_cache(runs[name], host)): runs[name]['cacheEvidence'] for name in selected}
    require(type(value['cacheEvidence']) is list and len(value['cacheEvidence']) == len(cache)
            and {identity(item) for item in value['cacheEvidence']} == set(cache),
            'Independent validation omitted unknown-cache observations')
