"""TEST builders for the P3a plan-record tests (MASTER-PLAN M-081): a synthetic native Short project on L-Q's TEST
production, and Short and Long plan records around it.

The production (admitted manifest, word-timed transcript, sealed version 2 shared evidence, TEST authority reader)
is L-Q's ``SpeakerEvidenceFixture``; nothing starts a child process. The native plan copies the dense fixture's key
set (perf/fixture-dense-v1, read once by the lane; no home path ships, U-T6) with TEST values whose kept words, cuts
and frames match the TEST transcript. Every value is TEST-labelled: no plan, approval, review or observation here is
real. M-082 (L-T2) adds the assignment-binding builders.
"""
from __future__ import annotations

import _live_state_isolation  # noqa: F401  private budget/pool roots; live state refused

import contextlib
import copy
import json
from collections.abc import Iterator
from pathlib import Path

import role_packet_approvals as approvals
from _coordination_writer import refresh, writer_fields
from _role_packet_evidence_v2_fixture import SpeakerEvidenceFixture
from _role_packet_fixture import sha
from cross_runtime_canonical_json import canonical_compact_json
from role_packet_native import plan_hash
from role_packet_transcript import observe_transcript
from studio.native_short_regions import DERIVATION, ISOLATION_RULE
from studio.production.coordination_catalog import RESPONSIBILITIES, SUMMARY_SOURCES, WORK_COUNTERS
from studio.production.plan_fields import authored_digest
from studio.production.plan_record import slice_digest
from studio.production.plan_short_projection import short_sections

BATCH, OUTPUT, TASK, TOKEN, KIND = 'batch-test', 'Q9', 'author-q9', 'a' * 32, 'sniper-coordination-plan'
WHOLE = {'range': None, 'entryIds': None}
TITLE = 'TEST title'
RANGES = [[10, 11], [13, 13]]          # words 10, 11 and 13 of the TEST transcript (word i spans [i, i + 0.5] s)
WORDS = [[0, 0, 10, 0, 15, 'TEST', 0], [1, 0, 11, 30, 45, 'given', 0], [2, 1, 13, 45, 60, 'words', 0]]
CUTS = [{'start': 10.0, 'end': 11.5, 'speed': 1}, {'start': 13.0, 'end': 13.5, 'speed': 1}]
SEGMENTS = [{'startFrame': 0, 'endFrameExclusive': 45}, {'startFrame': 45, 'endFrameExclusive': 60}]
INDEX = ('<main><div id="lower" data-composition-src="compositions/lower-third.html" data-start="0.5" '
         'data-duration="1"></div></main>')
UNIT = {'id': 'lower-third', 'file': 'compositions/lower-third.html', 'startFrame': 15, 'endFrame': 45,
        'isolation': {'status': 'scoped', 'rule': ISOLATION_RULE, 'globalSha256': 'c' * 64}}
COMPOSITIONS = {'lower-third.html': '<div data-hf-reveal="0.4">TEST lower third</div>',
                'extra.html': '<div>TEST composition outside every region</div>'}


def pin_of(path: Path) -> dict:
    """The exact-byte pin of a TEST file."""
    return {'path': str(path), 'sha256': sha(path), 'bytes': path.stat().st_size}


def write_plan(path: Path, plan: dict) -> dict:
    """Write a record as exact canonical bytes (+ newline) and return its pin."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes((canonical_compact_json(plan) + '\n').encode())
    return pin_of(path)


def canvas() -> dict:
    """A TEST canvas with the dense fixture's keys and three kept words in two cuts."""
    style = {'align': 'center', 'color': '#FFFFFF'}
    return {'background': '#000000', 'captionCorrections': [], 'captionGroups': [[0, 1], [2]], 'captionMode': 'native',
            'captionProtectedPhrases': [[0, 1]],   # the sealed TEST record protects words 10-11 (P2-05, P2-08)
            'captionViews': [{'startFrame': 0, 'endFrame': 60, 'box': [0, 1600, 1080, 200], 'style': style}],
            'cuts': copy.deepcopy(CUTS), 'frameRate': '30/1', 'occurrences': copy.deepcopy(WORDS),
            'motion': [{'id': 'label', 'startFrame': 32, 'durationFrames': 10, 'ease': 'power2.out',
                        'from': {'y': 10, 'scale': 1, 'opacity': 0}, 'to': {'y': 0, 'scale': 1, 'opacity': 1}}],
            'pictureViews': [{'startFrame': 0, 'endFrame': 45, 'box': [0, 0, 1080, 1620], 'crop': [100, 0, 720, 1080]},
                             {'startFrame': 45, 'endFrame': 60, 'box': [0, 0, 1080, 1620], 'crop': [900, 0, 720, 1080]}],
            'segments': copy.deepcopy(SEGMENTS), 'shapes': [{'id': 'bar', 'startFrame': 40, 'endFrame': 50,
                                                             'box': [0, 0, 10, 10], 'fill': '#000'}],
            'sourceFile': 'assets/raw.mp4', 'sourceSize': {'w': 1920, 'h': 1080},
            'text': [{'id': 'label', 'startFrame': 30, 'endFrame': 60, 'text': 'TEST label', 'role': 'label'}],
            'title': 'TEST', 'titleCard': {'copy': {'text': TITLE}, 'endFrame': 30, 'lines': [TITLE], 'palette': 'TEST',
                                           'top': 100, 'fontSize': 64}, 'totalFrames': 60}


def strategy() -> dict:
    """TEST pacing beats and two contiguous scenes."""
    beats = [{'startFrame': 0, 'endFrame': 45, 'occurrenceIds': [0, 1], 'reason': 'TEST opening'},
             {'startFrame': 45, 'endFrame': 60, 'occurrenceIds': [2], 'reason': 'TEST close'}]
    scenes = [{'startFrame': 0, 'endFrame': 45, 'holdFrames': 10, 'visibleIds': ['source-0'], 'format': 'presenter',
               'exitReason': 'TEST cut'},
              {'startFrame': 45, 'endFrame': 60, 'holdFrames': 5, 'visibleIds': ['source-1'], 'format': 'diagram',
               'exitReason': 'TEST end'}]
    return {'schemaVersion': 3, 'pacing': {'beats': beats, 'holds': [{'targetId': 'lower', 'startFrame': 15,
                                                                    'endFrame': 45, 'minimumFrames': 5}]},
            'scenes': scenes, 'selectedTreatment': 'TEST treatment', 'references': []}


class PlanFixture(SpeakerEvidenceFixture):
    """L-Q's TEST production plus a writer-shaped native Short plan, its project folder, an approval and records."""

    compositions = COMPOSITIONS   # a test replaces this (``staged``) to stage other composition bytes

    @contextlib.contextmanager
    def staged(self, files: dict[str, str]) -> Iterator[None]:
        """Stage other composition bytes (file name -> text) for the projects written inside the block."""
        self.compositions = {**COMPOSITIONS, **files}
        try:
            yield
        finally:
            self.compositions = COMPOSITIONS

    def native_plan(self) -> dict:
        """The TEST native Short plan; its request packet binds the TEST manifest."""
        request = self.write('requests/q9/SHORT-REQUEST.json', {'schemaVersion': 1, 'scope': 'TEST', 'manifest': {
            'path': str(self.manifest), 'sha256': sha(self.manifest)}})
        plan = {'schemaVersion': 1, 'request': {'selection': 'auto'}, 'strategy': strategy(), 'canvas': canvas(),
                'assets': [{'file': 'assets/raw.mp4', 'path': str(self.media), 'role': 'source', 'sha256': sha(self.media),
                            'origin': {'path': '/TEST/origin.json', 'sha256': 'e' * 64}},
                           {'file': 'assets/web.png', 'path': '/TEST/web.png', 'role': 'image', 'sha256': 'f' * 64,
                            'webCapture': {'path': '/TEST/capture.json', 'sha256': '1' * 64,
                                           'supervisionPath': '/TEST/supervision.json', 'supervisionSha256': '2' * 64}}],
                'catalogFiles': [{'file': f'compositions/{name}', 'path': f'/TEST/catalog/{name}', 'sha256': '',
                                  'catalogId': f'TEST-{name}', 'sourceSha256': '3' * 64} for name in COMPOSITIONS],
                'requestPacket': {'path': str(request), 'sha256': sha(request)},
                'preparedSources': {'path': '/TEST/package/selected-sources-stage.json', 'sha256': '4' * 64},
                'audioFinishing': {'schemaVersion': 1, 'rationale': 'TEST', 'audioEnhance': {'preset': 'voice'}},
                'visualSources': {'decisions': [{'route': 'catalog', 'item': 'TEST'}], 'policyVersion': 1},
                'prebuildReview': {'path': '/TEST/PREBUILD-REVIEW.json', 'sha256': '0' * 64},
                'draft': {'schemaVersion': 1, 'state': 'review-pending'},
                'guidedBinding': {'schemaVersion': 1, 'kind': 'guided-native-proposal-binding', 'nativePlanHash': '0' * 64,
                                  'resolutions': []}}
        writer_fields(plan)
        return plan

    def project(self, plan: dict, name: str = 'project', regions: bool = True, evidence: Path | None = None) -> dict:
        """Write a TEST project folder for ``plan`` and return its homes (evidence binds ``sharedEvidence``)."""
        folder = self.root / name
        (folder / 'compositions').mkdir(parents=True)
        for file, content in self.compositions.items():
            (folder / 'compositions' / file).write_text(content)
        (folder / 'index.html').write_text(INDEX)
        if regions:
            (folder / 'REVIEW-REGIONS.json').write_text(json.dumps(
                {'schemaVersion': 2, 'derivation': DERIVATION, 'units': [UNIT]}))
        plan = copy.deepcopy(plan)
        if evidence is not None:
            record = json.loads(evidence.read_text())
            plan['sharedEvidence'] = {'path': str(evidence), 'sha256': sha(evidence),
                                      'contentSha256': record['contentSha256'], 'version': record['version']}
        refresh(plan, folder)
        (folder / 'SHORT-PROJECT.json').write_text(json.dumps(plan))
        return {'nativePlan': pin_of(folder / 'SHORT-PROJECT.json'), 'project': str(folder), 'planHash': plan_hash(plan),
                'regions': pin_of(folder / 'REVIEW-REGIONS.json') if regions else None,
                'sharedEvidence': None if evidence is None else pin_of(evidence), 'longChunks': None}

    def leaf_outcome(self, plan: dict, path: tuple, base: bytes) -> tuple[str, dict | None]:
        """How one perturbed leaf ends: writer-refused, recomputed (identical plan), refused, or its record."""
        try:
            homes = self.project(perturbed(plan, path), name=f'leaf-{"-".join(map(str, path))}')
        except (OSError, KeyError):          # the TEST writer port refuses it, as the writer does (a missing file)
            return 'writer-refused', None
        if Path(homes['nativePlan']['path']).read_bytes() == base:
            return 'recomputed', None       # the writer recomputes this leaf from other fields or the staged bytes
        try:
            return 'derived', self.short_record(homes)
        except ValueError as error:
            self.assertTrue(str(error).startswith('Coordination plan: '), str(error))
            return 'refused', None

    def approval_row(self, word_ranges: list | None = None, title: str = TITLE) -> dict:
        """The authority's approval row for the TEST output (title and word ranges on the TEST transcript)."""
        transcript = observe_transcript(str(self.transcript), 60.0)
        row = approvals.approval_row(title, approvals.derive_script(sha(self.media), transcript, word_ranges or RANGES))
        return {**row, 'previous': None, 'elapsed': 0.0, 'recordedBy': 'TEST'}

    def authority(self, row: dict) -> dict:
        """An in-memory TEST batch record holding the output's approvals (what a freeze reads under the lock)."""
        return {'batchId': BATCH, 'status': 'active', 'clips': {OUTPUT: {'approvals': [row]}}}

    def short_record(self, homes: dict, row: dict | None = None, **changes: object) -> dict:
        """A version 1 Short record derived from ``homes``; the author owns every responsibility."""
        row = row or self.approval_row()
        sections = short_sections(homes)
        total = sections['clock']['totalFrames']
        remaining = {key: {'planReview': 1, 'review': 2}.get(key, 0) for key in WORK_COUNTERS}
        record = {'schemaVersion': 1, 'kind': KIND, 'batchId': BATCH, 'outputId': OUTPUT, 'format': 'short',
                  'version': 1, 'parent': None, 'integration': {'taskId': TASK, 'epoch': 1, 'token': TOKEN},
                  'approvedContent': {'approvalIdentity': row['identity'], 'titleSha256': row['titleSha256'],
                                      'scriptSha256': row['script']},
                  'homes': homes, 'inputs': [], 'sections': [], **sections, 'unresolved': [],
                  'ownership': [{'responsibility': name, 'range': [0, total], 'owner': {'task': TASK}}
                                for name in RESPONSIBILITIES],
                  'contributions': [], 'conflicts': [], 'workPlan': {'remaining': remaining, 'reserve': 'one-repair'},
                  'decisions': [], 'changeClass': 'initial'}
        record.update(changes)
        return record


def authored(**fields: object) -> dict:
    """A Long authored entry with its code-computed digest."""
    return {**fields, 'digest': authored_digest(fields)}


def long_record(total: int = 300) -> dict:
    """A version 1 TEST Long record: sections A, B, C; one beat each; one graphic, hold, caption rule and transition."""
    thirds = [[0, 100], [100, 200], [200, total]]
    story = [authored(id=f'beat-{key}', range=span, occurrenceIds=None, purpose=f'TEST beat {key}')
             for key, span in zip('ABC', thirds)]
    graphics = [authored(id='g1', lane='lower', range=[10, 60], revealFrame=20, hiddenUntilReveal=True,
                         source={'kind': 'catalog', 'ref': 'TEST item'}, feasibility='feasible', evidence=[],
                         isolation='scoped')]
    transitions = [authored(id='t-ab', boundaryFrame=100, range=[90, 110], outgoing='A', incoming='B', state='planned',
                            owner={'task': TASK})]
    remaining = {key: {'planReview': 1, 'author': 3, 'review': 6}.get(key, 0) for key in WORK_COUNTERS}
    return {'schemaVersion': 1, 'kind': KIND, 'batchId': BATCH, 'outputId': 'L1', 'format': 'long', 'version': 1,
            'parent': None, 'integration': {'taskId': TASK, 'epoch': 1, 'token': TOKEN},
            'approvedContent': {'outputIdentity': 'b' * 64},
            'homes': {key: None for key in ('nativePlan', 'project', 'planHash', 'regions', 'sharedEvidence',
                                            'longChunks')},
            'inputs': [], 'clock': {'frameRate': '30/1', 'totalFrames': total}, 'speech': None,
            'sections': [{'id': key, 'range': span} for key, span in zip('ABC', thirds)], 'story': story,
            'holds': [authored(id='h1', subject='g1', range=[10, 60], minimumFrames=20)], 'framing': [],
            'captions': [authored(id='c1', range=None, rule='TEST captions stay in the lower third')],
            'graphics': graphics, 'transitions': transitions, 'audio': [], 'sourceFacts': [], 'unresolved': [],
            'ownership': [{'responsibility': name, 'range': [0, total], 'owner': {'task': TASK}}
                          for name in RESPONSIBILITIES],
            'contributions': [], 'conflicts': [], 'workPlan': {'remaining': remaining, 'reserve': 'one-repair'},
            'decisions': [], 'changeClass': 'initial'}


def canonical_size(plan: dict) -> int:
    """Canonical JSON bytes of a record."""
    return len(canonical_compact_json(plan).encode())


def padded_long(target: int) -> dict:
    """A valid TEST Long record of exactly ``target`` canonical bytes, padded with graphics rule evidence."""
    plan = long_record()
    pads = [{'id': f'pad-{index}', 'lane': f'pad{index}', 'range': [10, 60], 'revealFrame': 20,
             'hiddenUntilReveal': False, 'source': {'kind': 'custom', 'ref': 'TEST'}, 'feasibility': 'feasible',
             'evidence': ['x' * 500] * 16, 'isolation': 'scoped', 'digest': '0' * 64} for index in range(127)]
    plan['graphics'] += pads
    rows, over = iter(reversed(pads)), canonical_size(plan) - target
    row = next(rows)
    while over >= 500:
        row = row if len(row['evidence']) > 1 else next(rows)
        row['evidence'].pop()
        over = canonical_size(plan) - target
    row['evidence'][-1] = 'x' * (500 - over)
    for pad in pads:
        pad['digest'] = authored_digest({key: value for key, value in pad.items() if key != 'digest'})
    return plan


def moved(before: dict, after: dict, scope: dict = WHOLE) -> frozenset[str]:
    """Responsibilities whose slice over ``scope`` differs between two records."""
    return frozenset(name for name in RESPONSIBILITIES if slice_digest(before, name, scope) != slice_digest(after, name, scope))


def leaves(value: object, path: tuple = ()) -> list[tuple]:
    """Every scalar, and every empty list or object, of a JSON value, as its key path."""
    if isinstance(value, dict) and value:
        return [leaf for key, item in value.items() for leaf in leaves(item, (*path, key))]
    if isinstance(value, list) and value:
        return [leaf for index, item in enumerate(value) for leaf in leaves(item, (*path, index))]
    return [path]


def perturbed(plan: dict, path: tuple) -> dict:
    """A copy of ``plan`` with the leaf at ``path`` changed."""
    changed = copy.deepcopy(plan)
    holder = changed
    for key in path[:-1]:
        holder = holder[key]
    value = holder[path[-1]]
    swaps = {bool: lambda: not value, int: lambda: value + 1, float: lambda: value + 0.5, str: lambda: value + 'x',
             list: lambda: [*value, 'TEST'], dict: lambda: {**value, 'TEST': 1}, type(None): lambda: 'TEST'}
    holder[path[-1]] = swaps[type(value)]()
    return changed


def summarised(path: tuple) -> bool:
    """Whether a leaf lies under a writer-verified summary (X211(4); proved in test_coordination_writer_plan)."""
    dotted = '.'.join(map(str, path))
    return any(dotted == root or dotted.startswith(f'{root}.') for root in SUMMARY_SOURCES)
