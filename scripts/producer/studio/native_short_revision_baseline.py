"""Read sealed frame ownership without transferring an old final approval.

The final delivery supplies QC authority. A promotion may retain its screenshots
in its immutable draft attempt; that draft's own seal proves capture ownership,
while equality to the checked final picture supplies the final-picture binding.
An unpromoted draft can never become a checked revision donor through this reader.
A completed sealed render whose final QC is unfinished may supply unchanged work,
explicitly marked unfinished; every current final check must still run.
"""
from __future__ import annotations

from pathlib import Path

from cut_preview_io import bound_json
from studio.native_runtime import digest
from studio.native_short_draft import read_draft_stage
from studio.native_short_picture_reuse import MAX_RECEIPT_BYTES, picture_dependencies, picture_reuse_pins, verify_picture
from studio.native_stage_evidence import read_stage, require, verify_pins, verify_supervised_inputs


def frame_root(checked: dict, attempt: Path) -> Path:
    """A promotion retains frames at its named sealed draft; direct exports own their own."""
    promotion = checked.get('promoteDraft')
    return Path(promotion['attempt']) if promotion else attempt


def baseline_pins(checked: dict, attempt: Path) -> tuple[Path, dict, dict]:
    """Admit exact picture/frame inventory under its original completed supervisor."""
    original = frame_root(checked, attempt)
    if original == attempt:
        pins = picture_reuse_pins(Path(checked['project']), attempt)
        return original, checked, pins
    draft = bound_json(original / 'export-request.json')
    promotion = checked['promoteDraft']
    require(draft.get('reviewDraft') is True and draft['project'] == checked['project']
            and draft['captureMode'] == checked['captureMode']
            and draft['runtime'] == checked['runtime'] and draft['tools'] == checked['tools'],
            'Promoted frame baseline differs from the checked final inputs')
    seal = original / 'draft-stage.json'
    require(promotion.get('draftStage') == str(seal)
            and promotion.get('draftStageSha256') == digest(seal), 'Promoted draft seal changed')
    record, pins = read_draft_stage(seal, draft['pins'])
    require(record['artifacts']['draft']['sha256'] == promotion.get('draftSha256')
            == digest(attempt / 'review.mp4'), 'Checked promotion changed the sealed draft bytes')
    require(record['artifacts']['picture']['sha256'] == digest(attempt / 'picture.mp4'),
            'Checked promotion changed the original captured picture')
    pins.update(picture_dependencies(Path(checked['project']), draft))
    receipt_file = original / 'batched-picture.json'
    receipt = bound_json(receipt_file, maximum=MAX_RECEIPT_BYTES)
    pins.update(verify_picture(Path(checked['project']), original, draft, receipt))
    pins[str(receipt_file)] = digest(receipt_file)
    verify_pins(pins)
    return original, draft, pins


def read_baseline(attempt: Path) -> tuple[dict, dict, str]:
    """Completed picture work may be unfinished QC; never inherit its final approval."""
    request = bound_json(attempt / 'export-request.json')
    delivery = bound_json(attempt / 'delivery.json')
    if delivery.get('status') == 'native-short-checked-for-review':
        from studio.native_review_contract import checked_delivery
        _delivery, checked, pins = checked_delivery(attempt)
        return checked, pins, 'checked-final'
    require(delivery.get('status') in {'failed', 'native-short-rendered-awaiting-qc'}
            and isinstance(delivery.get('completedAt'), str), 'Picture donor invocation is not terminal')
    seal = attempt / 'render-stage.json'
    record, pins = read_stage(seal, request['pins'], 'render')
    require(record['successStatus'] == 'native-short-rendered-awaiting-qc', 'Picture stage did not finish')
    from studio.native_short_resume import media_result
    media_result(record)
    pins.update(terminal_owner_pins(attempt, request))
    for name in ('delivery.json', 'export-request.json'):
        pins[str(attempt / name)] = digest(attempt / name)
    verify_pins(pins)
    return request, pins, 'rendered-awaiting-final-qc'


def terminal_owner_pins(attempt: Path, request: dict) -> dict:
    """No retained attempt donates while a capture/render/verification owner remains unresolved."""
    owners = sorted(attempt.glob('*.render.json'))
    require(0 < len(owners) <= 32, 'Picture donor owner inventory is missing or unbounded')
    pins = {}
    for file in owners:
        owner = bound_json(file)
        require(type(owner.get('exitCode')) is int and owner.get('completedAt')
                and owner.get('status') not in {'running', 'preparing'}, 'Picture donor owner has not ended')
        verify_supervised_inputs(Path(request['project']), attempt / 'export-request.json', request, owner)
        pins[str(file)] = digest(file)
    return pins
