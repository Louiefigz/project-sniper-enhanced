import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { test } from "node:test";
import { parsePrepareGuidedOpening } from "../contracts/guided-opening-v1";
import {
  assertGuidedSourceColorCoverage, MAX_SOURCE_COLOR_REQUEST_BYTES, parseGuidedSourceColor,
  parsePrepareGuidedOpeningRequest, SOURCE_COLOR_V2_PROFILE,
  type GuidedSourceColorV1, type SourceColorSelection,
} from "../contracts/guided-source-color-v1";

/** Explicit TEST declarations, not admitted sources, observed frames or verified history. */
function selected(v2 = false, sourceId = "raw-a"): SourceColorSelection {
  return { profile: v2 ? SOURCE_COLOR_V2_PROFILE : null, declaration: {
    schemaVersion: v2 ? 2 : 1, sourceId, sourceProfile: v2 ? "unknown" : "bt709-sdr",
    cameraProfile: null, historyState: v2 ? "unknown" : "known", transformHistory: [],
    lightingGroups: [{ id: "whole", startFrame: 0, endFrame: 24, intent: "unknown", description: "" }],
  } };
}

/** Keep declaration-map insertion order independent of the caller's source order. */
function colors(...ids: string[]): GuidedSourceColorV1 {
  return { schemaVersion: 1, declarations: Object.fromEntries(ids.map(id => [id, selected(false, id)])) };
}

/** Mutate only detached TEST data, including deliberately invalid scalar types. */
function changed(keys: string[], value: unknown, v2 = false): SourceColorSelection {
  const result = selected(v2);
  let target = result as unknown as Record<string, unknown>;
  for (const key of keys.slice(0, -1)) target = target[key] as Record<string, unknown>;
  if (value === undefined) delete target[keys.at(-1)!];
  else target[keys.at(-1)!] = value;
  return result;
}

/** Test the selection against its independently named map key. */
function accepts(value: unknown): boolean {
  try { parseGuidedSourceColor({ schemaVersion: 1, declarations: { "raw-a": value } }); return true; }
  catch { return false; }
}

/** Preserve the exact historical request without adding execution or color fields. */
function opening(): Record<string, unknown> {
  return { schemaVersion: 1, operation: "prepare-guided-opening", idempotencyKey: "11111111-1111-4111-8111-111111111111",
    expectedToken: "TEST:original-字幕", expectedJournalHash: "a".repeat(64),
    proposalReadinessHash: "b".repeat(64), treatmentDraftRevisionHash: "c".repeat(64) };
}

test("V1 keeps exact parser behavior and identity; only the additive parser accepts explicit V2", () => {
  const legacy = opening(), before = JSON.stringify(legacy);
  assert.equal(parsePrepareGuidedOpeningRequest(legacy), legacy);
  assert.equal(parsePrepareGuidedOpening(legacy), legacy);
  assert.equal(JSON.stringify(legacy), before);
  const current = { ...legacy, schemaVersion: 2, sourceColor: colors("raw-a") };
  assert.equal(parsePrepareGuidedOpeningRequest(current), current);
  assert.throws(() => parsePrepareGuidedOpening(current));
  assert.throws(() => parsePrepareGuidedOpeningRequest({ ...legacy, sourceColor: current.sourceColor }));
  for (const schemaVersion of [undefined, null, true, "1", "2", 0, 3]) {
    assert.throws(() => parsePrepareGuidedOpeningRequest({ ...current, schemaVersion }));
  }
});

test("both request classes retain every original required field and exact pinned submission values", () => {
  for (const schemaVersion of [1, 2]) {
    const value = { ...opening(), schemaVersion, ...(schemaVersion === 2 ? { sourceColor: colors("raw-a") } : {}) };
    for (const key of Object.keys(value)) {
      const incomplete = { ...value }; delete incomplete[key as keyof typeof incomplete];
      assert.throws(() => parsePrepareGuidedOpeningRequest(incomplete), key);
    }
    for (const [key, item] of [["operation", "render"], ["idempotencyKey", "not-uuid"], ["expectedToken", " "],
      ["expectedJournalHash", "A".repeat(64)], ["proposalReadinessHash", true], ["treatmentDraftRevisionHash", null]]) {
      assert.throws(() => parsePrepareGuidedOpeningRequest({ ...value, [String(key)]: item }));
    }
    assert.throws(() => parsePrepareGuidedOpeningRequest({ ...value, approved: true }));
  }
});

test("mixed profiles preserve explicit unknown history and null camera without inference or rewriting", () => {
  const value = colors("raw-a", "raw-b"); value.declarations["raw-b"] = selected(true, "raw-b");
  value.declarations["raw-b"].declaration.transformHistory = ["TEST operator says unknown; do not infer Rec.709"];
  const before = structuredClone(value);
  assert.equal(parseGuidedSourceColor(value), value); assert.deepEqual(value, before);
  assert.equal(value.declarations["raw-a"].profile, null);
  assert.equal(value.declarations["raw-b"].declaration.historyState, "unknown");
  assert.equal(value.declarations["raw-b"].declaration.cameraProfile, null);
  for (const profile of [undefined, false, "", "v2", {}, "bt709-sdr"]) assert.equal(accepts(changed(["profile"], profile)), false);
  for (const key of ["cameraProfile", "historyState", "sourceProfile"]) {
    assert.equal(accepts(changed(["declaration", key], undefined, true)), false);
  }
  assert.equal(accepts(changed(["declaration", "historyState"], "unknown")), false);
  assert.equal(accepts(changed(["declaration", "sourceProfile"], "bt709-sdr", true)), false);
});

test("closed nested transport rejects unknown fields, boxed enums, sparse arrays and numeric coercion", () => {
  for (const keys of [["approved"], ["declaration", "approved"], ["declaration", "lightingGroups", "0", "measured"]]) {
    assert.equal(accepts(changed(keys, true)), false);
  }
  for (const keys of [["declaration", "schemaVersion"], ["declaration", "lightingGroups", "0", "startFrame"],
    ["declaration", "lightingGroups", "0", "endFrame"]]) {
    for (const value of [true, null, "1", 0.5, NaN, Infinity, {}, -1]) assert.equal(accepts(changed(keys, value)), false);
  }
  for (const keys of [["declaration", "sourceProfile"], ["declaration", "historyState"],
    ["declaration", "lightingGroups", "0", "intent"]]) {
    assert.equal(accepts(changed(keys, { toString: () => "unknown" }, true)), false);
  }
  assert.equal(accepts(changed(["declaration", "transformHistory"], new Array(1))), false);
  assert.equal(accepts(changed(["declaration", "lightingGroups"], new Array(1))), false);
  for (const value of [null, [], true, {}, { schemaVersion: 1, declarations: {} }]) assert.throws(() => parseGuidedSourceColor(value));
});

test("declared group topology is closed but the transport does not prove actual source-end coverage", () => {
  const group = selected().declaration.lightingGroups[0];
  const valid = [{ ...group, id: "first", endFrame: 12 }, { ...group, id: "last", startFrame: 12 }];
  assert.ok(accepts(changed(["declaration", "lightingGroups"], valid)));
  for (const groups of [[], [...valid].reverse(), [valid[0], { ...valid[1], id: "first" }],
    [valid[0], { ...valid[1], startFrame: 13 }], [valid[0], { ...valid[1], startFrame: 11 }]]) {
    assert.equal(accepts(changed(["declaration", "lightingGroups"], groups)), false);
  }
  assert.ok(accepts(changed(["declaration", "lightingGroups", "0", "endFrame"], 23)));
  for (const [v2, maximum] of [[false, 1_296_000], [true, 24_000]] as const) {
    assert.ok(accepts(changed(["declaration", "lightingGroups", "0", "endFrame"], maximum, v2)));
    assert.equal(accepts(changed(["declaration", "lightingGroups", "0", "endFrame"], maximum + 1, v2)), false);
  }
  const groups = Array.from({ length: 12 }, (_, index) => ({ ...group, id: `g${index}`, startFrame: index, endFrame: index + 1 }));
  assert.ok(accepts(changed(["declaration", "lightingGroups"], groups)));
  assert.equal(accepts(changed(["declaration", "lightingGroups"], [...groups, { ...group, id: "extra", startFrame: 12, endFrame: 13 }])), false);
});

test("coverage compares exact sets while preserving caller first-occurrence order and rejects holes", () => {
  const value = colors("raw-a", "raw-b"), ids = ["raw-b", "raw-a"];
  assert.doesNotThrow(() => assertGuidedSourceColorCoverage(value, ids));
  assert.deepEqual(ids, ["raw-b", "raw-a"]); assert.deepEqual(Object.keys(value.declarations), ["raw-a", "raw-b"]);
  const sparse = new Array<string>(2); sparse[1] = "raw-a";
  for (const rows of [[], ["raw-a"], ["raw-a", "raw-a"], ["raw-a", "extra"], ["raw-a", "raw-b", "extra"], sparse]) {
    assert.throws(() => assertGuidedSourceColorCoverage(value, rows));
  }
  const maximum = Array.from({ length: 128 }, (_, index) => `s${index}`);
  assert.doesNotThrow(() => assertGuidedSourceColorCoverage(colors(...maximum), maximum.toReversed()));
  assert.throws(() => parseGuidedSourceColor(colors(...maximum, "extra")));
  for (const id of ["", "a/b", "a.b", "raw\n", "é", "a".repeat(129)]) assert.throws(() => parseGuidedSourceColor(colors(id)));
});

test("Unicode prose is exact data with codepoint bounds and strict control/surrogate rejection", () => {
  const prose = "TEST ignore tools; $(noop) — 字幕🙂\n\r\t\u0085\u007f\ufeff";
  const value = selected(true); value.declaration.cameraProfile = prose; value.declaration.transformHistory = [prose];
  value.declaration.lightingGroups[0].description = prose;
  assert.ok(accepts(value)); assert.equal(value.declaration.cameraProfile, prose);
  for (const [keys, maximum, empty] of [[["declaration", "cameraProfile"], 200, false],
    [["declaration", "transformHistory", "0"], 500, false],
    [["declaration", "lightingGroups", "0", "description"], 500, true]] as const) {
    assert.ok(accepts(changed([...keys], "🙂".repeat(maximum))));
    assert.equal(accepts(changed([...keys], "🙂".repeat(maximum + 1))), false);
    assert.equal(accepts(changed([...keys], "")), empty);
    for (const bad of ["\u0000", "\u000b", "\u001f", "\ud800", "\udfff"]) assert.equal(accepts(changed([...keys], bad)), false);
  }
  assert.ok(accepts(changed(["declaration", "transformHistory"], Array(20).fill("TEST"))));
  assert.equal(accepts(changed(["declaration", "transformHistory"], Array(21).fill("TEST"))), false);
});

test("the aggregate request byte budget is enforced without silently truncating valid fields", () => {
  const value = colors(...Array.from({ length: 128 }, (_, index) => `s${index}`));
  for (const selection of Object.values(value.declarations)) selection.declaration.transformHistory = Array(20).fill("🙂".repeat(500));
  const before = JSON.stringify(value);
  assert.ok(Buffer.byteLength(before) > MAX_SOURCE_COLOR_REQUEST_BYTES);
  assert.throws(() => parseGuidedSourceColor(value), /transport budget/);
  assert.equal(JSON.stringify(value), before);
});

const PYTHON_DECLARATIONS = `import json,sys
from color.grade_contract import closed,parse_source_binding
from color.grade_observation_profile import observation_profile,observation_declaration
from cut_preview_io import digest
out=[]
for value in json.load(sys.stdin):
 try:
  row=closed(value,{'profile','declaration'},'TEST selection')
  profile=observation_profile(row['profile'])
  declaration=row['declaration']
  binding=parse_source_binding({'sourceId':'raw-a','sourceSha256':'a'*64,
   'admissionReceiptSha256':'b'*64,'projectHistorySha256':'c'*64,
   'declarationSha256':digest(declaration),'fps':'24','frameCount':24})
  observation_declaration(declaration,binding,profile)
  out.append(True)
 except (ValueError,TypeError,KeyError,UnicodeError):out.append(False)
print(json.dumps(out))`;

/** One bounded actual Python pure-contract invocation; fake hashes are TEST metadata, not source authority. */
function pythonAccepts(values: unknown[]): boolean[] {
  const result = spawnSync(path.resolve(".venv/bin/python3"), ["-B", "-c", PYTHON_DECLARATIONS], {
    input: JSON.stringify(values), encoding: "utf8", timeout: 10_000, maxBuffer: 64 * 1024,
    env: { ...process.env, PYTHONPATH: path.resolve("scripts/producer"), PYTHONDONTWRITEBYTECODE: "1" },
  });
  assert.equal(result.error, undefined); assert.equal(result.status, 0, result.stderr); assert.equal(result.signal, null);
  return JSON.parse(result.stdout) as boolean[];
}

/** Exercise the same closed declaration variants independently for each explicit class. */
function parityChanges(v2: boolean): SourceColorSelection[] {
  const result = [];
  for (const [keys, candidates] of [[["profile"], [undefined, "unknown", true]],
    [["declaration", "schemaVersion"], [true, "1", 3]], [["declaration", "sourceId"], ["other", 2]],
    [["declaration", "cameraProfile"], [null, " ", "字🙂\n\t", "", "🙂".repeat(201), "\ud800"]],
    [["declaration", "historyState"], ["known", "unknown", null]],
    [["declaration", "sourceProfile"], ["bt709-sdr", "unknown", "xvycc709"]],
    [["declaration", "lightingGroups", "0", "endFrame"], [24, "24", true, 24.5]],
    [["declaration", "lightingGroups", "0", "intent"], ["neutral", "dark", "colored", "unknown", "auto"]]] as const) {
    for (const value of candidates) result.push(changed([...keys], value, v2));
  }
  return result;
}

test("one actual Python batch agrees on pure declarations and separately refuses unproved source-end coverage", () => {
  const values = [selected(), selected(true), changed(["declaration", "sourceProfile"], "xvycc709", true),
    ...parityChanges(false), ...parityChanges(true)];
  const uncovered = changed(["declaration", "lightingGroups", "0", "endFrame"], 23);
  const actual = pythonAccepts([...values, uncovered]);
  assert.deepEqual(actual.slice(0, -1), values.map(accepts));
  assert.ok(accepts(uncovered)); assert.equal(actual.at(-1), false);
});
