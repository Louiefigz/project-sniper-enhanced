"""Bind an allocated VISUAL-PLAN.json to a native Long project."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from cross_runtime_canonical_json import canonical_compact_json
from planner.visual_plan_contract import invalidation_inputs, validate_visual_plan
from planner.visual_plan_receipts import authority_pin
from studio.native_stage_evidence import require

MAX_PLAN_BYTES = 4 * 1024 * 1024
BINDING_FIELDS = {
    'schemaVersion', 'path', 'byteHash', 'visualPlanSha256',
    'pictureInputSha256', 'catalogPinSha256', 'upstreamAuthoritySha256',
}
RECEIPT_FIELD = 'catalogReceiptAuthority'


def _regular_bytes(file: Path, label: str) -> bytes:
    """Read one canonical bounded regular file without following a symlink."""
    require(file.is_absolute() and not file.is_symlink() and file.is_file()
            and file.resolve(strict=True) == file, f'{label} must be one canonical regular file')
    size = file.stat().st_size
    require(1 < size <= MAX_PLAN_BYTES, f'{label} exceeds the bounded read size')
    return file.read_bytes()


def _binding(value: object) -> dict:
    """Validate the exact cross-runtime visual-plan binding shape."""
    fields = set(value) if isinstance(value, dict) else set()
    valid_fields = (BINDING_FIELDS, BINDING_FIELDS | {RECEIPT_FIELD})
    require(isinstance(value, dict) and fields in valid_fields,
            'invalid native visual-plan binding fields')
    require(value.get('schemaVersion') == 1, 'unsupported native visual-plan binding')
    for field in BINDING_FIELDS - {'schemaVersion', 'path'}:
        item = value.get(field)
        require(isinstance(item, str) and len(item) == 64
                and all(char in '0123456789abcdef' for char in item),
                f'invalid native visual-plan {field}')
    require(isinstance(value.get('path'), str) and value['path'],
            'invalid native visual-plan path')
    if RECEIPT_FIELD in value:
        receipt = value[RECEIPT_FIELD]
        require(isinstance(receipt, dict) and isinstance(receipt.get('path'), str),
                'invalid native catalog receipt authority')
        require(authority_pin(receipt['path']) == receipt,
                'native catalog receipt authority differs from its bytes')
    return value

def bound_long_visual_plan(project: Path, plan: dict) -> tuple[dict | None, dict[str, str]]:
    """Return the validated allocated Long plan and its source/frozen byte pins."""
    raw_binding = plan.get('visualPlan')
    if raw_binding is None:
        return None, {}
    binding = _binding(raw_binding)
    source = Path(binding['path'])
    source_bytes = _regular_bytes(source, 'visual-plan source')
    require(hashlib.sha256(source_bytes).hexdigest() == binding['byteHash'],
            'visual-plan source changed')
    try:
        receipt = binding.get(RECEIPT_FIELD)
        visual_plan = validate_visual_plan(json.loads(source_bytes), receipt)
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError('native visual plan is invalid') from exc
    require(visual_plan['project']['mode'] == 'long'
            and visual_plan['allocation']['status'] == 'allocated'
            and visual_plan['allocation']['route'] == 'native-long',
            'VISUAL-PLAN.json must allocate the complete long project to native-long')
    fingerprints = invalidation_inputs(visual_plan, receipt)
    require(all(binding[field] == fingerprints[field] for field in fingerprints),
            'native visual-plan fingerprints differ from its content')
    frozen = project / 'VISUAL-PLAN.json'
    frozen_bytes = _regular_bytes(frozen, 'frozen VISUAL-PLAN.json')
    require(frozen_bytes == source_bytes, 'frozen VISUAL-PLAN.json differs from its authority')
    pins = {str(source): binding['byteHash'], str(frozen): binding['byteHash']}
    if receipt is not None:
        pins[receipt['path']] = receipt['sha256']
    return visual_plan, pins


def validate_long_visual_plan(project: Path, plan: dict) -> dict[str, str]:
    """Validate and pin an optional allocated Long visual plan and frozen copy."""
    _visual_plan, pins = bound_long_visual_plan(project, plan)
    return pins


def visual_plan_reuse_identity(plan: dict, audio_profile: str) -> dict:
    """Separate picture authority from compatible source/audio reuse authority."""
    binding = plan.get('visualPlan')
    if binding is None:
        return {}
    binding = _binding(binding)
    source_assets = [{key: row.get(key) for key in ('file', 'sha256', 'role')}
                     for row in plan.get('assets', [])
                     if isinstance(row, dict) and row.get('role') == 'source']
    audio = plan.get('audioFinishing', plan.get('audio'))
    authority = {'upstreamAuthoritySha256': binding['upstreamAuthoritySha256'],
                 'audioProfile': audio_profile, 'audio': audio,
                 'sourceAssets': source_assets}
    audio_hash = hashlib.sha256(canonical_compact_json(authority).encode()).hexdigest()
    return {'pictureInputSha256': binding['pictureInputSha256'],
            'upstreamAuthoritySha256': binding['upstreamAuthoritySha256'],
            'audioReuseSha256': audio_hash}


def same_audio_reuse_identity(current: dict, original: dict) -> bool:
    """Return true only for the same explicit visual-plan upstream/audio authority."""
    identity, previous = current.get('visualPlanReuse'), original.get('visualPlanReuse')
    fields = ('upstreamAuthoritySha256', 'audioReuseSha256')
    return (isinstance(identity, dict) and isinstance(previous, dict)
            and all(isinstance(identity.get(field), str)
                    and len(identity[field]) == 64
                    and identity[field] == previous.get(field) for field in fields))
