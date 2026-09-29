"""Require current-project pixel comparisons before a reused Long window can seal.

The existing window owner runs every subprocess inside its media jail and budget.
This is a bounded per-attempt technical check, not general runtime qualification
or editorial approval. Its original StageEvidence must survive every later read.
"""
from __future__ import annotations

import subprocess
import json
from pathlib import Path

from cut_preview_io import bound_json, write_new
from studio.native_runtime import digest
from studio.native_segments.dependency import inventory
from studio.native_segments.long_plan import identity
from studio.native_segments.verify import verify_long_segment_probes
from studio.native_stage_evidence import require

KIND = 'native-long-current-dependency-comparison'


def file_pin(file: Path) -> dict:
    """Bind one immutable owned artifact to its canonical bytes."""
    require(file.resolve(strict=True) == file and file.is_file(), 'dependency probe artifact must be canonical')
    return {'path': str(file), 'sha256': digest(file)}


def dependency_frames(window: dict, project: Path | None = None) -> list[int]:
    """Bound exact window edges/interiors plus every declared compiled motion boundary."""
    start, end = window['startFrame'], window['endFrame']
    points = {start, end - 1, (start + end - 1) // 2,
              *range(start, end, max(1, (end - start + 7) // 8))}
    if project is not None:
        points.update(motion_frames(project, window))
    require(len(points) <= 64, 'declared dependency states exceed bounded probe owner; rerender this window')
    return sorted(points)


def motion_frames(project: Path, window: dict) -> list[int]:
    """Read exact compiled tween endpoints; arbitrary authored scripts are never inferred."""
    from studio.native_region_contract import read_region_map
    from studio.native_region_motion import script_text, validate_motion
    from studio.native_segments.dom import elements, parse
    if not (project / 'REVIEW-REGIONS.json').exists():
        return []
    rows = read_region_map(project, bound_json(project / 'LONG-PROJECT.json')['canvas'])
    selected = [row for row in rows if row['startFrame'] < window['endFrame'] and row['endFrame'] > window['startFrame']]
    boundaries = []
    for row in selected:
        scripts = [node for node in elements(parse((project / row['file']).read_text()))
                   if node.tag == 'script' and node.attr('data-native-section-motion') is not None]
        tweens = [tween for node in scripts for tween in validate_motion(json.loads(script_text(node)))['tweens']]
        boundaries.extend(row['startFrame'] + tween[key] + offset for tween in tweens
                          for key in ('startFrame', 'endFrame') for offset in (-1, 0, 1))
    return [frame for frame in boundaries if window['startFrame'] <= frame < window['endFrame']]


def execute_dependency_probe(request: dict, phase: str, directory: Path, value: dict) -> dict:
    """Capture and compare current pixels; replace value.probes with this owner's references."""
    from studio.native_segments.owners import segment_phase
    index = segment_phase(phase)
    work = directory / 'dependency-capture'
    request_file = Path(request['output']) / 'export-request.json'
    expected = dependency_frames(value['window'], Path(request['project']))
    subprocess.run([request['tools']['node'], str(Path(__file__).with_suffix('.mjs')),
                    str(request_file), str(index), str(work), json.dumps(expected)], check=True, timeout=540)
    capture_file = work / 'capture.json'
    capture = bound_json(capture_file)
    require(capture['window'] == value['window'] and capture['planIdentity'] == request['revision']['identity']
            and [row['frame'] for row in capture['probes']] == expected, 'current dependency capture identity differs')
    comparison = verify_long_segment_probes(capture['probes'], value['piece'], request['revision']['canvas'], work / 'comparison')
    result_file = work / 'comparison.json'
    write_new(result_file, comparison)
    proof = {'schemaVersion': 1, 'kind': KIND, 'phase': phase, 'planIdentity': request['revision']['identity'],
        'window': value['window'], 'project': request['project'], 'projectInputs': identity(inventory(Path(request['project']))),
        'implementation': identity(request['sectionImplementationPins']), 'request': file_pin(request_file),
        'donor': file_pin(Path(value['piece']['path'])), 'capture': file_pin(capture_file), 'comparison': file_pin(result_file),
        'frames': expected, 'passed': True, 'runtimeQualification': 'not-established', 'editorialApproval': False}
    proof_file = directory / 'dependency-proof.json'
    write_new(proof_file, proof)
    value['probes'] = capture['probes']
    return file_pin(proof_file)


def probe_artifacts(value: dict) -> dict[str, Path]:
    """Seal both detailed native capture and comparison, alongside the screenshot inventory."""
    ref = value.get('dependencyProbe')
    if ref is None:
        return {}
    proof = bound_json(Path(ref['path']), ref['sha256'])
    return {'dependencyProof': Path(ref['path']), 'dependencyCapture': Path(proof['capture']['path']),
            'dependencyComparison': Path(proof['comparison']['path'])}


def require_dependency_probe(request: dict, phase: str, value: dict, record: dict) -> None:
    """Rehash original sealed current-pixel evidence, retaining exact-resume compatibility."""
    original = bound_json(Path(record['request']['path']), record['request']['sha256'])
    cross = original.get('sectionRepair') or original.get('sectionIntegrations')
    if not cross or phase not in original['revision'].get('windowDonors', {}):
        return
    ref = value.get('dependencyProbe')
    require(type(ref) is dict and ref == record['artifacts'].get('dependencyProof'),
            'reused Long section lacks sealed current-project dependency comparison')
    proof = bound_json(Path(ref['path']), ref['sha256'])
    require(proof.get('kind') == KIND and proof.get('schemaVersion') == 1 and proof.get('passed') is True
            and proof.get('phase') == phase and proof.get('window') == value['window']
            and proof.get('planIdentity') == request['revision']['identity'], 'stale dependency comparison generation')
    require(proof.get('project') == request['project']
            and proof.get('projectInputs') == identity(inventory(Path(request['project'])))
            and proof.get('implementation') == identity(request['sectionImplementationPins']), 'dependency comparison inputs changed')
    require(proof.get('request') == record['request'] and proof.get('donor') == record['artifacts']['media']
            and proof['donor']['sha256'] == value['piece']['sha256'], 'dependency comparison names another donor or request')
    require(proof.get('capture') == record['artifacts'].get('dependencyCapture')
            and proof.get('comparison') == record['artifacts'].get('dependencyComparison'), 'dependency comparison artifacts are unsealed')
    capture = bound_json(Path(proof['capture']['path']), proof['capture']['sha256'])
    comparison = bound_json(Path(proof['comparison']['path']), proof['comparison']['sha256'])
    expected = dependency_frames(value['window'], Path(request['project']))
    require(proof['frames'] == comparison.get('absoluteFrames') == expected and comparison.get('passed') is True,
            'dependency comparison did not cover every required current frame')
    observed = [(row['frame'], row['sha256']) for row in capture['probes']]
    require(observed == [(row['frame'], row['sha256']) for row in value['probes']]
            and [frame for frame, _sha in observed] == expected, 'dependency native reference inventory changed')
    require(all(record['artifacts'].get(f'probe{index}') == {'path': row['path'], 'sha256': row['sha256']}
                for index, row in enumerate(capture['probes'])), 'dependency native references are unsealed')
