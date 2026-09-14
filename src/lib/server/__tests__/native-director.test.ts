/** Real canonical-library retrieval and failure boundaries; provider judgment is explicitly stubbed. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import os from "node:os";
import { loadDirectorCatalog, catalogFromSources, directorCatalogHash } from "../native-director-library";
import { validateDirectorPlan } from "../native-director-validation";
import { stageNativeDirector, readNativeDirector, assertDirectorSource } from "../native-director-store";
import type { ProposalEvidence } from "../guided-proposal-evidence";
import { testDirectorPlan, nativeDirectorTestBrain, directorSourceFixture } from "./_native-director-fixture";

test("Director reads all canonical sources, including solution-aware training absent from the old index", () => {
  const catalog = loadDirectorCatalog();
  assert.equal(catalog.formats.length, 11); assert.equal(catalog.anchors.length, 190);
  assert.equal(catalog.examples.length, 326); assert.equal(catalog.examples.filter((row) => row.formula).length, 234);
  assert.ok(catalog.examples.find((row) => row.id === "T003")?.content.includes("Output:"));
  assert.equal(directorCatalogHash(catalogFromSources(catalog.sources)), directorCatalogHash(catalog));
  const changed = structuredClone(catalog.sources); changed[0].content += "changed";
  assert.throws(() => catalogFromSources(changed), /source bytes changed/);
  assert.throws(() => loadDirectorCatalog("/definitely-missing-director-library"));
});

test("Director rejects missing templates, copied/unbound slots, invented speech and failed hooks", () => {
  const input = directorSourceFixture(), catalog = loadDirectorCatalog(), good = testDirectorPlan(input, catalog);
  assert.deepEqual(validateDirectorPlan(good, catalog, input), good);
  const cases: Array<[(plan: typeof good) => void, RegExp]> = [
    [(plan) => { plan.format.id = "invented"; }, /format choices/],
    [(plan) => { plan.template.anchor = "invented"; }, /does not resolve/],
    [(plan) => { plan.template.referenceId = "R999"; }, /does not resolve/],
    [(plan) => { plan.template.slots = []; }, /every source-template slot/],
    [(plan) => { plan.template.slots[0].quote = "Made up"; }, /exact contiguous/],
    [(plan) => { plan.fills[0].writtenHook = "Business owners: Do you ever"; }, /copied reference wording/],
    [(plan) => { plan.spokenOpening = { occurrenceIds: [1], quote: "clear" }; }, /recorded first words/],
    [(plan) => { plan.fills[0].audit.clarity.pass = false; }, /failed its condition/],
    [(plan) => { plan.fills[0].audit.relevance.quote = "absent"; }, /absent opening evidence/],
    [(plan) => { plan.fills[1] = plan.fills[0]; }, /distinct concise/],
    [(plan) => { plan.visual.exitFrame = input.totalFrames + 1; }, /lifetime/],
  ];
  for (const [change, pattern] of cases) {
    const plan = structuredClone(good); change(plan); assert.throws(() => validateDirectorPlan(plan, catalog, input), pattern);
  }
});

test("Director author and critic precede a cold-readable bound decision; tampering invalidates it", async () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-director-"))), source = directorSourceFixture();
  const evidence = source as unknown as ProposalEvidence, phases: string[] = [];
  try {
    const record = await stageNativeDirector({ directory, evidence, rawIntent: source.rawIntent, remainingMs: () => 1000,
      brain: async (request) => { phases.push(request.phase); return nativeDirectorTestBrain(request); } });
    assert.deepEqual(phases, ["author", "critic"]); assert.deepEqual(readNativeDirector(directory), record);
    assertDirectorSource(record, source.rawIntent, evidence);
    assert.throws(() => assertDirectorSource(record, "changed intent", evidence), /different source/);
    const filename = path.join(directory, "native-director/author-result.json"), bytes = readFileSync(filename);
    const changed = JSON.parse(bytes.toString()); changed.output.fills[0].writtenHook = "New Hook";
    writeFileSync(filename, JSON.stringify(changed)); assert.throws(() => readNativeDirector(directory), /absent opening evidence|prompt differs/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("Director permits benefit/timeframe hooks while retaining length and line limits", () => {
  const input = directorSourceFixture(), catalog = loadDirectorCatalog();
  const plan = testDirectorPlan(input, catalog);
  const setHook = (text: string) => {
    plan.fills[0].writtenHook = text;
    for (const audit of Object.values(plan.fills[0].audit)) audit.quote = text;
  };
  for (const text of ["Use this offer formula\nto get more buyers",
    "Who else wants $1K/mo\nin their first 30 days?"]) {
    setHook(text);
    assert.deepEqual(validateDirectorPlan(plan, catalog, input), plan);
  }
  setHook("one two three four five six seven eight nine ten eleven twelve thirteen");
  assert.throws(() => validateDirectorPlan(plan, catalog, input), /12 words\/two lines/);
  setHook("One\ntwo\nthree");
  assert.throws(() => validateDirectorPlan(plan, catalog, input), /12 words\/two lines/);
});

test("failed independent critique retains the attempt and prevents a completed Director record", async () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-director-reject-"))), source = directorSourceFixture();
  try {
    await assert.rejects(stageNativeDirector({ directory, evidence: source as unknown as ProposalEvidence,
      rawIntent: source.rawIntent, remainingMs: () => 1000, brain: async (request) => {
        const result = await nativeDirectorTestBrain(request);
        if (request.phase === "critic") Object.assign(result.output, { verdict: "revise", findings: ["TEST topic label lacks a viewer payoff."] });
        return result;
      } }), /critique blocked native assembly/);
    assert.ok(existsSync(path.join(directory, "native-director/critic-result.json")));
    assert.equal(existsSync(path.join(directory, "native-director/record.json")), false);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});
