"""Real changed-author lineage and static locality; media and review statements are fictional."""
from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace

from _native_long_isolation_fixture import write_static_project
from _native_long_probe_fixture import synthetic_dependency_probe
from _native_review_package_fixture import install_test_packages
from _production_chunk_fixture import ChunkFixture
from cut_preview_io import write_new
from studio.native_export_history import register_attempt
from studio.native_long_chunk_evidence import chunk_geometry
from studio.native_long_chunks import bind_chunk_request
from studio.native_runtime import digest
from studio.native_segments.compatibility import prepare_long_repair, reuse_window
from studio.native_segments.long_plan import initial_long_plan
from studio.production import api
from studio.production.callbacks import TaskResult
from studio.production.section_plan import pin_file
from studio.production.sections import bind_section_tasks, enqueue_section_authors
from test_native_long_chunk_admission import ChunkAdmissionTests
from test_production_sections import ProductionSectionsTests

CANVAS = {'width': 320, 'height': 180, 'frameRate': '1/1', 'totalFrames': 180}


class ChangedChunkFixture:
    """One B author owns three chunks; its middle isolated mount changes in generation two."""

    def __init__(self, test: object, claim_review: bool = True) -> None:
        """Build actual authored chunk admission and a registered immutable original request."""
        self.host = ProductionSectionsTests()
        self.host.setUp()
        test.addCleanup(self.host.doCleanups)
        h, f = self.host, self.host.fixture
        self.write_project(f.project)
        h.request.update(revision=initial_long_plan(CANVAS, 'a' * 64, [0, 60, 120, 180]),
                         sectionImplementationPins={str(f.node): digest(f.node)})
        h.plan['assignments'] = [h.assignment('B', [0, 180], 'compositions/unit-4.html')]
        h.planfile = h.budget.base / 'three-chunks-one-author.json'
        write_new(h.planfile, h.plan)
        h.context = enqueue_section_authors(h.planfile)['sectionProduction']
        self.contract()
        self.project_pins(h.request, f.project)
        h.complete(h.context['assignments'][0]['authorTaskId'])
        bind_section_tasks(h.request, h.planfile)
        h.request['prebuildReview'] = {'status': 'recorded-independent-plan-pass',
                                      'scope': 'native-long-full-project'}
        bind_chunk_request(h.request)
        f.write_request(h.request)
        register_attempt(h.request)
        h.preview = h.make_previews()
        h.publish_previews()
        h.early()
        install_test_packages(test, h)
        for index in range(3):
            h.seal(index)
        self.review = ChunkFixture.__new__(ChunkFixture)
        self.review.host = h
        if claim_review:
            self.review.start()
        else:
            self.review.spec = self.review.enqueue()

    def write_project(self, project: Path, changed: bool = False) -> None:
        """Keep transition-adjacent mounts unchanged so cold dependency proof can be local."""
        texts = tuple('changed B2' if changed and index == 4 else f'original {index}' for index in range(9))
        write_static_project(project, CANVAS, texts)
        (project / 'LONG-PROJECT.json').write_text(json.dumps({'canvas': CANVAS, 'scenes': [
            {'startFrame': start, 'endFrame': start + 20} for start in range(0, 180, 20)]}))

    def contract(self) -> None:
        """Write explicit TEST transition decisions against the actual current scoped dependencies."""
        h = self.host
        fixture = SimpleNamespace(project=h.fixture.project, context=h.context,
                                  geometry=chunk_geometry(h.fixture.project, h.context))
        write_new(h.fixture.project / 'LONG-CHUNKS.json', ChunkAdmissionTests.authored_contract(fixture))

    def project_pins(self, request: dict, project: Path) -> None:
        """Refresh the unpublished project's complete actual inventory, retaining source/tool authority."""
        previous = Path(request['project'])
        request['pins'] = {path: sha for path, sha in request['pins'].items()
                           if not Path(path).is_relative_to(previous)}
        request['project'] = str(project)
        request['pins'].update({str(file): digest(file) for file in project.rglob('*') if file.is_file()})

    def record_original(self, complete: bool = True) -> None:
        """Record real immutable progress callbacks; optionally finish the old assigned reviewer."""
        for index in range(len(self.review.scopes())):
            self.review.record(self.review.progress(index))
        if complete:
            api.complete_task(self.host.budget.root, 'section-test', self.review.ref,
                              TaskResult((self.review.final(),)))

    def repair(self, windows: tuple[int, ...] = (0, 1, 2)) -> None:
        """Admit an immutable changed B snapshot and a real replacement author without transferring QC."""
        h, f = self.host, self.host.fixture
        self.original = copy.deepcopy(h.request)
        project = h.budget.base / 'changed-project'
        self.write_project(project, True)
        plan = copy.deepcopy(h.plan)
        plan['parentPlan'] = pin_file(h.planfile)
        plan['assignments'][0].update(generation=2, priorAuthorTaskId=h.context['assignments'][0]['authorTaskId'])
        h.planfile = h.budget.base / 'changed-assignments.json'
        write_new(h.planfile, plan)
        h.context = enqueue_section_authors(h.planfile)['sectionProduction']
        current = {**copy.deepcopy(h.request), 'output': str(h.budget.base / 'changed-attempt')}
        Path(current['output']).mkdir()
        f.project = project
        self.contract()
        self.project_pins(current, project)
        current = prepare_long_repair(current, Path(self.original['output']))
        h.request, f.request, f.root = current, current, Path(current['output'])
        h.complete(h.context['assignments'][0]['authorTaskId'])
        bind_section_tasks(current, h.planfile)
        bind_chunk_request(current)
        f.write_request(current)
        register_attempt(current)
        h.preview = h.make_previews()
        h.publish_previews()
        h.early()
        self.copy_owners()
        from _native_review_package_fixture import prepare_test_master, seal_test_package
        from studio.native_segments.review_scopes import package_scopes
        prepare_test_master(h)
        for index in windows:
            ProductionSectionsTests.seal(h, index)
        for scope in package_scopes(current):
            if all((f.root / f"segment-picture-{window['index']}-stage.json").exists() for window in scope['windows']):
                seal_test_package(h, scope)

    def copy_owners(self) -> None:
        """Unchanged chunks use actual donor copies and fresh seals; B2 receives changed fictional bytes."""
        f = self.host.fixture
        original = f.write_phase

        def write_phase(label: str, root: Path) -> None:
            """Only synthetic media generation is substituted, never source compatibility or seals."""
            index = int(label.rsplit('-', 1)[1])
            if index == 1:
                original(label, root)
                file = root / f'{label}.json'
                value = json.loads(file.read_text())
                Path(value['piece']['path']).write_bytes(b'TEST changed middle chunk picture')
                value['piece']['sha256'] = digest(Path(value['piece']['path']))
                value['piece']['sizeBytes'] = Path(value['piece']['path']).stat().st_size
                file.write_text(json.dumps(value))
                return
            value = reuse_window(f.request, label, root / f'{label}-copied')
            audio = root / f'{label}-TEST.wav'
            audio.write_bytes(f'TEST non-decodable section audio {index}'.encode())
            value['audio'] = {'path': str(audio), 'sha256': digest(audio), 'pcmSha256': digest(audio)}
            directory = root / f'{label}-probe'
            directory.mkdir()
            value['dependencyProbe'] = synthetic_dependency_probe(f.request, label, directory, value)
            (root / f'{label}.json').write_text(json.dumps(value))

        f.write_phase = write_phase
