"""Bounded installed-Node policy/projection parity; no provider or media process."""
from __future__ import annotations

import json
import os
from pathlib import Path
import shutil
import unittest

from guided_proposal_presenter import guided_presenter_policy, validate_requested_presenter
from headless.process_runner import ProcessRequest, run_text

_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = r"""
const {presenterFixture, presenterProposal, layoutOperation, layoutSelection} = require('./src/lib/server/__tests__/_guided-proposal-presenter-fixture.ts');
const {PRESENTER_RAW, oldOperation} = require('./src/lib/producer/__tests__/_presenter-layout-fixture.ts');
const {guidedPresenterPolicy, applyGuidedPresenterOperations} = require('./src/lib/server/guided-proposal-presenter.ts');
const {buildTreatmentCandidate} = require('./src/lib/server/guided-proposal-candidate.ts');
const {guidedCaptionPolicy, GUIDED_CAPTION_CONFIG_FILES} = require('./src/lib/server/guided-proposal-captions.ts');
const {guidedMusicPolicy} = require('./src/lib/server/guided-proposal-music.ts');
const cases = [];
function emit(name, change, full=false) {
  const f=presenterFixture(); change(f);
  f.policy=guidedPresenterPolicy(f.plan,f.manifest);
  f.evidence={...f.evidence,schemaVersion:8,presenterPolicy:f.policy};
  const candidate=full ? fullCandidate(f) : applyGuidedPresenterOperations(f);
  cases.push({name,accepted:f.plan,candidate,manifest:f.manifest,
    packet:{proposal:f.proposal,evidence:f.evidence,rawRequest:{rawIntent:PRESENTER_RAW}}});
}
function fullCandidate(f) {
  const evidence={...f.evidence,cleanEnds:[600],occurrences:[],catalog:[],timelineMapHash:'c'.repeat(64),
    introSeams:[],hookWindowS:60,graphicsAdvice:{'graphics_planner.py':{introSemanticBeats:[]}},
    captionPolicy:guidedCaptionPolicy(GUIDED_CAPTION_CONFIG_FILES.map(name=>({name,sha256:'d'.repeat(64)}))),
    musicPolicy:guidedMusicPolicy(f.plan,f.manifest)};
  const cut={plan:{value:f.plan},manifest:{value:f.manifest},job:{ctx:{intent:{scope:f.plan.target.scope,lanes:f.plan.target.lanes}}}};
  const result=buildTreatmentCandidate({cut,evidence,output:f.proposal,rawIntent:PRESENTER_RAW});
  if(result.blockers.length || !result.candidate) throw new Error(JSON.stringify(result.blockers));
  return result.candidate;
}
for(const kind of ['inset','bubble','split']) emit(kind,f=>{
  f.proposal=presenterProposal([layoutOperation({startAnchor:2,endAnchorExclusive:28,presenterLayout:layoutSelection(kind)})]);
});
emit('full-decorated-builder',()=>{},true);
emit('no-op',f=>{f.proposal=presenterProposal([oldOperation('preserve-cut')]);});
emit('video-offset',f=>{
  f.manifest.broll[0]={...f.manifest.broll[0],kind:'video',duration:9.125};
  f.proposal.operations[0].presenterLayout.assetStart={numerator:1,denominator:3};
});
emit('unsorted-original-indices',f=>{
  const selection={...layoutSelection(),sourceIds:['raw-2']};
  f.proposal=presenterProposal([layoutOperation({startAnchor:20,endAnchorExclusive:30,presenterLayout:selection}),
    oldOperation('preserve-cut'),layoutOperation({startAnchor:0,endAnchorExclusive:10,presenterLayout:selection})]);
});
emit('scope-default-null-lanes',f=>{f.plan.target.lanes=null;f.evidence.target.lanes=null;});
emit('authorable-upscale',f=>{
  f.proposal.operations[0].presenterLayout.presenterCrop={x:.3,y:.3,width:.4,height:.4};
  f.proposal.operations[0].presenterLayout.presenterRect={x:.2,y:.2,width:.5,height:.5};
  f.proposal.operations[0].presenterLayout.protectedPresenterRect={x:.4,y:.4,width:.2,height:.2};
});
emit('authorable-16k',f=>{
  f.plan.target.width=f.evidence.target.width=16384;f.plan.target.height=f.evidence.target.height=9216;
});
process.stdout.write(JSON.stringify(cases));
"""


class PresenterParityTests(unittest.TestCase):
    """TS is used only as an independent test oracle, never a production dependency."""

    def test_actual_ts_outputs_match_supported_python_policy_and_candidate(self) -> None:
        """Owned10s/2MiB Node invocation holds actual array indices and decorated target."""
        node = shutil.which("node")
        self.assertIsNotNone(node, "The installed local Node test runtime is required")
        result = run_text(ProcessRequest(command=(str(Path(node).resolve()), "--import", "tsx", "-e", _SCRIPT),
            stdin_text="", cwd=str(_ROOT), environment={**os.environ, "TSX_DISABLE_CACHE": "1"},
            timeout_seconds=10, max_output_bytes=2 * 1024 * 1024))
        self.assertEqual(result.returncode, 0, result.stderr)
        cases = json.loads(result.stdout)
        self.assertEqual(len(cases), 10)
        for case in cases:
            self.assertEqual(guided_presenter_policy(case["accepted"], case["manifest"]), case["packet"]["evidence"]["presenterPolicy"])
            self._candidate(case)

    def _candidate(self, case: dict) -> None:
        """Only the explicitly narrower execution policy rejects authorable examples."""
        rows = (case["accepted"], case["candidate"], case["packet"], case["manifest"])
        if case["name"].startswith("authorable-"):
            with self.subTest(case=case["name"]), self.assertRaises(ValueError):
                validate_requested_presenter(*rows)
            return
        with self.subTest(case=case["name"]):
            validated = validate_requested_presenter(*rows)
            self.assertEqual(list(validated.windows), case["candidate"].get("presenterLayouts", []))


if __name__ == "__main__":
    unittest.main()
