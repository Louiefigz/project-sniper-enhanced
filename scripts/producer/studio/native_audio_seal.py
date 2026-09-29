"""Immutable seals for supervised audio stages, and identity-bound discovery.

A seal exists only after the audio owner completed cleanly and its premaster,
float master, receipts and executed implementation were bound. Readers re-hash
every sealed byte. A failed or unsealed stage is never reusable; a stage whose
executed code changed since sealing is stale, not an error, during discovery.
"""
from __future__ import annotations

import sys
from datetime import datetime, timezone
from itertools import islice
from pathlib import Path

from cut_preview_io import bound_json, file_hash, real_directory, write_new
from studio.native_audio_contract import audio_input_identity, implementation_current
from studio.native_stage_evidence import MAX_NATIVE_FILE_BYTES, STABLE_FIELDS, require

STATUS_PREPARED = 'native-audio-stage-prepared'
SEAL_STATUS = 'native-audio-stage-sealed'
MASTER_STATUS = 'float-master-checked-awaiting-aac'
SEAL_NAME, FAILED_NAME = 'audio-stage.json', 'audio-stage-failed.json'
REQUEST_NAME, RESULT_NAME = 'stage-request.json', 'audio-stage-result.json'
OWNER_NAME, WORKER_FAILURE = 'audio-stage.render.json', 'worker-failure.json'
MAX_ARTIFACTS, MAX_ENTRIES = 64, 256


class StaleAudioStage(ValueError):
    """A structurally valid seal whose executed implementation has since changed."""


def _binding(file: Path) -> dict:
    """Retain one exact regular file inside a stage."""
    return {'path': str(file), 'sha256': file_hash(file, MAX_NATIVE_FILE_BYTES)}


def _inventory(work: Path) -> dict[str, str]:
    """Hash every regular file produced by the worker; links or special files fail."""
    rows = {}
    for file in sorted(work.rglob('*')):
        require(not file.is_symlink() and (file.is_file() or file.is_dir()), f'unsafe audio stage entry: {file}')
        if file.is_file():
            rows[file.relative_to(work).as_posix()] = file_hash(file, MAX_NATIVE_FILE_BYTES)
    require(0 < len(rows) <= MAX_ARTIFACTS, 'audio stage artifact inventory is empty or unbounded')
    return rows


def require_owner_completion(owner: dict, request_file: Path) -> None:
    """Accept only a clean, launched, stable owner that pinned this exact request."""
    require(owner.get('status') == STATUS_PREPARED and type(owner.get('exitCode')) is int
            and owner['exitCode'] == 0 and not owner.get('abortReason')
            and not owner.get('receiptOwnershipFailed'), 'audio stage owner did not complete successfully')
    cleanup = owner.get('cleanup')
    require(isinstance(cleanup, dict) and cleanup.get('verified') is True and cleanup.get('survivors') == [],
            'audio stage owner cleanup is unverified')
    require(all(owner.get(key) is True for key in STABLE_FIELDS), 'audio stage owner inputs were not stable')
    before = owner.get('additionalFilePinsBefore')
    require(isinstance(before, dict) and before == owner.get('additionalFilePinsAfter')
            and before.get(str(request_file)) == file_hash(request_file), 'audio stage request was not supervised')


def require_master(stage: dict, receipt: dict) -> None:
    """Bind the float master receipt to this stage's premaster, clock and profile."""
    contract = stage['audioInput']
    require(receipt.get('status') == MASTER_STATUS and receipt.get('humanListeningApproved') is False
            and receipt.get('output') == stage['master']['path']
            and receipt.get('masterSha256') == stage['master']['sha256']
            and receipt.get('inputPremasterSha256') == stage['premaster']['sha256']
            and receipt.get('samples') == contract['clock']['totalSamples']
            and receipt.get('masteringProfile') == contract['masteringProfile']
            and receipt.get('masteringPolicyVersion') == contract['masteringPolicyVersion']
            and receipt.get('reviewSections') == contract['reviewSections'],
            'audio stage master receipt differs from its sealed contract')


def seal_stage(root: Path, lease_class: str) -> dict:
    """Publish the immutable record for a completed owner; never for a failed one."""
    real_directory(root)
    request_file, owner_file, result_file = root / REQUEST_NAME, root / OWNER_NAME, root / RESULT_NAME
    request, owner, result = bound_json(request_file), bound_json(owner_file), bound_json(result_file)
    require(not (root / FAILED_NAME).exists() and not (root / WORKER_FAILURE).exists(), 'failed audio stage')
    require_owner_completion(owner, request_file)
    require(result.get('status') == STATUS_PREPARED and result.get('audioInputSha256') == request['audioInputSha256']
            == audio_input_identity(request['audioInput']), 'audio stage result differs from its request')
    prepared, work = result['prepared'], root / 'work'
    record = {'schemaVersion': 1, 'scope': 'native-short-audio-stage', 'status': SEAL_STATUS,
              'audioInputSha256': request['audioInputSha256'], 'audioInput': request['audioInput'],
              'implementation': result['implementation'], 'stageRoot': str(root),
              'preparedFromProject': request['project'], 'leaseClass': lease_class,
              'request': _binding(request_file), 'owner': _binding(owner_file), 'result': _binding(result_file),
              'artifacts': _inventory(work), 'premaster': _binding(Path(prepared['reference'])),
              'masterReceipt': _binding(Path(prepared['masterReceipt'])),
              'master': _binding(Path(prepared['masterReceipt']).parent / 'program-master.wav'),
              'ownerElapsedSeconds': owner.get('elapsedSeconds'), 'ownerCleanup': owner['cleanup'],
              'humanListeningApproved': False, 'deliveryApproved': False,
              'sealedAt': datetime.now(timezone.utc).isoformat()}
    receipt = bound_json(Path(record['masterReceipt']['path']), record['masterReceipt']['sha256'])
    require(record['premaster']['sha256'] == prepared['referenceSha256']
            and record['masterReceipt']['sha256'] == prepared['masterReceiptSha256'], 'audio stage result changed')
    require_master(record, receipt)
    record.update(audioQuality=receipt['audioQuality'], audioReviewRequired=receipt['audioReviewRequired'])
    _require_inside(record, work)
    publish_seal(root, record)
    return read_sealed_stage(root / SEAL_NAME, record['audioInputSha256'])


def publish_seal(root: Path, record: dict) -> None:
    """Publish atomically so concurrent discovery never reads a partial seal."""
    seal, pending = root / SEAL_NAME, root / f'.{SEAL_NAME}.pending'
    require(not seal.exists() and not seal.is_symlink(), 'audio stage is already sealed')
    write_new(pending, record)
    pending.rename(seal)


def _require_inside(record: dict, work: Path) -> None:
    """Keep the pointed premaster/master files within the sealed inventory."""
    for key in ('premaster', 'masterReceipt', 'master'):
        file = Path(record[key]['path'])
        require(file.is_relative_to(work) and file.resolve(strict=True) == file
                and record['artifacts'].get(file.relative_to(work).as_posix()) == record[key]['sha256'],
                f'audio stage {key} is outside its sealed inventory')


def read_sealed_stage(seal: Path, identity: str | None = None) -> dict:
    """Re-hash one complete seal; raise StaleAudioStage when only its code is outdated."""
    require(seal.name == SEAL_NAME, 'expected an audio-stage.json seal')
    root = seal.parent
    real_directory(root)
    record = bound_json(seal)
    require(record.get('schemaVersion') == 1 and record.get('status') == SEAL_STATUS
            and record.get('stageRoot') == str(root) and not (root / FAILED_NAME).exists(),
            'audio stage seal is not a sealed success')
    require(record['audioInputSha256'] == audio_input_identity(record['audioInput'])
            and identity in (None, record['audioInputSha256']), 'audio stage identity differs')
    expected = {'request': root / REQUEST_NAME, 'owner': root / OWNER_NAME, 'result': root / RESULT_NAME}
    require(all(record[key]['path'] == str(file) for key, file in expected.items()), 'audio stage receipts moved')
    for key in ('request', 'owner', 'result', 'premaster', 'masterReceipt', 'master'):
        require(file_hash(Path(record[key]['path']), MAX_NATIVE_FILE_BYTES) == record[key]['sha256'],
                f'sealed audio stage {key} changed')
    require_owner_completion(bound_json(root / OWNER_NAME), root / REQUEST_NAME)
    require(_inventory(root / 'work') == record['artifacts'], 'sealed audio stage inventory changed')
    _require_inside(record, root / 'work')
    require_master(record, bound_json(Path(record['masterReceipt']['path'])))
    if not implementation_current(record['implementation']):
        raise StaleAudioStage('audio stage implementation changed since sealing')
    return record


def candidate_seals(search_root: Path, attempts: tuple[Path, ...] = ()) -> list[Path]:
    """List standalone and in-attempt seals among bounded siblings plus exact history attempts."""
    real_directory(search_root)
    entries = list(islice(search_root.iterdir(), MAX_ENTRIES + 1))
    require(len(entries) <= MAX_ENTRIES, 'audio stage search exceeds 256 entries; pass --audio-stage explicitly')
    seals = [entry / name for entry in sorted(entries) if entry.is_dir() and not entry.is_symlink()
             for name in (SEAL_NAME, f'audio-stage/{SEAL_NAME}')]
    seals += [attempt / 'audio-stage' / SEAL_NAME for attempt in attempts]
    return sorted({file for file in seals if file.is_file() and not file.is_symlink()})


def matching_stage(seal: Path, identity: str) -> dict | None:
    """Return a verified matching seal, or None for another identity or any failed verification.

    Discovery only offers reuse: a sibling whose evidence no longer verifies (stale code, a
    changed or cluttered inventory, an unreadable seal) is not a match, and the export prepares
    its own stage. An explicitly selected ``--audio-stage`` still fails closed (explicit_stage).
    Each skip is reported on stderr, so a reader defect stays visible instead of silently
    turning reuse off.
    """
    try:
        if bound_json(seal).get('audioInputSha256') != identity:
            return None
        return read_sealed_stage(seal, identity)
    except (StaleAudioStage, RuntimeError, ValueError, OSError, KeyError, TypeError) as error:
        print(f'audio stage discovery skipped {seal}: {type(error).__name__}: {error}', file=sys.stderr)
        return None


def discover_stage(search_root: Path, identity: str, attempts: tuple[Path, ...] = ()) -> tuple[Path, dict] | None:
    """Select the earliest verified seal with this audio-input identity, by content not path."""
    found = []
    for seal in candidate_seals(search_root, attempts):
        record = matching_stage(seal, identity)
        if record is not None:
            found.append((record['sealedAt'], str(seal), record))
    if not found:
        return None
    _sealed, path, record = min(found)
    return Path(path), record
