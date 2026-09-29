"""Real authority and sealed synthetic media for incremental Long review tests."""
from __future__ import annotations

import json
from pathlib import Path

from _native_long_isolation_fixture import write_static_project
from cut_preview_io import write_new
from studio.native_runtime import digest
from studio.native_segments.plan import initial_long_plan
from studio.production import api
from studio.production.claims import ClaimRef
from studio.production.section_chunk_plan import freeze_chunk_plan, read_chunk_plan, scope_manifest, scope_observations
from studio.production.section_plan import pin_file, unique_pins
from studio.production.section_results import CHECKS, claim_directory
from studio.production.sections import early_result, enqueue_section_authors, review_task
from test_production_sections import ProductionSectionsTests


class ChunkFixture:
    """Two sixty-second chunks in one creative assignment; execution and judgments are fictional."""

    def __init__(self, test: object) -> None:
        """Reuse actual task, clock, author, preview and StageEvidence fixtures."""
        self.host = ProductionSectionsTests()
        self.host.setUp()
        test.addCleanup(self.host.doCleanups)
        host = self.host
        canvas = {'width': 320, 'height': 180, 'frameRate': '1/1', 'totalFrames': 180}
        project = host.fixture.project
        write_static_project(project, canvas, ('A1', 'A2', 'C'))
        (project / 'LONG-PROJECT.json').write_text(json.dumps({'canvas': canvas, 'scenes': [
            {'startFrame': start, 'endFrame': start + 60} for start in (0, 60, 120)]}))
        host.fixture.inputs.update({str(file): digest(file) for file in project.rglob('*') if file.is_file()})
        host.request.update(pins=dict(host.fixture.inputs), revision=initial_long_plan(canvas, 'a' * 64,
                                                                                    [0, 60, 120, 180]))
        host.plan['assignments'] = [host.assignment('first', [0, 120], 'index.html'),
                                    host.assignment('last', [120, 180], 'LONG-PROJECT.json')]
        host.planfile = host.budget.base / 'chunk-assignments.json'
        write_new(host.planfile, host.plan)
        host.context = enqueue_section_authors(host.planfile)['sectionProduction']
        host.preview = host.make_previews()
        host.bind()
        host.early()
        self.start()

    def start(self, row: dict | None = None) -> None:
        """Attach the same assigned reviewer protocol to a selected real-authority test host."""
        host = self.host
        self.spec = self.enqueue(row)
        claim = api.claim_task(host.budget.root, 'section-test', self.spec.task_id, host.handle('director'))
        self.ref = ClaimRef(self.spec.task_id, claim['epoch'], claim['token'])
        api.attach_task(host.budget.root, 'section-test', self.ref, host.handle('TEST-chunk-reviewer'))
        claim_directory(self.task()).mkdir(parents=True)

    def enqueue(self, row: dict | None = None) -> object:
        """Register one ordinary encoded reviewer before later chunk media exists."""
        host = self.host
        row = row or host.context['assignments'][0]
        early_pin, early = early_result(host.request, row, host.budget.record())
        author = host.budget.record()['production']['tasks'][row['authorTaskId']]['receipts'][0]
        plan = freeze_chunk_plan(host.request, row, host.budget.base / f"TEST-{row['sectionId']}-chunk-plan.json")
        binding = {**row['authorBinding'], 'role': 'encoded-review', 'authorTaskId': row['authorTaskId'],
                   'mediaManifest': None, 'chunkPlan': plan,
                   'inputs': unique_pins([*row['authorBinding']['inputs'], author, early_pin, plan])}
        spec = review_task(host.context, {**row, 'earlyTaskId': early.task_id}, binding)
        api.enqueue_tasks(host.budget.root, 'section-test', (spec,))
        return spec

    def task(self) -> dict:
        """Read current task through the closed production authority reader."""
        return self.host.budget.record()['production']['tasks'][self.ref.task_id]

    def scopes(self) -> list[dict]:
        """Read the actual planner-derived required chunks and neighboring edge."""
        return read_chunk_plan(self.spec.section_binding)[0]['scopes']

    def progress(self, index: int, current: dict | None = None) -> dict:
        """Create an explicitly synthetic judgment over exact current sealed scope media."""
        task, binding = self.task(), self.spec.section_binding
        scope_id = self.scopes()[index]['id']
        directory = claim_directory(task) / 'chunks'
        directory.mkdir(exist_ok=True)
        manifest = scope_manifest(binding, scope_id, directory / f'{scope_id}-media.json', current)
        review = {'status': 'pass', 'checks': dict.fromkeys(CHECKS, True),
                  'assessments': dict.fromkeys(CHECKS, 'TEST synthetic statement; no actual playback'),
                  'observations': scope_observations(binding, scope_id, manifest)}
        value = {'schemaVersion': 1, 'kind': 'native-long-section-chunk-result',
                 'taskId': self.ref.task_id, 'epoch': self.ref.epoch, 'token': self.ref.token,
                 'chunkPlan': binding['chunkPlan'], 'scopeId': scope_id, 'mediaManifest': manifest, 'review': review}
        file = directory / f'{scope_id}.json'
        write_new(file, value)
        return pin_file(file)

    def record(self, pin: dict) -> dict:
        """Use the locked nonterminal callback; never mutate authority fields directly."""
        return api.record_section_review_progress(self.host.budget.root, 'section-test', self.ref, pin)

    def final(self) -> dict:
        """Publish a fictional final judgment explicitly referencing every recorded scope."""
        task = self.task()
        progress = task.get('sectionProgress', {})
        pins = [progress[row['id']] for row in self.scopes() if row['id'] in progress]
        value = {'schemaVersion': 1, 'kind': 'native-long-section-result', 'taskId': self.ref.task_id,
                 'epoch': self.ref.epoch, 'token': self.ref.token, 'binding': self.spec.section_binding,
                 'artifacts': [], 'review': {'status': 'pass', 'progress': pins, 'globalJoins': None}}
        file = claim_directory(task) / 'result.json'
        write_new(file, value)
        return pin_file(file)
