"""Cold owner and parent-timing evidence for technical package measurements."""
from __future__ import annotations

from datetime import datetime
from pathlib import Path

from native_work_service_pins import document, fields, number, pin, require
from native_work_service_schema import UNITS, validate_contract, validate_dimensions
from native_work_service_provenance import owner_request, picture_identity

FACTS = ('unit', 'contract', 'dimensions', 'inputPins', 'outputPins', 'referenceMatched', 'unsupportedOperations')


def inspection(reference: dict) -> tuple[dict, dict]:
    """Consume the existing actual owned-completion reader, not a passed boolean."""
    from studio.owned_inspection import read_inspection
    fields(reference, 'path sha256 owner ownerSha256')
    for name, sha in (('path', 'sha256'), ('owner', 'ownerSha256')):
        file = Path(reference[name])
        pin({'path': reference[name], 'bytes': file.stat().st_size, 'sha256': reference[sha]})
    result = read_inspection(reference, require_owner_digest=True)
    owner_file = Path(reference['owner'])
    owner = document({'path': str(owner_file), 'bytes': owner_file.stat().st_size,
                      'sha256': reference['ownerSha256']})
    return result, owner


def validate_run(entry: dict, provenance: dict) -> dict:
    """Read parent timing only after both real preparation and measurement owners completed."""
    fields(entry, 'id role referenceId measurement')
    require(entry['role'] in ('training', 'held-out'), 'Invalid measurement role')
    value = document(entry['measurement'])
    fields(value, 'schemaVersion kind id unit contract dimensions preparation inspection timing referenceMatched '
                  'inputPins outputPins unsupportedOperations cacheEvidence')
    require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1
            and value['kind'] == 'native-long-review-package-service-run' and value['id'] == entry['id'],
            'Measurement identity changed')
    require(value['unit'] in UNITS and type(value['referenceMatched']) is bool, 'Invalid measured unit/reference')
    validate_contract(value['contract'])
    validate_dimensions(value['dimensions'])
    require(value['unsupportedOperations'] == [], 'Unmeasured operations cannot be adopted')
    validate_media_pins(value)
    prepared, preparation_owner = inspection(value['preparation'])
    result, owner = inspection(value['inspection'])
    owner_request(value['preparation'], preparation_owner, provenance, 'prepare')
    measured = owner_request(value['inspection'], owner, provenance, 'measure')
    require(measured.get('measurementId') == result.get('measurementId') == value['id'],
            'Owner result measurement identity differs')
    require(measured.get('preparation') == value['preparation'], 'Measurement owner used other preparation')
    require(measured.get('referenceId') == entry['referenceId'], 'Measurement owner comparison identity differs')
    require(prepared.get('kind') == 'native-long-review-package-technical-preparation',
            'Measurement inputs lack technical preparation')
    require(all(item in prepared.get('outputPins', []) for item in value['inputPins']),
            'Measured inputs differ from actual prepared media')
    require(result.get('kind') == 'native-long-review-package-technical-result'
            and all(result.get(key) == value[key] for key in FACTS), 'Worker and parent measurement differ')
    validate_timing(value['timing'], owner)
    return {**value, 'role': entry['role'], 'referenceId': entry['referenceId'],
            'pictureIdentity': picture_identity(prepared, value), 'comparison': measured.get('reference')}


def validate_media_pins(value: dict) -> None:
    """Reopen exact generated inputs and measured outputs; unbounded lists are refused."""
    for key in ('inputPins', 'outputPins'):
        rows = value[key]
        require(type(rows) is list and 0 < len(rows) <= 128, 'Invalid measurement media inventory')
        paths = [str(pin(row)) for row in rows]
        require(len(set(paths)) == len(paths), 'Duplicate measurement media pin')


def epoch(value: object) -> float:
    """Read the existing owner UTC timestamp without introducing a new clock authority."""
    require(type(value) is str, 'Missing owner timestamp')
    date = datetime.fromisoformat(value.replace('Z', '+00:00'))
    require(date.tzinfo is not None, 'Owner timestamp has no timezone')
    return date.timestamp()


def validate_timing(timing: dict, owner: dict) -> None:
    """Parent interval encloses the owner and all cleanup; queue is counted exactly once."""
    fields(timing, 'startedEpoch finishedEpoch grossSeconds queueSeconds serviceSeconds')
    require(all(number(value) for value in timing.values()), 'Invalid parent measurement timing')
    require(abs(timing['grossSeconds'] - (timing['finishedEpoch'] - timing['startedEpoch'])) <= .00001
            and abs(timing['serviceSeconds'] - (timing['grossSeconds'] - timing['queueSeconds'])) <= .00001,
            'Measurement timing arithmetic differs')
    require(timing['serviceSeconds'] > 0, 'Empty measured service interval')
    queue = owner.get('queue', {}).get('queueSeconds')
    require(number(queue) and abs(queue - timing['queueSeconds']) <= .00001, 'Queue deduction differs from owner')
    require(number(owner.get('elapsedSeconds')) and timing['grossSeconds'] >= owner['elapsedSeconds'],
            'Parent interval omits owner work or cleanup')
    require(timing['startedEpoch'] <= epoch(owner['startedAt']) + 1
            and timing['finishedEpoch'] + 1 >= epoch(owner['completedAt'])
            and epoch(owner['startedAt']) <= epoch(owner['nativeLaunchedAt']) <= epoch(owner['completedAt']),
            'Parent timing does not surround owned launch/completion')


def validate_cache(run: dict, host: dict) -> dict:
    """Validate observed filesystem conditions without claiming a new file is cold."""
    value = document(run['cacheEvidence'])
    fields(value, 'schemaVersion kind method regime filesystem observations')
    require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1
            and value['kind'] == 'native-service-cache-evidence', 'Invalid cache evidence')
    require(value['method'] == 'working-set-unknown' and value['regime'] == 'unknown'
            and value['filesystem'] == run['contract']['filesystem'], 'Default rate lacks unknown-cache evidence')
    facts = document(value['observations'])
    fields(facts, 'schemaVersion kind host filesystem method regime workingSetBytes readBytes physicalReadBytes passes notes')
    require(type(facts['schemaVersion']) is int and facts['schemaVersion'] == 1
            and facts['kind'] == 'native-service-cache-observations' and facts['host'] == host,
            'Cache observations provenance differs')
    require(all(facts[key] == value[key] for key in ('filesystem', 'method', 'regime')),
            'Cache observation method differs')
    from native_work_service_cache import observation_facts
    result, owner = inspection(run['inspection'])
    require(type(result.get('cacheObservation')) is dict, 'Measured owner did not bind cache observations')
    expected = observation_facts(result['cacheObservation'], run['inputPins'], owner['ownerIdentities'])
    require(facts == expected, 'Cache observations differ from owner-bound raw evidence')
    require(all(type(facts[key]) is int and facts[key] > 0 for key in ('workingSetBytes', 'readBytes', 'passes'))
            and type(facts['physicalReadBytes']) is int and facts['physicalReadBytes'] >= 0,
            'Cache observations lack measured IO')
    require(type(facts['notes']) is str and 0 < len(facts['notes'].strip()) <= 2048,
            'Cache method limitations were not recorded')
    return run['cacheEvidence']
