"""Source-derived native dialogue and encoded-picture checks, under one owner."""
from __future__ import annotations

import json
import subprocess
from dataclasses import replace
from pathlib import Path

import numpy as np

from audio.audio_mix_picture import observe_picture_source, packet_signature
from audio.native_dialogue_delivery import NativeDialogueDelivery, finish_native_dialogue
from audio.dialogue_cleanup import DialogueSource
from audio.native_audio_finishing import finish_native_audio
from audio.native_master_preparation import NativeMasterPreparation, prepare_native_master
from audio.native_audio_donor import prepare_audio_donor
from audio.mastering_profile import NATIVE_SHORT_MASTERING_PROFILE, resolve_mastering_profile
from audio.program_audio_clock import exact_aac_audio_clock
from studio.native_runtime import digest
from studio.native_short_dialogue import clock, dialogue_reference, normalize_dialogue_reference, run
from studio.native_stage_evidence import MAX_NATIVE_FILE_BYTES, read_native_capture_receipt
from cut_preview_io import MAX_JSON, file_hash, file_identity, write_new
from native_render_resources import ResourcePolicy
from native_render_storage import require_disk_allocation
from studio.native_selected_frames import compare_selected_frames, selected_frames
from studio.native_picture_references import (assert_picture_inputs, picture_metrics,
                                              qualify_reverse_frames, reference_identities)


def dialogue_premaster(request: dict, canvas: dict, audio_finishing: object) -> Path:
    """Prepare the exact intended float audio independently of picture generation."""
    root, project = Path(request['output']), Path(request['project'])
    raw_reference = dialogue_reference(project, canvas, root)
    samples = clock(canvas).sample_at_frame(canvas['totalFrames'])
    reference = normalize_dialogue_reference(raw_reference, samples, root)
    source = DialogueSource(str(reference), samples, request['tools']['ffmpeg'], request['tools']['ffprobe'])
    return finish_native_audio(source, audio_finishing, root / 'dialogue-cleanup')


def prepare_dialogue(request: dict, canvas: dict, audio_finishing: object = None) -> dict:
    """Check mastered dialogue before expensive picture; retain final AAC/mux gates."""
    profile = resolve_mastering_profile(request.get('audioProfile', NATIVE_SHORT_MASTERING_PROFILE.identity))
    reference = dialogue_premaster(request, canvas, audio_finishing)
    samples = clock(canvas).sample_at_frame(canvas['totalFrames'])
    master = NativeMasterPreparation(reference, digest(reference), samples,
        Path(request['output']) / 'audio-preparation', profile, dialogue_review_sections(canvas))
    if request.get('preparedMaster'):
        receipt = request['preparedMaster']
        master = replace(master, prepared_master=(Path(receipt), request['pins'][receipt]))
    tools = (request['tools']['ffmpeg'], request['tools']['ffprobe'])
    donor = request.get('audioDonor')
    receipt, sha = prepare_audio_donor(master, Path(donor), tools) if donor else prepare_native_master(master, tools)
    return {'kind': 'donor' if donor else 'master', 'reference': str(reference), 'referenceSha256': master.premaster_sha256,
            'masterReceipt': str(receipt), 'masterReceiptSha256': sha, 'audioFinishing': audio_finishing}


def finish_dialogue(request: dict, canvas: dict, audio_finishing: object = None,
                    prepared: dict | None = None) -> dict:
    """Share float mastering and AAC reuse; never repeat an admitted prepared master."""
    root = Path(request['output'])
    profile = resolve_mastering_profile(request.get('audioProfile', NATIVE_SHORT_MASTERING_PROFILE.identity))
    samples = clock(canvas).sample_at_frame(canvas['totalFrames'])
    binding, donor_binding = None, None
    if prepared and prepared.get('kind') == 'donor' and not request.get('audioDonor'):
        raise RuntimeError('Prepared audio donor requires its original prior receipt')
    if prepared is None:
        reference = dialogue_premaster(request, canvas, audio_finishing)
    else:
        reference = Path(prepared['reference'])
        admitted_long = request.get('adapter') == 'native-long' and request['pins'].get(str(reference)) == prepared['referenceSha256']
        if prepared.get('audioFinishing') != audio_finishing or (not reference.is_relative_to(root) and not admitted_long) \
                or digest(reference) != prepared['referenceSha256']:
            raise RuntimeError('Prepared native dialogue changed before final assembly')
        binding = (Path(prepared['masterReceipt']), prepared['masterReceiptSha256'])
        if prepared.get('kind') == 'donor':
            donor_binding, binding = binding, None
    picture = root / 'picture.mp4'
    donor = Path(request['audioDonor']) if request.get('audioDonor') else None
    return finish_native_dialogue(NativeDialogueDelivery(picture, reference,
        samples, root / 'audio',
        digest(picture), digest(reference), donor,
        profile=profile, review_sections=dialogue_review_sections(canvas),
        prepared_master=binding, prepared_donor=donor_binding))


def dialogue_review_sections(canvas: dict) -> tuple[dict, ...]:
    """Use the executed frame-to-sample cut clock for dialogue level comparisons."""
    timeline = clock(canvas)
    return tuple({'start': timeline.sample_at_frame(row['startFrame']) / 48000,
                  'end': timeline.sample_at_frame(row['endFrameExclusive']) / 48000,
                  'label': f'dialogue cut {index + 1}'}
                 for index, row in enumerate(canvas['segments']))


def picture_payload(file: Path) -> str:
    """Hash H.264 picture slices independently of color metadata NAL units."""
    return run(['ffmpeg', '-nostdin', '-v', 'error', '-i', str(file), '-map', '0:v:0', '-an',
        '-c:v', 'copy', '-bsf:v', 'h264_mp4toannexb,filter_units=pass_types=1-5',
        '-f', 'hash', '-hash', 'sha256', '-']).strip()


def native_srgb_delivery(root: Path, audio: dict) -> dict:
    """Correct the measured native Chrome route only, preserving picture and AAC."""
    source, output = root / 'audio/candidate.mp4', root / 'review.mp4'
    if audio['status'] != 'audio-qualified' or digest(source) != audio['candidateSha256']:
        raise RuntimeError('Native audio candidate changed or did not qualify')
    samples = audio['audioClock']['presentedSamples']
    before = observe_picture_source(str(source), samples / 48000)
    stream = json.loads(run(['ffprobe', '-v', 'error', '-select_streams', 'v:0',
                            '-show_streams', '-of', 'json', str(source)]))['streams']
    if len(stream) != 1 or stream[0]['codec_name'] != 'h264' or stream[0].get('color_transfer') != 'bt709':
        raise RuntimeError('Unexpected native color route; no inferred correction')
    slices = picture_payload(source)
    run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-n', '-i', str(source),
        '-map', '0:v:0', '-map', '0:a:0', '-c', 'copy', '-bsf:v',
        'h264_metadata=colour_primaries=1:transfer_characteristics=13:matrix_coefficients=1:video_full_range_flag=0',
        '-color_primaries', 'bt709', '-color_trc', 'iec61966-2-1', '-colorspace', 'bt709', '-color_range', 'tv',
        '-video_track_timescale', str(before.time_base.denominator), '-movie_timescale', '48000',
        '-movflags', '+faststart', str(output)])
    after = observe_picture_source(str(output), samples / 48000)
    if picture_payload(output) != slices or [row[0] for row in before.packets] != [row[0] for row in after.packets] \
            or packet_signature(str(source), 'a:0') != packet_signature(str(output), 'a:0'):
        raise RuntimeError('Native metadata correction changed picture or AAC payload/timing')
    return {'output': str(output), 'sha256': digest(output), 'pictureSliceSha256': slices,
            'aacPacketsIdentical': True, 'additionalPictureEncodes': 0, 'additionalAudioEncodes': 0,
            'audioClock': exact_aac_audio_clock(str(output), 'ffprobe', samples)}


def full_decode(candidate: Path, timeout: float = 180) -> None:
    """Retain the independent complete audio/video decode, beyond selected frames."""
    run(['ffmpeg', '-nostdin', '-v', 'error', '-xerror', '-i', str(candidate),
         '-map', '0:v:0', '-map', '0:a:0', '-f', 'null', '-'], timeout=timeout)


def qualify_picture(root: Path, canvas: dict, policy: ResourcePolicy = ResourcePolicy()) -> dict:
    """Stream every required comparison with no RGB scratch and a full A/V decode."""
    candidate = root / 'review.mp4'
    receipt = root / 'native-frames.json'
    receipt_hash = file_hash(receipt)
    native = read_native_capture_receipt(receipt, receipt_hash)
    if native['status'] != 'native-references-and-seek-states-pass':
        raise RuntimeError('Native capture/typography/seek checks failed')
    if 'expectedCapturePoints' in native and native['expectedCapturePoints'] != [r['frame'] for r in native['frames']]:
        raise RuntimeError('Native capture schedule differs from its required inventory')
    before = file_hash(candidate, maximum=MAX_NATIVE_FILE_BYTES)
    identities = reference_identities(native)
    identities.update({path: file_identity(path.lstat()) for path in (candidate, receipt)})
    rows = [row for row in native['frames'] if not row['repeat']]
    selection = selected_frames(canvas, rows)
    reverse = qualify_reverse_frames(native, selection.shape)
    receipt_budget = MAX_JSON + 512 * len(native["frames"])
    storage = require_disk_allocation(root, receipt_budget + len(selection.filter_bytes), policy)
    directory = root / 'picture-qc'
    directory.mkdir()
    duration = canvas['totalFrames'] / float(clock(canvas).fps.fraction)
    observed = observe_picture_source(str(candidate), duration)
    if len(observed.packets) != canvas['totalFrames']:
        raise RuntimeError('Encoded picture frame count differs from the strategy clock')
    indexed = {row['frame']: row for row in rows}
    def compare(frame: int, pixels: np.ndarray) -> dict:
        """Compare each exact selected frame with its admitted native reference."""
        row = indexed[frame]
        return {'frame': frame, **picture_metrics(Path(row['path']), pixels, selection.shape, row['sha256'])}
    comparisons, decoded = compare_selected_frames(candidate, selection, compare, directory)
    full_decode(candidate, timeout=max(180, duration * 2))
    assert_picture_inputs(identities, (candidate, before), (receipt, receipt_hash))
    result = {'passed': all(row['passed'] for row in comparisons), 'candidateSha256': before,
              'videoPackets': len(observed.packets), 'fullAudioVideoDecodePassed': True,
              'comparisons': comparisons, 'humanListeningApproved': False,
              'reverseSeekComparisons': reverse,
              'reverseSeekTolerance': {'maeMaximum': .01, 'psnrMinimumDb': 60,
                  'exactSceneStateAndSourceFramesRequired': True},
              'batchDecode': decoded, 'storageAdmission': storage,
              'storageBeforeReceipt': require_disk_allocation(directory, receipt_budget, policy)}
    if len(json.dumps(result, allow_nan=False).encode('utf-8')) + 1 > receipt_budget:
        raise RuntimeError('Native picture result exceeds its admitted receipt allocation')
    write_new(directory / 'result.json', result)
    if not result['passed']:
        raise RuntimeError('Native encoded picture comparison failed; see picture-qc/result.json')
    return result
