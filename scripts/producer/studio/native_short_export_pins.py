"""Input pins for a native Short export: authored bytes, admitted inputs and implementation.

Split from native_short_export.py (which re-exports these names, so existing
imports and test patches of ``studio.native_short_export.input_pins`` keep working).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from audio.dialogue_cleanup import cleanup_model_binding
from audio.native_audio_finishing import native_finishing_request
from cut_preview_io import MAX_JSON, bound_json
from cross_runtime_canonical_json import canonical_compact_json
from studio.native_reference_reuse import implementation_files
from studio.native_runtime import REPO, digest
from studio.native_selected_sources import prepared_source_pins
from studio.native_short_delivery import clock
from studio.native_visual_usage_registration import usage_implementation_files


def prebuild_review_pins(plan: dict) -> dict[str, str]:
    """Retain original reviewer receipt/evidence through all owned render and reuse phases."""
    ref = plan.get('prebuildReview')
    if not ref:
        return {}
    review = bound_json(Path(ref['path']), ref['sha256'])
    return {ref['path']: ref['sha256'], **{row['path']: row['sha256'] for row in review['evidence']}}


def style_application_pins(plan: dict) -> dict[str, str]:
    """Retain copied vocabulary and related-group evidence used by authored choices."""
    application = plan.get('strategy', {}).get('styleApplication')
    if not application:
        return {}
    refs = [application['vocabulary']]
    if application.get('relatedContext'):
        refs.append(application['relatedContext'])
    return {row['path']: row['sha256'] for row in refs}


def visual_plan_pins(plan: dict) -> dict[str, str]:
    """Retain the exact external visual-plan authority through every owned stage."""
    binding = plan.get('visualPlan')
    return {binding['path']: binding['byteHash']} if binding else {}


def assert_admitted_pins(project: Path, plan: dict, manifest: dict, pins: dict) -> None:
    """A changed admitted file cannot become a new accepted hash while pins are collected."""
    expected = [(str(project / row['file']), row['sha256']) for row in manifest['files']]
    expected += [(asset['path'], asset['sha256']) for asset in plan['assets']]
    expected += list(prebuild_review_pins(plan).items())
    expected += list(style_application_pins(plan).items())
    expected += list(visual_plan_pins(plan).items())
    if plan['strategy']['schemaVersion'] >= 3:
        report = json.loads((project / 'ASSET-USE-REPORT.json').read_text())
        expected += [(row['path'], row['sha256']) for row in report['originEvidenceFiles']]
    if plan.get('requestPacket'):
        request = plan['requestPacket']
        expected.append((request['path'], request['sha256']))
        packet = json.loads(Path(request['path']).read_text())
        expected += [(row['transcript']['path'], row['transcript']['sha256'])
                     for row in packet['sources'] if row.get('transcript')]
        expected += [(row['path'], row['sha256']) for row in packet.get('availableSupportingAssets', [])
                     if row.get('sha256')]
        expected += [(row['path'], row['sha256']) for row in packet.get('selectedReferences', [])]
        related = packet.get('relatedStyleContext')
        if related:
            expected.append((related['source']['path'], related['source']['sha256']))
    for filename, expected_hash in expected:
        if pins.get(filename) != expected_hash:
            raise ValueError(f'Admitted native export input changed before pinning: {filename}')


def request_input_paths(plan: dict) -> list[Path]:
    """Return every external request input retained by a prepared Short."""
    if not plan.get('requestPacket'):
        return []
    packet_path = Path(plan['requestPacket']['path'])
    packet = json.loads(packet_path.read_text())
    paths = [packet_path]
    paths += [Path(row['transcript']['path']) for row in packet['sources']
              if row.get('transcript')]
    paths += [Path(row['path']) for row in packet.get('availableSupportingAssets', [])]
    paths += [Path(row['path']) for row in packet.get('selectedReferences', [])]
    if packet.get('relatedStyleContext'):
        paths.append(Path(packet['relatedStyleContext']['source']['path']))
    return paths


def input_pins(project: Path, runtime: Path, tools: dict) -> dict[str, str]:
    """Bind source bytes and the shared implementation used for this attempt."""
    manifest = json.loads((project / 'PROJECT-MANIFEST.json').read_text())
    paths = [project / row['file'] for row in manifest['files']]
    paths.append(project / 'PROJECT-MANIFEST.json')
    plan = json.loads((project / 'SHORT-PROJECT.json').read_text())
    paths += [Path(file) for file in prebuild_review_pins(plan)]
    paths += [Path(file) for file in style_application_pins(plan)]
    paths += [Path(file) for file in visual_plan_pins(plan)]
    paths += [Path(asset['path']) for asset in plan['assets']]
    if plan['strategy']['schemaVersion'] >= 3:
        asset_use = json.loads((project / 'ASSET-USE-REPORT.json').read_text())
        paths += [Path(row['path']) for row in asset_use['originEvidenceFiles']]
    for asset in plan['assets']:
        if asset.get('webCapture'):
            paths += [Path(asset['webCapture'][key]) for key in ('path', 'supervisionPath')]
    paths += request_input_paths(plan)
    paths += [Path(value) for value in tools.values()]
    paths += [*Path(__file__).parent.glob('native_*.*'), *(Path(__file__).parent / 'runtime').glob('*.mjs')]
    paths += list(Path(__file__).parent.parent.glob('native_render_*.py'))
    paths += list(Path(__file__).parent.parent.glob('native_work_*.py'))  # host pool admission code
    paths += list((REPO / 'src/lib/server').glob('native-*.ts'))
    paths += list((REPO / 'src/lib/server').glob('guided-native-*.ts'))
    paths += [REPO / 'scripts/producer/native-short.ts', REPO / 'src/lib/producer/short-direction.ts']
    paths += [REPO / 'src/app/api/producer/ai-edit/caption-text-contract-v1.ts']
    paths += list((REPO / 'src/lib/producer/contracts').glob('*.ts'))
    paths += [runtime / 'dist' / name for name in ('cli.js', 'native-capture-library.mjs',
              'hyperframe.runtime.iife.js', 'hyperframe.manifest.json', 'frame-source-transport.mjs',
              'native-render-sdk.mjs', 'native-export-guard.mjs')]
    paths += list((REPO / 'scripts/producer/audio').glob('*.py'))
    paths += list((REPO / 'scripts/producer/audit').glob('*.py'))
    paths += implementation_files()
    paths += usage_implementation_files()
    from graphics.visual_source_project import source_implementation_files
    paths += source_implementation_files()
    samples = clock(plan['canvas']).sample_at_frame(plan['canvas']['totalFrames'])
    finishing = native_finishing_request(plan.get('audioFinishing'), samples)
    model = cleanup_model_binding(finishing.enhance_chain) if finishing else None
    if model:
        paths.append(Path(model['path']))
    paths += [REPO / 'scripts/producer' / name for name in (
        'guided_opening_picture.py', 'guided_opening_mux.py', 'guided_picture_decode.py',
        'producer_config.py', 'fingerprints.py', 'cut_preview_io.py', 'native_work_lease.py',
        'headless/durable_files.py', 'headless/process_runner.py', 'graphics/render_tools.py',
        'edit/exact_timing.py', 'stage_timing.py', 'palmier/process_deadline.py')]
    paths.append(Path(sys.executable).resolve())
    pins = {str(file): digest(file) for file in set(paths) if file.is_file()}
    pins.update(prepared_source_pins(plan))
    assert_admitted_pins(project, plan, manifest, pins)
    return pins


def require_readable_request(request: dict) -> None:
    """Refuse an oversized inherited proof before publishing an unreadable export request."""
    size = len((canonical_compact_json(request) + '\n').encode())
    if size > MAX_JSON:
        raise ValueError(f'Native Short export request is {size} bytes, above its {MAX_JSON}-byte reader limit. '
                         'The retained revision proof chain must be reduced before another export; '
                         'no unreadable request or new attempt was published.')
