"""Shared assertions for actual synthetic audio-only graph revisions.

This helper still invokes the fixture's real graph CLI; it does not emulate the
renderer or authorize media. Sequential test cases retain their original order.
The composite node aliases the audio-bearing final artifact in this fixture.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any

from audio.audio_mix_picture import packet_signature
from current_render_graph_store import load_active
from cut_preview_io import bound_json


def audio_only_revision(
    case: Any, label: str, change: dict,
) -> tuple[list[dict], dict]:
    """Run one real revision and check picture reuse without claiming speedup.

    Source, timeline, base and dialogue nodes remain reused. Composite and final
    are dirty because they share the changed audio-bearing output artifact.
    """
    picture = packet_signature(str(case.output / 'final.mp4'), 'v:0')
    before = bound_json(case.output / 'program_audio.v2.json')
    plan = bound_json(case.output / 'edit_plan.json')
    plan.update(change)
    (case.output / 'edit_plan.json').write_text(json.dumps(plan))
    rows = case.command('assemble', label)
    done = next(row for row in rows if row.get('status') == 'done')
    case.assertTrue(done['pictureReusedForAudioRevision'], label)
    case.assertTrue(done['delivery']['qualified'], label)
    case.assertEqual(picture, packet_signature(str(case.output / 'final.mp4'), 'v:0'), label)
    case.assertFalse(any(row.get('stage') == 'graphics' for row in rows),
                     f'{label}: the graphics/composite stage must not run for an audio-only revision')
    case.assertFalse(any(row.get('status') in ('composite', 'caption_composite_reused', 'exit_on_cut_clamped')
                         for row in rows), label)
    after = bound_json(case.output / 'program_audio.v2.json')
    case.assertNotEqual(before['audioProgramInputHash'], after['audioProgramInputHash'], label)
    case.assertEqual(before['pictureReuseInputHash'], after['pictureReuseInputHash'], label)
    latest = load_active(case.output)
    # node-composite's artifact IS final.mp4 when no caption-free composite exists, so it
    # reads dirty whenever the AAC in that container changes; the graphics-event absence
    # above is the non-invocation proof. Every picture INPUT node must be reused.
    case.assertEqual(latest[1]['dirtyNodeIds'], ['node-composite', 'node-final'], f'{label}: {latest[1]["dirtyNodeIds"]}')
    for node_id in ('node-source', 'node-timeline', 'node-base', 'node-dialogue'):
        case.assertIn(node_id, latest[1]['reusedNodeIds'], label)
    nodes = {row['nodeId']: row for row in latest[0]['nodes']}
    case.assertEqual(nodes['node-composite']['outputArtifactHash'], nodes['node-final']['outputArtifactHash'],
                     'composite and final share one artifact here; composite inputs are unchanged')
    return rows, after


def prepare_test_review(project: Path, output: Path) -> None:
    """Isolate real graph/audio tests with declared TEST-only editorial evidence."""
    approval = project / 'src/lib/server/__tests__/_plan-readiness-fixture.ts'
    reviewed = subprocess.run([os.environ.get('SNIPER_NODE_PATH', 'node'), '--import', 'tsx',
        str(approval), str(output)], cwd=project, check=False,
        capture_output=True, text=True, timeout=120)
    if reviewed.returncode:
        raise RuntimeError(f'TEST review fixture failed: {reviewed.stderr}')
