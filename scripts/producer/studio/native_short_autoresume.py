"""Automatically discover Short work; existing media and donor readers retain authority."""
from __future__ import annotations

import sys
from pathlib import Path

from cut_preview_io import bound_json
from studio.native_export_history import candidate_attempts
from studio.native_runtime import digest
from studio.native_short_picture_reuse import picture_reuse_pins
from studio.native_short_resume import prepared_audio_reuse, prepare_reverification, render_stage_for_attempt
from studio.native_stage_evidence import require, verify_pins, verify_supervised_inputs
from studio.native_visual_plan import same_audio_reuse_identity

TERMINAL = {'failed', 'native-short-rendered-awaiting-qc', 'native-short-checked-for-review'}
POLICY = ('runtime', 'tools', 'cache', 'captureMode', 'sourceCacheMode', 'audioProfile', 'referenceMap')
AUDIO_READY = {'float-master-checked-awaiting-aac', 'audio-donor-checked-awaiting-picture'}
STUDIO = Path(__file__).resolve().parent


def retained_picture(original: dict, attempt: Path) -> Path | None:
    """Identify claimed completed picture; admission still uses the qualified donor reader."""
    if original.get('pictureDonor'):
        return Path(original['pictureDonor'])
    if original.get('captureMode') == 'cached-native-batches':
        return attempt if (attempt / 'batched-picture.json').exists() else None
    audio = attempt / 'audio/receipt.json'
    if audio.exists():
        row = bound_json(audio)
        if row.get('status') in {'failed', 'audio-qualified'} and row.get('picture'):
            return attempt
    return None


def retained_audio(attempt: Path) -> bool:
    """Failed or unfinished audio never becomes a reusable master by its file's presence."""
    final, prepared = attempt / 'audio/receipt.json', attempt / 'audio-preparation/receipt.json'
    return ((final.exists() and bound_json(final).get('status') == 'audio-qualified')
            or (prepared.exists() and bound_json(prepared).get('status') in AUDIO_READY))


def matching_attempt(current: dict, attempt: Path) -> tuple[int, str] | None:
    """Match exact current input/policy before admitting only terminal invocations."""
    file = attempt / 'export-request.json'
    if not file.is_file():
        return None
    original = bound_json(file)
    if original.get('adapter', 'native-short') != 'native-short' or original.get('project') != current['project']:
        return None
    if original.get('reviewDraft'):
        return None  # Review drafts are never final-media donors; only --promote-draft reuses their bytes.
    require(original.get('output') == str(attempt), 'Short recovery attempt moved; preserve its original location')
    inputs = original.get('renderInputs', original['pins'])
    if not matching_implementation(current, inputs):
        return None
    exact_inputs = not any(inputs.get(file) != sha for file, sha in current['pins'].items())
    if not exact_inputs and not same_audio_reuse_identity(current, original):
        return None
    if any(original.get(key) != current.get(key) for key in POLICY):
        return None
    if original.get('previewOnly') or original.get('promoteDraft'):
        return None  # Preview-only work (even while it runs) has no final-media owner: capture and section
        # seals are adopted by their own discovery; a promotion copies a draft's bytes and has no render.
    delivery_file = attempt / 'delivery.json'
    require(delivery_file.is_file(), 'Compatible Short attempt is active or interrupted; reconcile its owner first')
    delivery = bound_json(delivery_file)
    require(delivery.get('status') in TERMINAL and isinstance(delivery.get('completedAt'), str)
            and bool(delivery['completedAt'].strip()), 'Compatible Short attempt has no terminal delivery state')
    if exact_inputs and ((attempt / 'render-stage.json').exists() or original.get('verifyStage')):
        captured = (attempt / 'capture-stage.json').exists() or original.get('captureStage')
        return (4 if captured else 3), delivery['completedAt']
    if exact_inputs and retained_picture(original, attempt):
        return 2, delivery['completedAt']
    return (1, delivery['completedAt']) if retained_audio(attempt) and render_child_started(attempt) else None


def render_child_started(attempt: Path) -> bool:
    """A stopped preflight has no renderer-owned partial work to recover.

    The render owner writes its receipt before launching anything, so a missing receipt means
    the render phase never began (for example, a final that failed in its preview phase),
    unless the delivery records a render stage: then the missing proof fails in the reader.
    """
    file = attempt / 'pipeline.render.json'
    if not file.is_file():
        stages = bound_json(attempt / 'delivery.json').get('stages') or []
        return any(isinstance(row, dict) and row.get('phase') == 'pipeline' for row in stages)
    owner = bound_json(file)
    never_launched = (owner.get('status') == 'failed' and owner.get('pid') is None
                     and owner.get('exitCode') is None
                     and owner.get('cleanup') == {'childNeverLaunched': True, 'verified': True})
    return not never_launched


def matching_implementation(current: dict, previous: dict[str, str]) -> bool:
    """Audio identity cannot authorize reuse across changed executable dependencies."""
    roots = (STUDIO.parent, STUDIO.parents[2] / 'src', Path(current['runtime']))
    tools = {*current['tools'].values(), str(Path(sys.executable).resolve())}
    present = current['pins']
    for filename in previous.keys() | present.keys():
        executable = filename in tools or any(Path(filename).is_relative_to(root) for root in roots)
        if executable and previous.get(filename) != present.get(filename):
            return False
    return True


def partial_owner_pins(original: dict, attempt: Path) -> dict[str, str]:
    """Require the stopped shared worker and immutable inputs before reusing partial work."""
    file, owner_file = attempt / 'export-request.json', attempt / 'pipeline.render.json'
    owner = bound_json(owner_file)
    verify_supervised_inputs(Path(original['project']), file, original, owner)
    require(owner.get('status') == 'failed' and type(owner.get('exitCode')) is int
            and not owner.get('receiptOwnershipFailed'), 'Partial Short owner did not finish cleanly')
    command = ['/usr/bin/sandbox-exec', '-f', str(STUDIO / 'native_localhost_only.sb'),
               sys.executable, str(STUDIO / 'native_short_worker.py'), str(file), 'render']
    require(owner.get('args') == command and owner.get('output') == str(attempt / 'review.mp4'),
            'Partial Short owner did not invoke the shared render worker')
    identities, pid = owner.get('ownerIdentities'), owner.get('pid')
    require(type(pid) is int and pid > 0 and isinstance(identities, list) and bool(identities),
            'Partial Short owner identity is missing')
    require(all(isinstance(row, dict) and all(type(row.get(key)) is int and row[key] > 0
                for key in ('pid', 'pgid', 'parent_pid')) and isinstance(row.get('started'), str)
                and bool(row['started'].strip()) for row in identities), 'Partial Short owner identity is incomplete')
    require(len({row['pid'] for row in identities}) == len(identities)
            and any(row['pid'] == row['pgid'] == pid for row in identities), 'Partial Short root owner is missing')
    pins = {**original['pins'], str(file): digest(file), str(owner_file): digest(owner_file)}
    verify_pins(pins)
    return pins


def audio_reuse(original: dict, attempt: Path) -> tuple[dict, dict]:
    """Prefer already qualified AAC, otherwise retain the checked float preparation."""
    receipt = attempt / 'audio/receipt.json'
    if receipt.exists() and bound_json(receipt).get('status') == 'audio-qualified':
        record = bound_json(receipt)
        master, candidate = receipt.parent / 'program-master.wav', receipt.parent / 'candidate.mp4'
        require(digest(master) == record.get('masterSha256')
                and digest(candidate) == record.get('candidateSha256'), 'Short audio donor bytes changed')
        return {'preparedMaster': None, 'audioDonor': str(receipt)}, {
            str(file): digest(file) for file in (receipt, master, candidate)}
    if retained_audio(attempt):
        return prepared_audio_reuse(original, attempt)
    return {}, {}


def recover_partial(current: dict, attempt: Path) -> dict:
    """Copy no bytes here; bind independent proofs for the ordinary owned worker to consume."""
    output = Path(current['output'])
    require(output != attempt and not output.is_relative_to(attempt)
            and not attempt.is_relative_to(output), 'Short recovery output must preserve the donor')
    original = bound_json(attempt / 'export-request.json')
    pins = partial_owner_pins(original, attempt)
    fields, audio_pins = audio_reuse(original, attempt)
    donor = retained_picture(original, attempt)
    if donor:
        pins.update(picture_reuse_pins(Path(current['project']), donor))
        fields['pictureDonor'] = str(donor)
    return {**current, **fields, 'pins': {**pins, **current['pins'], **audio_pins}}


def recover_automatically(current: dict) -> dict:
    """Select the most complete compatible work without suppressing invalid selected proof."""
    candidates = []
    for attempt in candidate_attempts(current):
        rank = matching_attempt(current, attempt)
        if rank:
            candidates.append((*rank, str(attempt)))
    if not candidates:
        return {**current, 'recoverySelection': {'mode': 'fresh', 'searchRoot': str(Path(current['output']).parent)}}
    rank, _completed, filename = max(candidates)
    attempt = Path(filename)
    result = (prepare_reverification(current, render_stage_for_attempt(attempt), attempt)
              if rank >= 3 else recover_partial(current, attempt))
    reused = 'completed-media' if rank >= 3 else 'audio'
    if rank == 2:
        reused = 'picture-and-audio' if result.get('audioDonor') or result.get('preparedMaster') else 'picture'
    return {**result, 'recoverySelection': {'mode': 'automatic', 'attempt': filename, 'reused': reused}}
