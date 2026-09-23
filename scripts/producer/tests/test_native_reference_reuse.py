"""Opt-in native mapping integration; inert evidence, no media execution."""
from __future__ import annotations

from argparse import Namespace
from pathlib import Path
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from _native_short_pipeline_fixture import ShortPipelineFixture
from _native_current_source_fixture import bind_test_project_sources
from _reference_reuse_fixture import ReuseFixture
from cut_preview_io import file_hash
from studio import native_preflight as preflight
from studio import native_reference_reuse as native
from studio.native_short_export import prepare
from studio.native_short_resume import prepare_reverification
from studio.native_long_prebuild import prebuild_snapshot


class NativeReferenceReuseTests(ReuseFixture):
    """Shared native checks only read a map the caller explicitly supplied."""

    def setUp(self) -> None:
        """Keep the real discovery/core on test-owned files and replace no validator."""
        super().setUp()
        self.project = Path(self.body['project'])
        self.project.mkdir()
        (self.project / 'index.html').write_text('<p>TEST ONLY inert native source</p>')
        bind_test_project_sources(self.project)
        self.mapping = self.root / 'reuse-map.json'
        self.sdk_calls = 0
        self.sdk_change = None
        self.enterContext(patch.object(native, 'load_catalog', side_effect=self.catalog))

    def publish(self, record: dict | None = None) -> Path:
        """Save a completed test-authored map as external planning evidence."""
        self.write_json(self.mapping, self.decided() if record is None else record)
        return self.mapping

    def request_to_bind(self) -> dict:
        """Use a real source pin in an otherwise tiny native request."""
        source = self.project / 'index.html'
        return {'project': str(self.project), 'pins': {str(source): file_hash(source)}}

    def sdk_result(self, project: Path, output: Path, original: dict, end: float) -> tuple:
        """Stub only SDK execution while retaining native completion/pin checks."""
        self.sdk_calls += 1
        request = output / 'request.json'
        self.write_json(request, {'TEST': 'inert SDK request, no execution'})
        if self.sdk_change:
            self.sdk_change()
        return ({'blocked': False, 'requestSha256': file_hash(request)},
                preflight.lint._identity(request))

    def run_preflight(self, mapping: Path | None, name: str = 'preflight') -> dict:
        """Exercise actual before/after integration with no SDK, browser or tools."""
        with patch.object(preflight, '_tools', return_value={'TEST': 'fixed tool pins'}), \
                patch.object(preflight, '_execute', side_effect=self.sdk_result):
            return preflight.preflight(self.project, self.root / name, mapping)

    def export_fixture(self) -> ShortPipelineFixture:
        """Prepare existing TEST source/runtime boundaries without launching them."""
        base = self.root / 'media-fixture'
        base.mkdir()
        return ShortPipelineFixture(base)

    def export_prepare(self, fixture: ShortPipelineFixture, args: Namespace) -> tuple:
        """Run export admission with only external tool/SDK preparation substituted."""
        with patch('studio.native_short_export.local_environment',
                   return_value=(fixture.request['tools'], {})), \
                patch('studio.native_short_export.subprocess.run',
                      side_effect=lambda *args, **kwargs: self.sdk_change() if self.sdk_change else None), \
                patch('studio.native_short_export.install_runtime', return_value=fixture.runtime), \
                patch('studio.native_short_export.input_pins', return_value=dict(fixture.inputs)):
            return prepare(args)

    def test_absent_map_does_not_load_catalog_or_change_request(self) -> None:
        """Normal native edits require no new reference planning artifact."""
        request = self.request_to_bind()
        with patch.object(native, 'load_catalog') as catalog:
            self.assertIs(native.bind_reference_map(request, None), request)
            self.assertIsNone(native.reference_snapshot(self.project, None))
        catalog.assert_not_called()
        self.assertNotIn('referenceMap', request)

    def test_bound_map_exports_reference_plan_and_candidate_source_pins(self) -> None:
        """Export supervision retains every dependency plus the exact map bytes."""
        record = self.decided()
        request = self.request_to_bind()
        bound = native.bind_reference_map(request, self.publish(record))
        self.assertNotIn('referenceMap', request)
        self.assertEqual(bound['referenceMap'], str(self.mapping))
        self.assertEqual(bound['pins'][str(self.mapping)], file_hash(self.mapping))
        for path, sha in record['inputPins'].items():
            self.assertEqual(bound['pins'][path], sha)
        self.assertEqual(bound['pins'][str(self.reference)], file_hash(self.reference))
        self.assertIn(str(self.plan), bound['pins'])
        self.assertIn(str(self.sources / 'meter-card.html'), bound['pins'])

    def test_long_declaration_binds_reference_review_and_rejects_stale_evidence(self) -> None:
        """Long review hashes include declared map dependencies without another export flag."""
        self.body['format'] = 'longform'
        self.publish()
        self.write_json(self.project / 'LONG-PROJECT.json', {'referenceMap': str(self.mapping)})
        reviewed = prebuild_snapshot(self.project)
        self.assertEqual(reviewed['referenceMap'], str(self.mapping))
        self.assertEqual(reviewed['pins'][str(self.reference)], file_hash(self.reference))
        record = self.decided(); record['shots'][0]['decision']['reason'] = 'TEST revised valid decision'
        self.publish(record)
        self.assertNotEqual(prebuild_snapshot(self.project)['planHash'], reviewed['planHash'])
        self.reference.write_text('TEST stale reference')
        with self.assertRaisesRegex(ValueError, 'stale pinned file'):
            prebuild_snapshot(self.project)

    def test_wrong_project_and_longform_map_cannot_bind_short_export(self) -> None:
        """Format/project identity remains independent of a valid planning verdict."""
        self.publish()
        request = {**self.request_to_bind(), 'project': str(self.root / 'other-project')}
        with self.assertRaisesRegex(ValueError, 'different native project'):
            native.bind_reference_map(request, self.mapping)
        self.body['format'] = 'longform'
        self.publish()
        with self.assertRaisesRegex(ValueError, '[Ss]hort reference map'):
            native.bind_reference_map(self.request_to_bind(), self.mapping)

    def test_bound_map_rejects_conflicting_already_admitted_pins(self) -> None:
        """Mapping evidence cannot overwrite an earlier contradictory input admission."""
        request = self.request_to_bind()
        request['pins'][str(self.reference)] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'conflict'):
            native.bind_reference_map(request, self.publish())
        self.assertEqual(request['pins'][str(self.reference)], '0' * 64)

    def test_longform_map_short_admission_refuses_before_tool_preparation(self) -> None:
        """A valid Long map stays valid for Long without entering Short tooling."""
        fixture = self.export_fixture()
        self.body.update(project=str(fixture.project), format='longform')
        args = fixture.options(reference_map=self.publish())
        with patch('studio.native_short_export.local_environment') as tools, \
                self.assertRaisesRegex(ValueError, 'short reference map'):
            prepare(args)
        tools.assert_not_called()

    def test_invalid_map_short_admission_refuses_before_tool_preparation(self) -> None:
        """A stale or foreign map cannot trigger native SDK or tool preparation."""
        fixture = self.export_fixture()
        args = fixture.options(reference_map=self.publish())
        with patch('studio.native_short_export.local_environment') as tools, \
                self.assertRaisesRegex(ValueError, 'different native project'):
            prepare(args)
        tools.assert_not_called()
        self.body['project'] = str(fixture.project)
        self.publish()
        self.reference.write_text('TEST stale reference before preparation')
        with patch('studio.native_short_export.local_environment') as tools, \
                self.assertRaisesRegex(ValueError, 'stale pinned file'):
            prepare(args)
        tools.assert_not_called()
        self.assertFalse(args.output.exists())

    def test_normal_short_preparation_does_not_load_catalog_or_require_map(self) -> None:
        """No supplied flag keeps the standard request free of reference metadata."""
        fixture = self.export_fixture()
        with patch.object(native, 'load_catalog') as catalog:
            request, environment = self.export_prepare(fixture, fixture.options())
        catalog.assert_not_called()
        self.assertNotIn('referenceMap', request)
        self.assertEqual(request['pins'], fixture.inputs)
        self.assertEqual(environment, {})

    def test_short_preparation_rechecks_map_after_external_tool_preparation(self) -> None:
        """Changing a reference during preparation cannot publish an export attempt."""
        fixture = self.export_fixture()
        self.body['project'] = str(fixture.project)
        args = fixture.options(reference_map=self.publish())
        self.sdk_change = lambda: self.reference.write_text('TEST reference changed while preparing')
        with self.assertRaisesRegex(ValueError, 'stale pinned file'):
            self.export_prepare(fixture, args)
        self.assertFalse(args.output.exists())

    def test_short_preparation_retains_valid_explicit_map_dependency_pins(self) -> None:
        """The actual exporter stores map/source/reference pins before creating output."""
        fixture = self.export_fixture()
        self.body['project'] = str(fixture.project)
        args = fixture.options(reference_map=self.publish())
        request, _ = self.export_prepare(fixture, args)
        self.assertEqual(request['referenceMap'], str(self.mapping))
        self.assertEqual(request['pins'][str(self.reference)], file_hash(self.reference))
        self.assertEqual(request['pins'][str(self.mapping)], file_hash(self.mapping))
        self.assertTrue(args.output.is_dir())

    def test_blocked_map_is_refused_before_sdk(self) -> None:
        """A documented missing adapter is not execution readiness."""
        record = self.decided()
        decision = record['shots'][0]['decision']
        decision['route'] = 'blocked'
        decision['execution']['status'] = 'unavailable'
        decision['prerequisites'] = [{'kind': 'adapter', 'detail': 'TEST missing integration'}]
        with self.assertRaisesRegex(ValueError, 'unresolved prerequisites'):
            self.run_preflight(self.publish(record))
        self.assertEqual(self.sdk_calls, 0)
        self.assertTrue((self.root / 'preflight/failure.json').exists())

    def test_wrong_project_is_refused_before_sdk(self) -> None:
        """A map prepared for a different native project cannot qualify this one."""
        self.body['project'] = str(self.root / 'another-project')
        with self.assertRaisesRegex(ValueError, 'different native project'):
            self.run_preflight(self.publish())
        self.assertEqual(self.sdk_calls, 0)

    def test_stale_reference_is_refused_before_sdk(self) -> None:
        """Retained text/source evidence must still match the prepared map."""
        self.publish()
        self.reference.write_text('TEST changed reference')
        with self.assertRaisesRegex(ValueError, 'stale pinned file'):
            self.run_preflight(self.mapping)
        self.assertEqual(self.sdk_calls, 0)

    def test_both_formats_use_the_shared_preflight_with_no_quality_claim(self) -> None:
        """The same optional static integration supports Short and Long projects."""
        for form in ('short', 'longform'):
            self.body['format'] = form
            report = self.run_preflight(self.publish(), form)
            self.assertEqual(report['referenceMatch']['report']['format'], form)
            self.assertEqual(report['status'], 'static-checks-pass')
            self.assertFalse(report['renderApproved'])
            self.assertFalse(report['qualityApproved'])
        self.assertEqual(self.sdk_calls, 2)

    def test_no_map_preflight_never_loads_catalog(self) -> None:
        """Ordinary edit execution keeps mapping absent, even with a nearby map."""
        self.publish()
        with patch.object(native, 'load_catalog') as catalog:
            report = self.run_preflight(None)
        catalog.assert_not_called()
        self.assertIsNone(report.get('referenceMatch'))
        self.assertEqual(self.sdk_calls, 1)

    def test_reference_changed_during_sdk_invalidates_completion(self) -> None:
        """The external evidence is rechecked after the expensive boundary."""
        self.sdk_change = lambda: self.reference.write_text('TEST changed during SDK')
        with self.assertRaisesRegex(ValueError, 'stale pinned file'):
            self.run_preflight(self.publish())
        self.assertEqual(self.sdk_calls, 1)
        self.assertFalse((self.root / 'preflight/completion.json').exists())
        with self.assertRaisesRegex(RuntimeError, 'failure marker'):
            preflight.read_completed(self.root / 'preflight')

    def test_valid_map_rewrite_during_sdk_invalidates_original_snapshot(self) -> None:
        """Even a structurally valid revised explanation changes this attempt's input."""
        record = self.decided()
        self.publish(record)
        record['shots'][0]['decision']['reason'] = 'TEST revised explanation'
        self.sdk_change = lambda: self.write_json(self.mapping, record)
        with self.assertRaisesRegex(RuntimeError, 'changed during native preflight'):
            self.run_preflight(self.mapping)
        self.assertFalse((self.root / 'preflight/completion.json').exists())

    def test_resume_rebinds_the_original_map_and_rejects_changed_reference(self) -> None:
        """Verification inherits sealed planning dependencies without a new choice."""
        base = self.root / 'media-fixture'
        base.mkdir()
        fixture = ShortPipelineFixture(base)
        self.body['project'] = str(fixture.project)
        original_pins = dict(fixture.inputs)
        fixture.request = native.bind_reference_map(fixture.request, self.publish())
        fixture.inputs = fixture.request['pins']
        fixture.write_request(fixture.request)
        receipt = fixture.seal()
        current = {**fixture.current(), 'pins': original_pins}
        current.pop('referenceMap')
        resumed = prepare_reverification(current, receipt)
        self.assertEqual(resumed['referenceMap'], str(self.mapping))
        self.assertEqual(resumed['renderInputs'], fixture.inputs)
        self.reference.write_text('TEST reference changed after media seal')
        with self.assertRaisesRegex(ValueError, 'stale pinned file'):
            prepare_reverification(current, receipt)

    def test_resume_map_option_conflict_refuses_before_tool_preparation(self) -> None:
        """A fresh CLI flag cannot replace the original sealed reference decision."""
        base = self.root / 'media-fixture'
        base.mkdir()
        fixture = ShortPipelineFixture(base)
        args = fixture.options(verify_from=fixture.root / 'render-stage.json',
                               reference_map=self.mapping)
        with patch('studio.native_short_export.local_environment') as tools, \
                self.assertRaisesRegex(ValueError, 'original reference map'):
            prepare(args)
        tools.assert_not_called()


if __name__ == '__main__':
    import unittest
    unittest.main()
