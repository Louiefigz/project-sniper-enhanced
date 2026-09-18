import assert from "node:assert/strict";
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";
import { assertProposalClauseCoverage, parseTreatmentProposalV2 } from "../contracts/treatment-proposal-v2";
import { parseTreatmentProposalV4 } from "../contracts/treatment-proposal-v4";
import { CURRENT_TREATMENT_PROPOSAL_VERSION, parseTreatmentProposalV5 } from "../contracts/treatment-proposal-v5";
import { parseTreatmentProposalV6 } from "../contracts/treatment-proposal-v6";
import { parseTreatmentProposalV7, parseCurrentTreatmentProposal as parseThroughV7 } from "../contracts/treatment-proposal-v7";
import { parseTreatmentProposalV8, parseCurrentTreatmentProposal, proposalV8ValidationView } from "../contracts/treatment-proposal-v8";
import { layoutOperation, layoutProposal, layoutSelection, oldOperation, PRESENTER_RAW, type Row } from "./_presenter-layout-fixture";

test("actual V8 retains the real timed layout, Unicode brief and original clause indices", () => {
  const value = layoutProposal(), before = JSON.stringify(value), parsed = parseTreatmentProposalV8(value);
  assertProposalClauseCoverage(parsed, PRESENTER_RAW);
  assert.deepEqual(parsed.operations[0], layoutOperation());
  assert.deepEqual(parsed.clauses, value.clauses);
  assert.equal(JSON.stringify(value), before);
  const view = proposalV8ValidationView(parsed);
  assert.equal(view.schemaVersion, 7);
  const { presenterLayout: _omitted, ...preserved } = oldOperation("preserve-cut"); void _omitted;
  assert.deepEqual(view.operations[0], preserved);
});

test("validation view removes geometry and timing only in the separate historical value", () => {
  const parsed = parseTreatmentProposalV8(layoutProposal()), before = structuredClone(parsed);
  const operation = proposalV8ValidationView(parsed).operations[0];
  assert.equal(operation.type, "preserve-cut");
  for (const key of ["reason", "beatIndex", "startAnchor", "endAnchorExclusive"] as const) assert.equal(operation[key], null);
  assert.equal(Object.hasOwn(operation, "presenterLayout"), false);
  assert.deepEqual(parsed, before);
  assert.throws(() => parseTreatmentProposalV8(proposalV8ValidationView(parsed)), /Invalid V8/);
});

test("mixed V7 music, V6 crop, V5 captions and V8 layout preserve actual operation slots", () => {
  const operations = [oldOperation("captions-full-program"), oldOperation("reframe-manual-short"),
    layoutOperation(), oldOperation("music-bed-full-program")];
  const value = layoutProposal({ operations });
  (value.clauses as Row[])[0].operationIndices = [0, 1, 2, 3];
  const parsed = parseTreatmentProposalV8(value);
  assertProposalClauseCoverage(parsed, PRESENTER_RAW);
  assert.deepEqual(parsed.operations, operations);
  const view = proposalV8ValidationView(parsed);
  assert.equal(view.operations[2].type, "preserve-cut");
  assert.equal(view.operations[0].type, "captions-full-program");
  assert.equal(view.operations[1].type, "reframe-manual-short");
  assert.equal(view.operations[3].type, "music-bed-full-program");
  assert.deepEqual(view.clauses[0].operationIndices, [0, 1, 2, 3]);
});

test("V8 layout refuses every prior payload and extra field instead of laundering it through preserve-cut", () => {
  for (const patch of [{ captions: oldOperation("captions-full-program").captions },
    { reframe: oldOperation("reframe-manual-short").reframe }, { music: oldOperation("music-bed-full-program").music },
    { variables: {} }, { catalogKind: "statement-card" }, { grade: "warm" }, { presentation: {} },
    { approval: true }, { presenterLayout: null }, { type: ["presenter-layout-window"] }]) {
    assert.throws(() => parseTreatmentProposalV8(layoutProposal({ operations: [layoutOperation(patch)] })), JSON.stringify(patch));
  }
  const { presenterLayout: _omitted, ...missing } = layoutOperation(); void _omitted;
  assert.throws(() => parseTreatmentProposalV8(layoutProposal({ operations: [missing] })), /requires presenterLayout/);
});

test("real window fields are mandatory integers inside the referenced actual beat", () => {
  for (const patch of [{ beatIndex: null }, { beatIndex: 1 }, { beatIndex: false }, { startAnchor: null },
    { startAnchor: "2" }, { startAnchor: 2.5 }, { startAnchor: 8 }, { endAnchorExclusive: 2 },
    { endAnchorExclusive: 11 }, { endAnchorExclusive: Infinity }, { reason: null }, { reason: "brief" }]) {
    assert.throws(() => parseTreatmentProposalV8(layoutProposal({ operations: [layoutOperation(patch)] })), JSON.stringify(patch));
  }
  const value = layoutProposal(); (value.beats as Row[])[0].startAnchor = 3;
  assert.throws(() => parseTreatmentProposalV8(value), /actual referenced story beat/);
});

test("other V8 operations require explicit null and retain every inherited semantic constraint", () => {
  assert.throws(() => parseTreatmentProposalV8(layoutProposal({ operations: [oldOperation("reframe-manual-short")] })), /separate explicit/);
  assert.throws(() => parseTreatmentProposalV8(layoutProposal({ operations: [{ ...oldOperation("preserve-cut"), presenterLayout: layoutSelection() }] })), /Only presenter/);
  assert.throws(() => parseTreatmentProposalV8(layoutProposal({ operations: [{ ...oldOperation("preserve-cut"), beatIndex: 0 }] })));
  assert.throws(() => parseTreatmentProposalV8(layoutProposal({ inventedApproval: true })));
  assert.throws(() => parseTreatmentProposalV8(layoutProposal({ operations: Array(129).fill(layoutOperation()) })));
});

test("historical parsers and the existing default remain closed; new dispatch is opt-in only", () => {
  for (const parser of [parseTreatmentProposalV2, parseTreatmentProposalV4, parseTreatmentProposalV5,
    parseTreatmentProposalV6, parseTreatmentProposalV7, parseThroughV7]) assert.throws(() => parser(layoutProposal()));
  assert.equal(CURRENT_TREATMENT_PROPOSAL_VERSION, 5);
  assert.equal(parseCurrentTreatmentProposal(layoutProposal()).schemaVersion, 8);
  const v7 = proposalV8ValidationView(parseTreatmentProposalV8(layoutProposal()));
  assert.deepEqual(parseCurrentTreatmentProposal(v7), parseThroughV7(v7));
  assert.throws(() => parseThroughV7({ ...layoutProposal(), schemaVersion: 7 }));
});

test("closed V8 JSON schema retains every unchanged V7 definition and all mandatory fields", () => {
  const schema = JSON.parse(readFileSync("schemas/producer/treatment-proposal-v8.schema.json", "utf8"));
  const old = JSON.parse(readFileSync("schemas/producer/treatment-proposal-v7.schema.json", "utf8"));
  const parsed = parseTreatmentProposalV8(layoutProposal());
  assert.deepEqual([...schema.required].sort(), Object.keys(parsed).sort());
  assert.deepEqual([...schema.$defs.operation.required].sort(), Object.keys(parsed.operations[0]).sort());
  assert.deepEqual([...schema.$defs.presenterLayout.required].sort(), Object.keys(layoutSelection()).sort());
  for (const key of Object.keys(old.$defs).filter(key => key !== "operation")) assert.deepEqual(schema.$defs[key], old.$defs[key]);
  const valid = ["inset", "bubble", "split"].map(kind => layoutProposal({ operations: [layoutOperation({
    presenterLayout: layoutSelection(kind as "inset" | "bubble" | "split") })] }));
  const invalid = [layoutProposal({ schemaVersion: 7 }), layoutProposal({ extra: true }),
    ...[{ sourceIds: ["raw-1", "raw-1"] }, { track: true }, { track: 0 }, { schemaVersion: true }, { assetAudio: "mix" }, { path: "/tmp/x.mp4" },
      { assetStart: { numerator: true, denominator: 1 } }, { mask: { kind: "circle", extra: true } }].map(patch =>
      layoutProposal({ operations: [layoutOperation({ presenterLayout: { ...layoutSelection(), ...patch } })] }))];
  const result = execFileSync(pythonInterpreter(), ["scripts/producer/contracts/schema_validator.py", "--batch"], {
    input: JSON.stringify([...valid, ...invalid].map(document => ({ schema: "treatment-proposal-v8.schema.json", document }))),
    encoding: "utf8", timeout: 10000, env: { ...process.env, PYTHONDONTWRITEBYTECODE: "1" },
  });
  assert.deepEqual(JSON.parse(result).map((row: { valid: boolean }) => row.valid), [...valid.map(() => true), ...invalid.map(() => false)]);
});
