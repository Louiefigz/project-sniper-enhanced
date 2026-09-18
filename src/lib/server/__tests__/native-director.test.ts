/** Real canonical-library retrieval and failure boundaries; provider judgment is explicitly stubbed. */
import assert from "node:assert/strict";
import { test } from "node:test";
import { existsSync, mkdtempSync, readFileSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import path from "node:path";
import os from "node:os";
import { loadDirectorCatalog, catalogFromSources, directorCatalogHash } from "../native-director-library";
import { validateDirectorPlan, validateStoredDirectorPlan } from "../native-director-validation";
import { stageNativeDirector, readNativeDirector, assertDirectorSource } from "../native-director-store";
import { buildDirectorPrompt } from "../native-director-prompt";
import { DIRECTOR_CRITERIA, DIRECTOR_VIEWER_START, parseNativeDirectorPlan } from "@/lib/producer/contracts/native-director-v2";
import type { ProposalEvidence } from "../guided-proposal-evidence";
import { testDirectorPlan, testLegacyDirectorPlan, nativeDirectorTestBrain, directorSourceFixture } from "./_native-director-fixture";

test("Director reads all six packaged sources, including solution-aware training", () => {
  const catalog = loadDirectorCatalog();
  // Exact counts of the packaged original library (resources/director/README.md); a change to the
  // library must change these deliberately.
  assert.equal(catalog.formats.length, 10); assert.equal(catalog.anchors.length, 40);
  assert.equal(catalog.examples.length, 37); assert.equal(catalog.examples.filter((row) => row.formula).length, 29);
  assert.equal(new Set(catalog.anchors.map((row) => row.category)).size, 10);
  assert.ok(catalog.examples.some((row) => row.id.startsWith("T") && Number(row.id.slice(1)) >= 707),
    "solution-aware training pairs are loaded");
  assert.ok(catalog.examples.find((row) => row.id === "T703")?.content.includes("Output:"));
  assert.equal(directorCatalogHash(catalogFromSources(catalog.sources)), directorCatalogHash(catalog));
  const changed = structuredClone(catalog.sources); changed[0].content += "changed";
  assert.throws(() => catalogFromSources(changed), /source bytes changed/);
  assert.throws(() => loadDirectorCatalog("/definitely-missing-director-library"));
});

test("every anchor and format an example names resolves, and every formula has slots", () => {
  const catalog = loadDirectorCatalog(), anchors = new Set(catalog.anchors.map((row) => row.id));
  const formats = new Set(catalog.formats.map((row) => row.id));
  for (const example of catalog.examples) {
    const named = [...example.content.matchAll(/`([a-z][a-z0-9_-]+)`/gu)].map((match) => match[1]);
    assert.ok(named.length, `${example.id} names its anchor and format`);
    for (const id of named) assert.ok(anchors.has(id) || formats.has(id), `${example.id} names unknown ${id}`);
    if (example.id.startsWith("R")) assert.ok(example.formula && example.slots.length, `${example.id} has a slot formula`);
  }
  assert.match(catalog.anchors.find((row) => row.id === "steps-toward-goal")!.template, / \(in \[timeframe\]\)"$/u);
});

test("the v2 output schema carries exactly the contract's criteria and viewer levels", () => {
  const schema = JSON.parse(readFileSync(path.join(process.cwd(), "schemas/producer/native-director-v2.schema.json"), "utf8"));
  assert.equal(schema.properties.schemaVersion.const, 2);
  const audit = schema.properties.fills.items.properties.audit;
  assert.deepEqual(audit.required, [...DIRECTOR_CRITERIA]); assert.deepEqual(Object.keys(audit.properties), [...DIRECTOR_CRITERIA]);
  assert.deepEqual(schema.properties.awareness.properties.level.enum, [...DIRECTOR_VIEWER_START]);
  const prompt = buildDirectorPrompt(directorSourceFixture(), loadDirectorCatalog());
  for (const key of DIRECTOR_CRITERIA) assert.ok(prompt.includes(`- ${key}: `), `prompt defines ${key}`);
  assert.match(prompt, /Director plan schema version 2/u);
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
    [(plan) => { plan.fills[0].writtenHook = "a chain that stops squeaking"; }, /copied reference wording/],
    [(plan) => { plan.spokenOpening = { occurrenceIds: [1], quote: "clear" }; }, /recorded first words/],
    [(plan) => { plan.fills[0].audit.glanceReadable.pass = false; }, /failed its criteria audit/],
    [(plan) => { plan.fills[0].audit.supportedClaim.pass = false; }, /failed its criteria audit/],
    [(plan) => { plan.fills[0].audit.viewerStake.quote = "absent"; }, /absent opening evidence/],
    [(plan) => { plan.fills[1] = plan.fills[0]; }, /distinct concise/],
    [(plan) => { plan.visual.exitFrame = input.totalFrames + 1; }, /lifetime/],
    [(plan) => { (plan.awareness as { level: string }).level = "most_aware"; }, /awareness level/],
    [(plan) => { delete (plan.fills[0].audit as Record<string, unknown>).concreteDetail; }, /criteria audit|Director/],
  ];
  for (const [change, pattern] of cases) {
    const plan = structuredClone(good); change(plan); assert.throws(() => validateDirectorPlan(plan, catalog, input), pattern);
  }
});

test("retained v1 plans stay readable with their own audit keys; new decisions must be v2", () => {
  const input = directorSourceFixture(), catalog = loadDirectorCatalog(), legacy = testLegacyDirectorPlan(input, catalog);
  assert.deepEqual(parseNativeDirectorPlan(legacy), legacy);
  assert.deepEqual(validateStoredDirectorPlan(legacy, catalog, input), legacy);
  assert.throws(() => validateDirectorPlan(legacy, catalog, input), /must use plan schema v2/);
  const failed = structuredClone(legacy); failed.fills[0].audit.clarity.pass = false;
  assert.throws(() => validateStoredDirectorPlan(failed, catalog, input), /failed its criteria audit/);
  const mixed = { ...structuredClone(testDirectorPlan(input, catalog)), schemaVersion: 1 };
  assert.throws(() => parseNativeDirectorPlan(mixed), /Director/);
  assert.throws(() => parseNativeDirectorPlan({ ...legacy, schemaVersion: 3 }), /Unsupported Director plan version/);
});

test("Director author and critic precede a cold-readable bound decision; tampering invalidates it", async () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-director-"))), source = directorSourceFixture();
  const evidence = source as unknown as ProposalEvidence, phases: string[] = [];
  try {
    const record = await stageNativeDirector({ directory, evidence, rawIntent: source.rawIntent, remainingMs: () => 1000,
      brain: async (request) => {
        phases.push(request.phase);
        assert.match(request.prompt, /VISUAL EXPLANATION — shared directing standard v1/);
        assert.equal(request.prompt.includes("VISUAL EXPLANATION REVIEW"), request.phase === "critic");
        if (request.phase === "critic") assert.match(request.prompt, /opening-only Director review/);
        return nativeDirectorTestBrain(request);
      } });
    assert.deepEqual(phases, ["author", "critic"]); assert.deepEqual(readNativeDirector(directory), record);
    assert.equal(record.plan.schemaVersion, 2);
    assertDirectorSource(record, source.rawIntent, evidence);
    assert.throws(() => assertDirectorSource(record, "changed intent", evidence), /different source/);
    const filename = path.join(directory, "native-director/author-result.json"), bytes = readFileSync(filename);
    const changed = JSON.parse(bytes.toString()); changed.output.fills[0].writtenHook = "New Hook";
    writeFileSync(filename, JSON.stringify(changed)); assert.throws(() => readNativeDirector(directory), /absent opening evidence|prompt differs/);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("a v1 author reply cannot become a new decision", async () => {
  const directory = realpathSync(mkdtempSync(path.join(os.tmpdir(), "sniper-director-v1-"))), source = directorSourceFixture();
  try {
    await assert.rejects(stageNativeDirector({ directory, evidence: source as unknown as ProposalEvidence,
      rawIntent: source.rawIntent, remainingMs: () => 1000, brain: async (request) => {
        if (request.phase === "critic") return nativeDirectorTestBrain(request);
        const packet = JSON.parse(request.prompt.split("DIRECTOR_INPUT_JSON\n")[1]);
        return { output: testLegacyDirectorPlan(packet.input, packet.library) };
      } }), /must use plan schema v2/);
    assert.equal(existsSync(path.join(directory, "native-director/record.json")), false);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("Director permits benefit/timeframe hooks while retaining length and line limits", () => {
  const input = directorSourceFixture(), catalog = loadDirectorCatalog();
  const plan = testDirectorPlan(input, catalog);
  const setHook = (text: string) => {
    plan.fills[0].writtenHook = text;
    for (const audit of Object.values(plan.fills[0].audit)) audit.quote = text;
  };
  for (const text of ["Two steps to invoices\npaid within 30 days",
    "Where did $62 of lunch\ngo this week?"]) {
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
