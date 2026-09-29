"""Exact rate-only cells bound to current implementation and measured workloads."""
from __future__ import annotations

from fractions import Fraction
from pathlib import Path

from native_work_pool_policy import policy_identity
from native_work_service_pins import digest, fields, identity, number, pin, require, text

KIND = 'native-long-review-package-service-v1'
UNITS = ('build-and-seal', 'cold-proof-read')
BOUND_DIMENSIONS = {'maxFrames': 'frames', 'maxWindows': 'windows', 'maxPictureBytes': 'pictureBytes',
                    'maxPeakBitrate': 'peakBitrate', 'maxMasterBytes': 'masterBytes',
                    'maxReferenceBytes': 'referenceBytes', 'maxPinnedInputBytes': 'pinnedInputBytes',
                    'maxProofFiles': 'proofFiles'}
# peakBitrate is ceil(max sealed-window bytes * 8 * fps): a conservative
# per-frame upper bound, not a claimed observed packet peak. Both readers and
# harness use this same stat-derived predictor without an unowned media probe.


def current_bindings() -> tuple[dict, dict]:
    """Resolve actual engine and tool executables, never values from rate evidence."""
    from native_work_workload import engine_record
    from studio.native_run_config import local_environment
    tools, _environment = local_environment()
    return engine_record(), {name: str(Path(tools[name]).resolve(strict=True)) for name in ('ffmpeg', 'ffprobe')}


def validate_document(value: dict, host: dict) -> list[dict]:
    """Require the closed host sidecar and all its currently proven service rows."""
    fields(value, 'schemaVersion kind host policy serviceRates writtenAt')
    require(type(value['schemaVersion']) is int and value['schemaVersion'] == 1
            and value['kind'] == 'sniper-native-service-rates', 'Unsupported service-rate schema')
    require(identity(value['host']) == identity(host) and identity(value['policy']) == identity(policy_identity()),
            'Service-rate host/policy differs')
    require(text(value['writtenAt']), 'Service-rate writtenAt invalid')
    rows = value['serviceRates']
    require(type(rows) is list and len(rows) <= 16, 'Service-rate rows exceed bound')
    bindings = current_bindings()
    for row in rows:
        validate_row(row, (host, value['policy'], bindings))
    require(len({row['id'] for row in rows}) == len(rows), 'Duplicate service-rate id')
    return rows


def validate_row(row: dict, context: tuple) -> None:
    """Validate current provenance, cells, measured arithmetic and independent adoption."""
    fields(row, 'id kind engine tools harness cells measurement adoption writtenAt')
    require(text(row['id'], 96) and row['kind'] == KIND and text(row['writtenAt']), 'Invalid service-rate identity')
    host, policy, bindings = context
    engine, tools = bindings
    fields(row['engine'], 'identity files')
    require(row['engine'] == engine and digest(row['engine']['identity'])
            and type(row['engine']['files']) is int and row['engine']['files'] > 0, 'Service-rate engine changed')
    fields(row['tools'], 'ffmpeg ffprobe')
    for name, value in row['tools'].items():
        fields(value, 'executable version')
        require(str(pin(value['executable'])) == tools[name], 'Service-rate tool executable changed')
        pin(value['version'])
    pin(row['harness'])
    require(type(row['cells']) is list and 0 < len(row['cells']) <= 64, 'Invalid service-rate cells')
    for cell in row['cells']:
        validate_cell(cell)
    require(len({cell['id'] for cell in row['cells']}) == len(row['cells']), 'Duplicate service cell')
    from native_work_service_evidence import validate_evidence
    validate_evidence(row, host, policy)


def validate_cell(cell: dict) -> None:
    """Check the fixed measured ceiling cell; no capacity or freely fitted coefficients."""
    fields(cell, 'id unit contract bounds runIds heldOutRunIds marginFactor ceilingSeconds')
    require(text(cell['id'], 96) and cell['unit'] in UNITS, 'Invalid service cell identity/unit')
    validate_contract(cell['contract'])
    require(cell['contract']['execution']['ownedConcurrency'] == 1,
            'Only serial service cells are adoptable; capacity evidence is separate')
    require(cell['contract']['cacheRegime'] == 'unknown', 'Warm service cells cannot become default rates')
    validate_bounds(cell['bounds'])
    for key in ('runIds', 'heldOutRunIds'):
        rows = cell[key]
        require(type(rows) is list and 0 < len(rows) <= 256 and all(text(item, 96) for item in rows)
                and len(set(rows)) == len(rows), 'Service cell run IDs invalid')
    require(not set(cell['runIds']) & set(cell['heldOutRunIds']), 'Training and held-out runs overlap')
    require(number(cell['marginFactor']) and cell['marginFactor'] >= 1
            and number(cell['ceilingSeconds'], True), 'Invalid measured service ceiling')


def validate_contract(value: dict) -> None:
    """Require exact media, filesystem and cold-reader implementation conditions."""
    fields(value, 'format stage canvas encoderContractSha256 audio filesystem cacheRegime execution proofPlanVersion')
    require(value['format'] == 'long' and value['stage'] == 'review-package', 'Rate is not a Long package')
    canvas = fields(value['canvas'], 'width height frameRate')
    require(all(type(canvas[key]) is int and canvas[key] > 0 for key in ('width', 'height')),
            'Invalid service canvas')
    require(type(canvas['frameRate']) is str, 'Invalid service frame rate type')
    rate = Fraction(canvas['frameRate'])
    require(rate > 0 and f'{rate.numerator}/{rate.denominator}' == canvas['frameRate'],
            'Invalid canonical service frame rate')
    require(digest(value['encoderContractSha256']), 'Invalid encoder contract digest')
    audio = fields(value['audio'], 'sampleRate channels sampleFormat')
    require(type(audio['sampleRate']) is int and type(audio['channels']) is int
            and audio == {'sampleRate': 48000, 'channels': 2, 'sampleFormat': 'pcm_f32le'},
            'Service audio must match the current stereo float master contract')
    filesystem = fields(value['filesystem'], 'type volumeIdentity')
    require(all(text(item) for item in filesystem.values()), 'Invalid filesystem identity')
    execution = fields(value['execution'], 'ownedConcurrency')
    require(type(execution['ownedConcurrency']) is int and execution['ownedConcurrency'] in (1, 2, 3),
            'Invalid observed concurrency')
    require(value['cacheRegime'] in ('unknown', 'observed-warm') and text(value['proofPlanVersion']),
            'Invalid cache/read-plan condition')


def validate_bounds(value: dict) -> None:
    """Require finite integer envelope dimensions with explicit minimum frame coverage."""
    fields(value, 'minFrames ' + ' '.join(BOUND_DIMENSIONS))
    require(all(type(item) is int and 0 <= item < 2 ** 63 for item in value.values()), 'Invalid service bounds')
    require(0 < value['minFrames'] <= value['maxFrames'] and value['maxWindows'] > 0, 'Invalid frame/window bounds')


def validate_dimensions(value: dict) -> None:
    """Validate actual measured workload facts, never replacing them with future estimates."""
    fields(value, ' '.join(BOUND_DIMENSIONS.values()))
    require(all(type(item) is int and 0 <= item < 2 ** 63 for item in value.values()), 'Invalid measured dimensions')
    require(value['frames'] > 0 and value['windows'] > 0, 'Empty measured media')


def within_bounds(value: dict, bounds: dict) -> bool:
    """Match all measured dimensions jointly, with no duration extrapolation."""
    return value['frames'] >= bounds['minFrames'] and all(value[key] <= bounds[name]
                                                       for name, key in BOUND_DIMENSIONS.items())
