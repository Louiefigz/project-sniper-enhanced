"""Strict landscape export contract on the existing native frame/sample clock."""
from __future__ import annotations

from fractions import Fraction
from math import ceil
from pathlib import Path
import re

from cut_preview_io import MAX_JSON, bound_json, file_hash
from studio.long_sources_html import inspect_html, local_asset, number
from studio.native_short_dialogue import clock
from studio.native_stage_evidence import require
from studio.native_style_application import validate_long_style_application
from studio.native_visual_plan_application import validate_long_visual_plan_application
from studio.native_workload import workload_budget

POLICY_FILE = 'NATIVE-LONG-POLICY.json'
POLICY = 'required-for-new-native-long'


def _legacy_authority(project: Path, authority: dict | None) -> None:
    """Verify controller-held provenance; editable project files cannot mint it."""
    plan = project / 'LONG-PROJECT.json'
    html = project / 'index.html'
    require(isinstance(authority, dict)
            and set(authority) == {'schemaVersion', 'scope', 'project',
                                   'planSha256', 'htmlSha256'}
            and authority['schemaVersion'] == 1
            and authority['scope'] == 'legacy-native-long-cold-read'
            and authority['project'] == str(project.resolve(strict=True))
            and authority['planSha256'] == file_hash(plan, MAX_JSON)
            and authority['htmlSha256'] == file_hash(html, MAX_JSON),
            'historical markerless native Long requires external controller-owned cold-read authority')


def _prepared_policy(project: Path, legacy_authority: dict | None = None) -> dict | None:
    """Read current policy or require an exact external historical authority."""
    marker = project / POLICY_FILE
    if not marker.exists():
        _legacy_authority(project, legacy_authority)
        return None
    row = bound_json(marker)
    require(set(row) == {'schemaVersion', 'requirement', 'requestPacket'}
            and row['schemaVersion'] == 1 and row['requirement'] == POLICY,
            'invalid native Long visual-plan policy marker')
    packet = row['requestPacket']
    require(isinstance(packet, dict) and set(packet) == {'path', 'sha256'},
            'invalid native Long request policy binding')
    request = Path(packet['path'])
    require(request.is_absolute() and not request.is_symlink()
            and request.resolve(strict=True) == request
            and file_hash(request, MAX_JSON) == packet['sha256'],
            'native Long policy request changed')
    return row


def require_current_long_policy(project: Path) -> dict:
    """Review/materialization paths have no markerless historical fallback."""
    policy = _prepared_policy(project)
    require(policy is not None, 'new native Long requires its controller policy marker')
    return policy


def _request_packet(plan: dict, policy: dict | None) -> None:
    """Bind every current Long project to the exact prepared request bytes."""
    packet = plan.get('requestPacket')
    require(isinstance(packet, dict) and set(packet) == {'path', 'sha256'},
            'new native Long schema requires an exact request packet')
    request = Path(packet['path'])
    require(request.is_absolute() and not request.is_symlink()
            and request.resolve(strict=True) == request
            and file_hash(request, MAX_JSON) == packet['sha256'],
            'native Long request packet changed')
    require(policy is None or packet == policy['requestPacket'],
            'native Long project differs from its prepared request')


def _program_audio_inputs(plan: dict) -> tuple[Path, Path, Path]:
    """Resolve only the exact producer/manifest named by the held Long request."""
    packet_path = Path(plan['requestPacket']['path'])
    packet = bound_json(packet_path)
    producer_value = packet.get('producerDir')
    manifest_ref = packet.get('manifest')
    require(isinstance(producer_value, str) and isinstance(manifest_ref, dict)
            and set(manifest_ref) == {'path', 'sha256', 'sizeBytes'},
            'native Long request lacks exact program-audio inputs')
    producer, manifest = Path(producer_value), Path(manifest_ref['path'])
    edit_plan = producer / 'edit_plan.json'
    require(producer.is_absolute() and producer.resolve(strict=True) == producer
            and not producer.is_symlink() and edit_plan.is_file() and not edit_plan.is_symlink(),
            'native Long producer audio input is not canonical')
    require(manifest.is_absolute() and manifest.is_file() and not manifest.is_symlink()
            and manifest.resolve(strict=True) == manifest
            and file_hash(manifest, MAX_JSON) == manifest_ref['sha256']
            and manifest.stat().st_size == manifest_ref['sizeBytes'],
            'native Long manifest audio input changed')
    return packet_path, producer, manifest


def validate_current_long_program_audio(project: Path, plan: dict) -> dict[str, str]:
    """Require the controller-owned complete-program WAV for current Long work."""
    require(plan.get('audio') == {'file': 'assets/program.wav'},
            'schema-2 native Long requires audio.file assets/program.wav')
    packet, producer, manifest = _program_audio_inputs(plan)
    from native_program_audio import read_native_program_audio_installation
    value = read_native_program_audio_installation(project, producer, manifest)
    authority, audio = value['authority'], value['audio']
    return {str(project / 'PROGRAM-AUDIO.json'): file_hash(project / 'PROGRAM-AUDIO.json', MAX_JSON),
            str(project / 'assets/program.wav'): audio['sha256'],
            authority['path']: authority['sha256'], authority['owner']: authority['ownerSha256'],
            str(producer / 'edit_plan.json'): file_hash(producer / 'edit_plan.json', MAX_JSON),
            str(manifest): file_hash(manifest, MAX_JSON), str(packet): file_hash(packet, MAX_JSON)}


def read_long_plan(project: Path, legacy_authority: dict | None = None, section_scope: dict | None = None) -> dict:
    """Reject gaps, ambiguous audio, clock drift and unreviewable scene ownership."""
    plan = bound_json(project / 'LONG-PROJECT.json')
    version = plan.get('schemaVersion')
    require(version in {1, 2}, 'unsupported long export schema')
    policy = _prepared_policy(project, legacy_authority)
    require(policy is None or version == 2,
            'prepared native Long projects require schema 2 visual planning')
    if version == 2:
        require(plan.get('requestPacket') and plan.get('visualPlan')
                and plan.get('visualPlanApplication'),
                'new native Long schema requires request, visual plan and execution application')
        _request_packet(plan, policy)
        validate_current_long_program_audio(project, plan)
    canvas = plan['canvas']
    budget = workload_budget(canvas)
    root, media = inspect_html((project / 'index.html').read_text())
    width, height = canvas['width'], canvas['height']
    require(type(width) is int and type(height) is int and width > height > 0
            and width <= 3840 and height <= 2160 and width % 2 == height % 2 == 0,
            'long export requires even landscape dimensions through 3840×2160')
    require(number(root['data-width']) == width and number(root['data-height']) == height,
            'long canvas differs from HTML')
    duration = Fraction(canvas['totalFrames'], 1) / clock(canvas).fps.fraction
    require(abs(number(root['data-duration']) - duration) <= Fraction(1, 1000000),
            'long root duration differs from integer output frames')
    validate_scenes(plan, media)
    validate_long_style_application(project, plan)
    validate_long_visual_plan_application(project, plan, section_scope)
    audio = [row for row in media if row.kind == 'audio']
    require(len(audio) == 1, 'long export requires one explicit complete-program float WAV')
    attrs = audio[0].attributes
    require(attrs.get('data-volume', '1') == '1' and 'muted' not in attrs,
            'long WAV is premixed; HTML audio gain/muting is unsupported')
    text = (project / 'index.html').read_text()
    require('<hf-audio-' not in text and not re.search(r'\bvolume\s*:', text),
            'long WAV is premixed; HTML audio effects/automation require explicit adaptation')
    require(attrs['src'] == local_asset(plan['audio']['file'])
            and attrs['src'].endswith('.wav') and number(attrs['data-start']) == 0
            and number(attrs.get('data-media-start', '0')) == 0
            and abs(number(attrs['data-duration']) - duration) <= Fraction(1, 1000000),
            'audio must preserve the complete program clock')
    require(set(plan['audio']) == {'file'}, 'apply cleanup to the explicit premaster before export')
    plan['budget'] = budget
    return plan


def validate_scenes(plan: dict, media: list) -> None:
    """Require contiguous scene coverage and explicit expected media at every cut."""
    scenes, canvas = plan['scenes'], plan['canvas']
    require(isinstance(scenes, list) and 0 < len(scenes) <= 256, 'invalid long scene inventory')
    cursor = 0
    videos = {row.attributes['id']: row for row in media if row.kind == 'video'}
    for scene in scenes:
        fields = {'startFrame', 'endFrame', 'mediaIds'}
        if plan['schemaVersion'] == 2:
            fields.add('visualIds')
        require(set(scene) == fields, 'unknown long scene fields')
        start, end = scene['startFrame'], scene['endFrame']
        require(type(start) is int and type(end) is int and start == cursor
                and start < end <= canvas['totalFrames'], 'long scenes must cover every frame exactly once')
        ids = scene['mediaIds']
        require(isinstance(ids, list) and len(ids) == len(set(ids)) and set(ids) <= videos.keys(),
                'scene references duplicate or unknown media')
        if plan['schemaVersion'] == 2:
            visual_ids = scene['visualIds']
            require(isinstance(visual_ids, list) and len(visual_ids) <= 64
                    and len(visual_ids) == len(set(visual_ids))
                    and all(isinstance(item, str) and re.fullmatch(
                        r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}', item)
                            for item in visual_ids),
                    'scene visual ownership is invalid')
        cursor = end
    require(cursor == canvas['totalFrames'], 'long scenes omit the ending')
    rate = clock(canvas).fps.fraction
    windows = {key: (ceil(number(row.attributes['data-start']) * rate),
        ceil((number(row.attributes['data-start']) + number(row.attributes['data-duration'])) * rate))
        for key, row in videos.items()}
    for scene in scenes:
        require(scene_media_ids(scene, windows) == set(scene['mediaIds']),
                'scene media ownership differs from literal video windows')


def scene_media_ids(scene: dict, windows: dict) -> set[str]:
    """Require complete media boundaries within one already validated contiguous scene."""
    active = set()
    for key, (start, end) in windows.items():
        if max(start, scene['startFrame']) >= min(end, scene['endFrame']):
            continue
        require(start <= scene['startFrame'] and end >= scene['endFrame'], 'scene omits an internal video boundary')
        active.add(key)
    return active


def long_audio_canvas(plan: dict) -> dict:
    """Keep dialogue review sections independent of picture-only scene changes."""
    return {**plan['canvas'], 'segments': [{'startFrame': 0,
                                          'endFrameExclusive': plan['canvas']['totalFrames']}]}


def sample_frame_count(plan: dict, section_scope: dict | None = None) -> int:
    """Reserve the exact seam/interior reference count including reverse visits."""
    canvas = plan['canvas']
    total, rate = canvas['totalFrames'], clock(canvas).fps.fraction
    start, end = section_scope['frameRange'] if section_scope else (0, total)
    require(0 <= start < end <= total, 'invalid Long sample scope')
    frames = {start, end - 1}
    boundaries = {value for scene in plan['scenes'] for value in (scene['startFrame'], scene['endFrame'])}
    frames.update(value + delta for value in boundaries for delta in range(-2, 3)
                  if start <= value + delta < end)
    frames.update(range(start, end, max(1, int(rate * 2))))
    require(len(frames) <= 3000, 'long sample schedule exceeds its bound')
    return len(frames) * 2


def disk_projection(plan: dict, retained_frames: int = 0) -> dict:
    """Include retained JPEG inventory; source frames still reserve through their own owner."""
    canvas = plan['canvas']
    pixels = canvas['width'] * canvas['height']
    require(type(retained_frames) is int and 0 <= retained_frames <= canvas['totalFrames'],
            'invalid retained Long frame count')
    retained = retained_frames * pixels * 4
    return {'sampleBytes': pixels * sample_frame_count(plan),
            'outputBytes': ceil(canvas['totalFrames'] * pixels / 4) + retained,
            'retainedFrameBytes': retained, 'miscBytes': 1024 ** 3}


def preview_window_seconds(project: Path) -> float:
    """Forecast the full declared preview inventory before any scoped child launches."""
    from cut_preview_io import bound_json
    from studio.native_review_regions import region_packet, preview_windows
    plan = bound_json(project / 'LONG-PROJECT.json')
    request = {'adapter': 'native-long', 'project': str(project), 'runtime': str(project), 'tools': {}, 'pins': {}}
    windows = preview_windows(region_packet(request))
    frames = sum(row['endFrame'] - row['startFrame'] for row in windows)
    return float(Fraction(frames, 1) / clock(plan['canvas']).fps.fraction)


def family_preview_inventory(project: Path, context: dict) -> list[dict]:
    """Freeze each logical child's exact preview ranges before the grouped launch starts."""
    from studio.native_review_regions import region_packet, preview_windows
    from studio.native_segments.review_forecast import preview_ranges
    rows = []
    for assignment in context['assignments']:
        scope = {'frameRange': assignment['frameRange']}
        request = {'adapter': 'native-long', 'project': str(project), 'sectionScope': scope,
                   'runtime': str(project), 'tools': {}, 'pins': {}}
        windows = preview_ranges(project, context, assignment['sectionId'], preview_windows(region_packet(request)))
        rows.append({'sectionId': assignment['sectionId'], 'frameRange': assignment['frameRange'],
                     'windows': [[row['startFrame'], row['endFrame']] for row in windows]})
    if len(context['assignments']) > 1:
        plan = bound_json(project / 'LONG-PROJECT.json')
        units = [{'id': f"join-{row['sectionId']}", 'hash': 'pending',
                  'startFrame': row['frameRange'][1] - 1, 'endFrame': row['frameRange'][1] + 1}
                 for row in context['assignments'][:-1]]
        joins = preview_windows({'canvas': plan['canvas'], 'units': units})
        joins = preview_ranges(project, context, None, joins)
        rows.append({'sectionId': None, 'frameRange': [0, plan['canvas']['totalFrames']],
                     'windows': [[row['startFrame'], row['endFrame']] for row in joins]})
    return rows
