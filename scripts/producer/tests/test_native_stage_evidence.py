"""Filesystem-only regressions for shared completed native stage evidence."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from studio import native_stage_evidence as stages
from studio.native_run_config import source_hashes
from studio.native_runtime import digest


def write_json(path: Path, value: dict) -> None:
    """Write tiny fixture receipts without media or child work."""
    path.write_text(json.dumps(value))


class NativeStageEvidenceTests(unittest.TestCase):
    """A stage seal never turns missing, stale, failed, or foreign work into success."""

    def setUp(self) -> None:
        """Retain one original native owner and its exact request/source closure."""
        self.base = Path(self.enterContext(tempfile.TemporaryDirectory(dir='/private/tmp')))
        self.project, self.root = self.base / 'project', self.base / 'original'
        self.project.mkdir()
        self.root.mkdir()
        self.source = self.base / 'original.mp4'
        self.source.write_bytes(b'TEST ONLY media bytes')
        (self.project / 'index.html').write_text('<div>TEST ONLY native composition</div>')
        (self.project / 'PROJECT.json').write_text('{"duration":600}')
        self.owner_code = self.base / 'owner.py'
        self.owner_code.write_text('TEST ONLY independent native owner')
        self.inputs = {str(file): digest(file) for file in [self.source, *self.project.iterdir()]}
        self.request_path, self.pipeline_path = self.root / 'request.json', self.root / 'render.json'
        self.request = {'project': str(self.project), 'output': str(self.root), 'pins': self.inputs}
        write_json(self.request_path, self.request)
        self.artifacts = {name: self.root / name for name in ('picture', 'review', 'audio', 'delivery')}
        for name, file in self.artifacts.items():
            file.write_bytes(f'TEST ONLY {name} artifact'.encode())
        pins = {**self.inputs, str(self.request_path): digest(self.request_path),
                str(self.owner_code): digest(self.owner_code)}
        self.pipeline = {'status': 'render-complete', 'exitCode': 0, 'project': str(self.project),
                         'output': str(self.artifacts['review']), 'pid': 101, 'abortReason': None,
                         'ownerIdentities': [{'pid': 101, 'pgid': 101, 'parent_pid': 100, 'started': 'now'}],
                         'cleanup': {'verified': True, 'survivors': []},
                         'sourceHashesBefore': source_hashes(self.project),
                         'sourceHashesAfter': source_hashes(self.project),
                         'additionalFilePinsBefore': pins, 'additionalFilePinsAfter': dict(pins),
                         **{name: True for name in stages.STABLE_FIELDS}}
        write_json(self.pipeline_path, self.pipeline)
        self.spec = stages.StageEvidence('render', self.project, self.root, self.request_path,
                                         self.pipeline_path, self.inputs, self.artifacts, 'render-complete')
        self.receipt = self.root / 'render-stage.json'

    def test_seal_binds_all_bytes_and_preserves_original_attempt(self) -> None:
        """The shared result contains enough pins for a new supervised verification."""
        before = {str(file): digest(file) for file in self.root.iterdir()}
        result = stages.seal_stage(self.spec)
        loaded, pins = stages.read_stage(self.receipt, self.inputs, 'render')
        self.assertEqual(loaded, result)
        required = {*before, *self.inputs, str(self.owner_code), str(self.receipt)}
        self.assertEqual(set(pins), required)
        self.assertEqual(before, {name: digest(Path(name)) for name in before})
        self.assertNotIn('humanApproved', result)
        with self.assertRaises(FileExistsError):
            stages.seal_stage(self.spec)

    def test_generic_stage_supports_long_form_without_a_short_canvas_contract(self) -> None:
        """A long adapter can provide its own stage label and artifact inventory."""
        spec = replace(self.spec, stage='long-picture')
        stages.seal_stage(spec)
        record, _pins = stages.read_stage(self.root / 'long-picture-stage.json', self.inputs, 'long-picture')
        self.assertEqual(record['stage'], 'long-picture')
        self.assertEqual(record['artifacts']['review']['sha256'], digest(self.artifacts['review']))

    def test_failed_unlaunched_aborted_or_partial_owner_never_gets_a_seal(self) -> None:
        """Neither a success label nor cleanup booleans can replace completed ownership."""
        changes = [{'status': 'failed'}, {'status': 'running'}, {'exitCode': 1}, {'exitCode': False},
                   {'exitCode': None}, {'abortReason': 'timed out'}, {'receiptOwnershipFailed': True},
                   {'pid': None}, {'pid': True}, {'ownerIdentities': []}, {'ownerIdentities': [{}]},
                   {'ownerIdentities': [{**self.pipeline['ownerIdentities'][0], 'pgid': 202}]},
                   {'ownerIdentities': self.pipeline['ownerIdentities'] * 2}]
        for change in changes:
            write_json(self.pipeline_path, {**self.pipeline, **change})
            with self.subTest(change=change), self.assertRaises(ValueError):
                stages.seal_stage(self.spec)
            self.assertFalse(self.receipt.exists())

    def test_every_cleanup_and_stability_field_is_mandatory(self) -> None:
        """A completed subprocess without independently verified cleanup is ineligible."""
        changes = [{key: False} for key in stages.STABLE_FIELDS]
        changes += [{'cleanup': {'verified': True, 'survivors': [101]}}, {'cleanup': None},
                    {'cleanup': {'verified': True}}, {'cleanup': {'survivors': []}}]
        for change in changes:
            write_json(self.pipeline_path, {**self.pipeline, **change})
            with self.subTest(change=change), self.assertRaises(ValueError):
                stages.seal_stage(self.spec)
            self.assertFalse(self.receipt.exists())

    def test_self_reported_stability_cannot_replace_exact_before_after_pins(self) -> None:
        """Detect altered pins even if every superficial status still says success."""
        changes = [{'additionalFilePinsAfter': {}}, {'sourceHashesAfter': {}},
                   {'additionalFilePinsBefore': self.inputs, 'additionalFilePinsAfter': self.inputs},
                   {'sourceHashesBefore': {}, 'sourceHashesAfter': {}}]
        for change in changes:
            write_json(self.pipeline_path, {**self.pipeline, **change})
            with self.subTest(change=change), self.assertRaises(ValueError):
                stages.seal_stage(self.spec)

    def test_changed_original_inputs_artifacts_receipts_and_owner_code_are_rejected(self) -> None:
        """All dependencies stay live bindings after a stage has been sealed."""
        stages.seal_stage(self.spec)
        files = [self.source, self.owner_code, self.project / 'index.html',
                 self.request_path, self.pipeline_path, *self.artifacts.values()]
        for file in files:
            original = file.read_bytes()
            file.write_bytes(original + b' changed')
            with self.subTest(path=file), self.assertRaises((ValueError, RuntimeError)):
                stages.read_stage(self.receipt, self.inputs, 'render')
            file.write_bytes(original)

    def test_missing_extra_or_changed_current_dependency_never_matches(self) -> None:
        """Map equality rejects additions as well as stale or removed dependencies."""
        stages.seal_stage(self.spec)
        variants = [{}, {str(self.source): self.inputs[str(self.source)]},
                    {**self.inputs, str(self.owner_code): digest(self.owner_code)},
                    {**self.inputs, str(self.source): 'a' * 64}]
        for current in variants:
            with self.subTest(current=current), self.assertRaises(ValueError):
                stages.read_stage(self.receipt, current, 'render')

    def test_new_authored_file_invalidates_current_source_closure(self) -> None:
        """A stale current-input collector cannot hide an additional authored source."""
        stages.seal_stage(self.spec)
        (self.project / 'new.js').write_text('changed source inventory')
        with self.assertRaisesRegex(ValueError, 'authored project'):
            stages.read_stage(self.receipt, self.inputs, 'render')

    def test_request_project_output_and_input_must_match_exact_stage(self) -> None:
        """A caller cannot select another project or borrow a subset of its pins."""
        variants = [replace(self.spec, inputs={str(self.source): self.inputs[str(self.source)]}),
                    replace(self.spec, project=self.base),
                    replace(self.spec, artifacts={'picture': self.artifacts['picture']})]
        for spec in variants:
            with self.subTest(spec=spec), self.assertRaises(ValueError):
                stages.seal_stage(spec)

    def test_artifact_and_receipt_symlinks_hardlinks_or_escape_are_rejected(self) -> None:
        """Path names cannot substitute files outside original owned evidence."""
        target = self.artifacts['review']
        original = target.read_bytes()
        target.unlink()
        target.symlink_to(self.source)
        with self.assertRaises((ValueError, RuntimeError, OSError)):
            stages.seal_stage(self.spec)
        target.unlink()
        os.link(self.source, target)
        with self.assertRaises((ValueError, RuntimeError)):
            stages.seal_stage(self.spec)
        target.unlink()
        target.write_bytes(original)
        with self.assertRaisesRegex(ValueError, 'escaping'):
            stages.seal_stage(replace(self.spec, artifacts={'review': self.source}))
        stages.seal_stage(self.spec)
        link = self.base / 'linked-stage.json'
        link.symlink_to(self.receipt)
        with self.assertRaises((ValueError, RuntimeError, OSError)):
            stages.read_stage(link, self.inputs, 'render')

    def test_symlinked_ancestor_is_rejected_even_if_it_resolves_to_valid_evidence(self) -> None:
        """Canonical evidence cannot enter through an alternate linked directory."""
        stages.seal_stage(self.spec)
        linked = self.base / 'linked'
        linked.symlink_to(self.root, target_is_directory=True)
        with self.assertRaisesRegex(RuntimeError, 'canonical'):
            stages.read_stage(linked / self.receipt.name, self.inputs, 'render')

    def test_missing_empty_malformed_or_oversized_receipt_is_rejected(self) -> None:
        """Untrusted local JSON is size-bounded before parsing."""
        with self.assertRaises(FileNotFoundError):
            stages.read_stage(self.receipt, self.inputs, 'render')
        for content in ('', 'null', '[]', '{broken', '{}'):
            self.receipt.write_text(content)
            with self.subTest(content=content), self.assertRaises((ValueError, RuntimeError)):
                stages.read_stage(self.receipt, self.inputs, 'render')
        with self.receipt.open('wb') as handle:
            handle.truncate(stages.MAX_JSON + 1)
        with self.assertRaisesRegex(RuntimeError, 'budget'):
            stages.read_stage(self.receipt, self.inputs, 'render')

    def test_wrong_stage_unknown_schema_and_modified_bindings_are_rejected(self) -> None:
        """No defaults or unchecked fields can restore a broken evidence chain."""
        original = stages.seal_stage(self.spec)
        with self.assertRaisesRegex(ValueError, 'another stage'):
            stages.read_stage(self.receipt, self.inputs, 'verification')
        variants = [{**original, 'schemaVersion': True}, {**original, 'unknown': 'ignored?'},
                    {**original, 'successStatus': 'failed'},
                    {**original, 'supervisorPins': self.inputs},
                    {**original, 'artifacts': {'review': {'path': str(self.artifacts['review']), 'sha256': 'a' * 64}}}]
        for record in variants:
            write_json(self.receipt, record)
            with self.subTest(record=record), self.assertRaises(ValueError):
                stages.read_stage(self.receipt, self.inputs, 'render')

    def test_changed_bytes_during_sealing_prevent_a_qualifying_record(self) -> None:
        """A mid-validation mutation cannot become accepted by a cached hash."""
        original = stages.verify_pins

        def mutate_then_verify(pins: dict[str, str]) -> None:
            """Simulate source drift after records have been inspected."""
            self.source.write_bytes(b'changed source during admission')
            original(pins)

        with patch.object(stages, 'verify_pins', side_effect=mutate_then_verify):
            with self.assertRaisesRegex(ValueError, 'changed input'):
                stages.seal_stage(self.spec)
        self.assertFalse(self.receipt.exists())

    def test_oversized_original_receipts_fail_before_hashing_or_sealing(self) -> None:
        """Large-source allowances never allow giant JSON metadata to be scanned."""
        original = self.pipeline_path.read_bytes()
        for path in (self.pipeline_path, self.request_path):
            with path.open('wb') as handle:
                handle.truncate(stages.MAX_JSON + 1)
            with self.subTest(path=path), self.assertRaisesRegex(RuntimeError, 'budget'):
                stages.seal_stage(self.spec)
            self.assertFalse(self.receipt.exists())
            self.pipeline_path.write_bytes(original)

    def test_missing_or_empty_retained_artifact_invalidates_sealed_work(self) -> None:
        """A surviving seal cannot replace deleted or truncated media."""
        stages.seal_stage(self.spec)
        self.artifacts['review'].unlink()
        with self.assertRaises(FileNotFoundError):
            stages.read_stage(self.receipt, self.inputs, 'render')
        self.artifacts['review'].touch()
        with self.assertRaisesRegex(RuntimeError, 'unsafe'):
            stages.read_stage(self.receipt, self.inputs, 'render')

    def test_native_hashing_uses_a_streaming_limit_above_large_long_form_sources(self) -> None:
        """The shared utility does not inherit preview-only media size restrictions."""
        with patch.object(stages, 'file_hash', return_value='a' * 64) as hash_file:
            self.assertEqual(stages._hash(self.source), 'a' * 64)
        hash_file.assert_called_once_with(self.source, maximum=stages.MAX_NATIVE_FILE_BYTES)
        self.assertGreater(stages.MAX_NATIVE_FILE_BYTES, 2 * 1024 ** 3)


if __name__ == '__main__':
    unittest.main(verbosity=2)
