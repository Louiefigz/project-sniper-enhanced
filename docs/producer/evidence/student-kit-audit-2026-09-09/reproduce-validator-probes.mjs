/** Text-only audit probes. Run with the pinned student-kit checkout as argument.
 * Imports only the two inspected pure validators. Does not render or open media.
 */
import { writeFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { pathToFileURL } from 'node:url';
import { execFileSync } from 'node:child_process';

const sourceCommit = 'b1afdb1dcbcad39dd27638ea699f132fe44ce6df';
const source = resolve(process.argv[2] ?? '/private/tmp/sniper-student-kit-audit-20260909');
const output = resolve(process.argv[3] ?? '/private/tmp/sniper-student-kit-validator-probes.json');
const actualCommit = execFileSync('git', ['rev-parse', 'HEAD'], { cwd: source, encoding: 'utf8' }).trim();
if (actualCommit !== sourceCommit) throw new Error('Audit source commit differs');
const helpers = join(source, '.agents/skills/short-form-edit/scripts');
const { validatePlan } = await import(pathToFileURL(join(helpers, 'validate-plan.mjs')).href);
const { validateFootage } = await import(pathToFileURL(join(helpers, 'validate-footage.mjs')).href);
const word = { text: 'Hello', start: .1, end: .3, sourceStart: 10.1, sourceEnd: 10.3 };
const base = {
  plan: {
    duration: 1, fps: 30,
    scenes: [{ id: 's0', start: 0, end: 1, layout: 'face', anchor: 'Hello', anchorTime: .1 }],
    captions: [{ start: .1, end: .3, words: [{ text: 'Hello', start: .1, end: .3 }] }],
    events: [{ time: 0, visual: 's0' }],
  },
  transcript: { words: [word] },
  edl: { keeps: [{ sourceStart: 10, sourceEnd: 11, start: 0, end: 1 }] },
};
const cases = [];
/** Compare a single altered input against the acceptance required by Sniper. */
function probe(name, mutate, shouldPass = false) {
  const value = structuredClone(base);
  mutate(value);
  const result = validatePlan(value.plan, value.transcript, value.edl);
  cases.push({ name, shouldPass, actualPass: result.ok, errors: result.errors });
}
probe('valid_control', () => {}, true);
probe('missing_program_duration', ({ plan }) => { delete plan.duration; });
probe('missing_scene_end', ({ plan }) => { delete plan.scenes[0].end; });
probe('fabricated_anchor_phrase', ({ plan }) => { plan.scenes[0].anchor = 'This was never spoken'; });
probe('unquantized_scene_end', ({ plan }) => { plan.duration = 1.01; plan.scenes[0].end = 1.01; });
probe('changed_word_end_source_mapping', ({ transcript }) => { transcript.words[0].sourceEnd = 10.7; });
probe('missing_caption_word', ({ plan }) => { plan.captions = []; });
probe('shifted_caption_word', ({ plan }) => { plan.captions[0].words[0].start = .2; });
const footage = validateFootage([{
  scene: 's0', sourceSceneId: 'source-scene-1', sha256: 'a'.repeat(64),
  sourceStart: 0, sourceEnd: JSON.parse('1e400'),
}]);
cases.push({ name: 'footage_infinite_end', shouldPass: false, actualPass: footage.ok, errors: footage.errors });
const result = {
  node: process.version, sourceCommit,
  scope: 'Text-only validator counterexamples; no media, browser, network or installed dependencies',
  cases,
};
writeFileSync(output, JSON.stringify(result, null, 2) + '\n');
console.log(JSON.stringify({ output, cases: cases.length, mismatches: cases.filter(c => c.shouldPass !== c.actualPass).length }));
