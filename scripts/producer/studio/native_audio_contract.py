"""Frozen audio-input contract for one native Short's whole-program dialogue master.

The contract names what determines the finished premaster and float master:
admitted dialogue bytes and source mappings, cuts and output segments, the exact
frame/sample clock and end hold, channel/cleanup/gain choices, the mastering
profile, tool identities and the core audio implementation. Picture, graphics,
fonts, copy and project paths are excluded, so a graphic-only revision keeps the
same identity. The stage worker additionally records every repository module it
actually executed; reuse re-verifies that closure (see ``implementation_current``).
"""
from __future__ import annotations

import importlib.metadata
import sys
from pathlib import Path

from audio.dialogue_cleanup import cleanup_model_binding
from audio.mastering_profile import resolve_mastering_profile
from audio.native_audio_finishing import native_finishing_request
from cut_preview_io import bound_json, digest, file_hash
from producer_config import MASTERING_POLICY_VERSION
from studio.native_runtime import REPO
from studio.native_selected_sources import dialogue_inputs
from studio.native_short_delivery import dialogue_review_sections
from studio.native_short_dialogue import clock
from studio.native_stage_evidence import MAX_NATIVE_FILE_BYTES, require

CONTRACT = 'native-short-audio-input-v1'
SAMPLE_RATE = 48000
PRODUCER = REPO / 'scripts/producer'
# Directly responsible audio code; any change yields a new identity. The worker's
# recorded executed closure (a superset) is re-verified before any reuse.
CORE_IMPLEMENTATION = (
    'studio/native_audio_contract.py', 'studio/native_audio_stage.py', 'studio/native_audio_seal.py',
    'studio/native_audio_import.py', 'studio/native_short_dialogue.py', 'studio/native_short_delivery.py',
    'studio/native_selected_sources.py', 'audio/native_audio_finishing.py', 'audio/dialogue_cleanup.py',
    'audio/native_master_preparation.py', 'audio/native_dialogue_delivery.py', 'audio/float_master.py',
    'audio/mastering_filter.py', 'audio/mastering_profile.py', 'audio/channel_normalization.py',
    'audio/channel_normalization_media.py', 'audio/channel_normalization_receipt.py',
    'audio/program_audio_clock.py', 'audio/program_finish_contract.py', 'audio/audio_gain.py',
    'audio/audio_mix_delivery.py', 'audit/audio_quality.py', 'audit/dialogue_consistency.py',
    'edit/exact_timing.py', 'producer_config.py')
MAPPING_KEYS = ('id', 'sourceFile', 'sourceOrigin', 'mediaStart', 'start', 'end', 'preparedFile')


def dialogue_sources(project: Path, canvas: dict) -> tuple[list[dict], list[list]]:
    """Identify each admitted dialogue input by content, with its exact cut offset.

    Args:
        project: Canonical native Short project.
        canvas: The project's admitted canvas.

    Returns:
        Ordered input identities and the ``[inputIndex, startSeconds]`` offsets that
        the shared dialogue reader passes to FFmpeg.
    """
    inputs, offsets = dialogue_inputs(project, canvas)
    require(len(inputs) % 2 == 0 and all(flag == '-i' for flag in inputs[::2]),
            'dialogue reader returned an unexpected input list')
    sources = []
    for name in inputs[1::2]:
        file = Path(name)
        sources.append({'sha256': file_hash(file, MAX_NATIVE_FILE_BYTES), 'bytes': file.stat().st_size})
    return sources, [[index, start] for index, start in offsets]


def prepared_mappings(project: Path, plan: dict) -> list[dict] | None:
    """Return the admitted dialogue mapping rows, excluding package paths."""
    if not plan.get('preparedSources'):
        return None
    report = bound_json(project / 'PREPARED-SOURCES.json')
    rows = [row for row in report['mappings'] if row['kind'] == 'audio']
    return sorted(({key: row[key] for key in MAPPING_KEYS} for row in rows), key=lambda row: row['id'])


def clock_contract(canvas: dict) -> dict:
    """Bind the exact frame-to-sample clock, cut timing and authored end hold."""
    timeline = clock(canvas)
    segments = [[row['startFrame'], row['endFrameExclusive']] for row in canvas['segments']]
    require(bool(segments) and segments[-1][1] <= canvas['totalFrames'], 'audio segments exceed the canvas')
    return {'frameRate': canvas['frameRate'], 'totalFrames': canvas['totalFrames'], 'sampleRate': SAMPLE_RATE,
            'totalSamples': timeline.sample_at_frame(canvas['totalFrames']), 'segments': segments,
            'endHoldFrames': canvas['totalFrames'] - segments[-1][1],
            'cuts': [{key: row[key] for key in ('start', 'end', 'speed')} for row in canvas['cuts']]}


def finishing_contract(plan: dict, samples: int) -> dict:
    """Validate authored channel/cleanup/gain choices and bind any cleanup model bytes."""
    value = plan.get('audioFinishing')
    request = native_finishing_request(value, samples)
    model = cleanup_model_binding(request.enhance_chain) if request else None
    return {'audioFinishing': value, 'cleanupModelSha256': model['sha256'] if model else None}


def tool_identities(tools: dict[str, str]) -> dict:
    """Bind FFmpeg, ffprobe, the interpreter and its numeric analysis libraries."""
    python = Path(sys.executable).resolve()
    return {'ffmpeg': file_hash(Path(tools['ffmpeg']).resolve(), MAX_NATIVE_FILE_BYTES),
            'ffprobe': file_hash(Path(tools['ffprobe']).resolve(), MAX_NATIVE_FILE_BYTES),
            'python': file_hash(python, MAX_NATIVE_FILE_BYTES),
            'numpy': importlib.metadata.version('numpy'), 'scipy': importlib.metadata.version('scipy')}


def core_implementation() -> dict[str, str]:
    """Hash the directly responsible audio modules by repository-relative path."""
    return {name: file_hash(PRODUCER / name) for name in CORE_IMPLEMENTATION}


def audio_input_contract(project: Path, profile_identity: str, tools: dict[str, str]) -> dict:
    """Freeze every audio dependency of one project, independently of its graphics.

    Args:
        project: Canonical native Short project directory.
        profile_identity: Explicit mastering profile identity.
        tools: Resolved local tool paths (``ffmpeg`` and ``ffprobe`` are required).

    Returns:
        A canonical JSON-compatible contract; ``audio_input_identity`` hashes it.
    """
    plan = bound_json(project / 'SHORT-PROJECT.json')
    canvas = plan['canvas']
    timing = clock_contract(canvas)
    sources, offsets = dialogue_sources(project, canvas)
    profile = resolve_mastering_profile(profile_identity)
    return {'schemaVersion': 1, 'contract': CONTRACT, 'sourceFile': canvas['sourceFile'],
            'sources': sources, 'offsets': offsets, 'mappings': prepared_mappings(project, plan),
            'clock': timing, **finishing_contract(plan, timing['totalSamples']),
            'masteringProfile': profile.receipt(), 'masteringPolicyVersion': MASTERING_POLICY_VERSION,
            'reviewSections': list(dialogue_review_sections(canvas)), 'tools': tool_identities(tools),
            'coreImplementation': core_implementation()}


def audio_input_identity(contract: dict) -> str:
    """Hash the canonical contract; equal identities describe the same audio work."""
    require(contract.get('contract') == CONTRACT and contract.get('schemaVersion') == 1,
            'unsupported native audio-input contract')
    return digest(contract)


def executed_implementation(modules: dict | None = None) -> dict[str, str]:
    """Record every repository Python module loaded by this process, by relative path."""
    rows = {}
    for module in list((modules if modules is not None else sys.modules).values()):
        name = getattr(module, '__file__', None)
        if not name:
            continue
        file = Path(name).resolve()
        if file.is_relative_to(REPO / 'scripts') and file.suffix == '.py':
            rows[file.relative_to(REPO).as_posix()] = file_hash(file)
    return dict(sorted(rows.items()))


def implementation_current(recorded: dict[str, str]) -> bool:
    """Return true only when every recorded executed module is unchanged in this checkout."""
    require(isinstance(recorded, dict) and bool(recorded), 'audio stage lacks its executed implementation')
    for relative, expected in recorded.items():
        file = REPO / relative
        require(isinstance(relative, str) and file.resolve() == file and file.is_relative_to(REPO / 'scripts'),
                'audio stage implementation path escaped the repository')
        if not file.is_file() or file_hash(file) != expected:
            return False
    return True
