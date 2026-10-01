"""TEST port of what the native Short writer recomputes on every build, so TEST plans are writer-shaped (X211(4)).

Each function mirrors one writer definition at stack 35eca01b (``coordination_catalog.SUMMARY_WRITERS``): catalog
file digests from the staged bytes, the visual-plan implementation hashes, the pacing timing/visual hashes, the
visual-source subject hash, and the asset-use and story revision hashes. Digests use ``cut_preview_io.digest`` (the
compact canonical JSON the TS ``canonicalJsonSha256`` mirrors); byte equality with the TS writer is not claimed and
not needed: the tests need only that each hash follows its sources as the writer's does. TEST data only.
"""
from __future__ import annotations

from pathlib import Path

from _role_packet_fixture import sha
from cut_preview_io import digest


def _visual(plan: dict) -> dict:
    """native-short-pacing-observations.ts:22-29 (visualHash's inputs)."""
    canvas, strategy = plan['canvas'], plan['strategy']
    optional = {'captionMode': canvas.get('captionMode') if canvas.get('captionMode') == 'source-burned' else None,
                'captionCorrections': canvas.get('captionCorrections') or None,
                'captionSuppressions': canvas.get('captionSuppressions') or None}
    return {**{key: value for key, value in optional.items() if value is not None},
            **{key: canvas[key] for key in ('pictureViews', 'captionViews', 'text', 'shapes', 'motion')},
            'titleCard': canvas.get('titleCard'), 'extension': plan.get('extension'), 'scenes': strategy['scenes'],
            'supporting': [row for row in strategy['supportingSearch']['candidates'] if row.get('selected')],
            'assets': [{key: row[key] for key in ('file', 'sha256', 'role')} for row in plan['assets']]}


def _asset_revision(plan: dict) -> str:
    """native-short-asset-use.ts:13-18."""
    assets = [{**{key: row[key] for key in ('file', 'sha256', 'role')}, 'origin': row.get('origin'),
               'webCapture': row.get('webCapture')} for row in plan['assets']]
    return digest({'request': plan['request'], 'requestPacket': plan.get('requestPacket'), 'canvas': plan['canvas'],
                   'extension': plan.get('extension'), 'assets': assets, 'scenes': plan['strategy']['scenes'],
                   'supportingSearch': plan['strategy']['supportingSearch']})


def _catalog(plan: dict, folder: Path) -> None:
    """Staged catalog digests, then every visual-plan binding that names them (native-visual-plan-application.ts:124)."""
    staged = {}
    for row in plan.get('catalogFiles') or []:
        row['sha256'] = staged[row['file']] = sha(folder / row['file'])
    for decision in (plan['strategy'].get('visualPlanApplication') or {}).get('decisions', []):
        for binding in [*decision['catalogBindings'], *decision['binding'].get('mounts', [])]:
            binding['implementationSha256'] = staged[binding['file']]


def refresh(plan: dict, folder: Path) -> None:
    """Recompute, in the writer's order, everything it derives from the plan and the staged files."""
    _catalog(plan, folder)
    canvas, strategy = plan['canvas'], plan['strategy']
    pacing = strategy.get('pacing')
    if pacing is not None:
        timing = {key: canvas[key] for key in ('cuts', 'segments', 'frameRate', 'totalFrames', 'occurrences', 'captionGroups')}
        pacing.update(timingHash=digest({**timing, 'source': canvas['sourceFile']}), visualHash=digest(_visual(plan)))
    if plan.get('visualSources') is not None:
        plan['visualSources']['subjectSha256'] = digest({'canvas': canvas, 'extension': plan.get('extension'),
                                                         'catalogFiles': plan.get('catalogFiles') or [],
                                                         'catalogTitle': plan.get('catalogTitle')})
    revision = _asset_revision(plan)
    if strategy.get('assetUse') is not None:
        strategy['assetUse']['revisionHash'] = revision
    if strategy.get('story') is not None:
        strategy['story']['revisionHash'] = digest({
            'assetRevisionHash': revision, 'assetUse': strategy.get('assetUse'), 'pacing': pacing,
            'viewerBenefit': strategy['viewerBenefit'], 'hookReasonToWatch': strategy['hookReasonToWatch'],
            'payoff': strategy['payoff'], 'expectations': plan.get('expectations')})


def writer_fields(plan: dict) -> None:
    """Add the writer-required fields a real plan carries (placeholders; ``refresh`` fills every hash)."""
    strategy = plan['strategy']
    strategy['pacing'].update(schemaVersion=1, timingHash='', visualHash='', lanes={'captions': 'TEST'})
    strategy.update(viewerBenefit='TEST benefit', hookReasonToWatch='TEST hook', payoff='TEST payoff',
                    supportingSearch={'searchedSourceFiles': ['assets/raw.mp4'], 'conclusion': 'TEST',
                                      'candidates': [{'assetFile': 'assets/raw.mp4', 'selected': True, 'reason': 'TEST'}]},
                    assetUse={'schemaVersion': 1, 'revisionHash': '', 'policy': 'TEST', 'intendedUse': 'TEST',
                              'decisions': []},
                    story={'schemaVersion': 1, 'revisionHash': '', 'viewerQuestion': 'TEST', 'payoff': 'TEST',
                           'continuity': {'id': 'TEST', 'subject': 'TEST'}, 'beats': []},
                    visualPlanApplication={'schemaVersion': 1, 'route': 'native-short', 'visualPlanSha256': 'b' * 64,
                                           'decisions': [_decision()]})
    plan['visualPlan'] = {'path': '/TEST/VISUAL-PLAN.json', 'sha256': 'b' * 64}
    plan['visualSources'].update(schemaVersion=1, subjectSha256='', request={'path': '/TEST/request.json', 'sha256': 'c' * 64})


def _decision() -> dict:
    """One TEST visual-plan decision executed by the lower-third region's catalog mount."""
    mount = {'file': 'compositions/lower-third.html', 'mountId': 'lower', 'catalogId': 'TEST-lower',
             'sourceSha256': 'd' * 64, 'implementationSha256': ''}
    return {'opportunityId': 'o1', 'candidateId': 'c1', 'anatomy': 'TEST', 'development': 'TEST', 'startFrame': 15,
            'endFrameExclusive': 45, 'sceneIndexes': [0], 'visibleIds': ['lower'], 'catalogBindings': [dict(mount)],
            'binding': {'kind': 'catalog', 'mounts': [dict(mount)]}}
