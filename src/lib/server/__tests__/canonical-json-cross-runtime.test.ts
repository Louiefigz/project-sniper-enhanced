import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import { planObjectContentHash } from "../auto-edit-authority";
import { stableAuthorityHash } from "../auto-edit-authority-snapshot";
import { canonicalJson, canonicalJsonSha256 } from "../auto-edit-hash";

interface PythonParity {
  canonical: string[];
  planHashes: string[];
  stableHashes: string[];
  unicodeCanonical: string;
  unicodeStableHash: string;
  cutTrackHash: string;
  cutDecisionsHash: string;
}

const PYTHON_PARITY = `
import faulthandler
faulthandler.dump_traceback_later(10)
import json
import sys
from cross_runtime_canonical_json import canonical_compact_json
from fingerprints import plan_content_hash
from palmier.quality_hash import stable_hash
from transcript_cut_evidence import stable_hash as transcript_cut_hash

request = json.load(sys.stdin)
values = request["values"]
response = {
    "canonical": [canonical_compact_json(value) for value in values],
    "planHashes": [
        plan_content_hash({"numericValue": value}) for value in values
    ],
    "stableHashes": [
        stable_hash({"numericValue": value}) for value in values
    ],
    "unicodeCanonical": canonical_compact_json(request["unicode"]),
    "unicodeStableHash": stable_hash(request["unicode"]),
    "cutTrackHash": transcript_cut_hash(request["cutTrack"]),
    "cutDecisionsHash": transcript_cut_hash(request["cutDecisions"]),
}
json.dump(response, sys.stdout, ensure_ascii=True)
sys.stdout.flush()
faulthandler.cancel_dump_traceback_later()
`;

function generatedNumbers(count: number): number[] {
  const bytes = new ArrayBuffer(8);
  const view = new DataView(bytes);
  const values: number[] = [];
  let state = 0x6d2b79f5;
  while (values.length < count) {
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    view.setUint32(0, state);
    state = (Math.imul(state, 1664525) + 1013904223) >>> 0;
    view.setUint32(4, state);
    const value = view.getFloat64(0);
    const unsafeInteger = Number.isInteger(value)
      && !Number.isSafeInteger(value);
    if (Number.isFinite(value) && !unsafeInteger) values.push(value);
  }
  return values;
}

function pythonParity(
  values: number[],
  unicode: unknown,
  cutTrack: unknown,
  cutDecisions: unknown,
): PythonParity {
  const producerDir = path.join(process.cwd(), "scripts", "producer");
  const python = path.join(process.cwd(), ".venv", "bin", "python3");
  const result = spawnSync(python, ["-B", "-c", PYTHON_PARITY], {
    cwd: producerDir,
    encoding: "utf8",
    input: JSON.stringify({ values, unicode, cutTrack, cutDecisions }),
    maxBuffer: 16 * 1024 * 1024,
    // Parity normally takes <1s. A pipe/import stall must fail this test, not the suite.
    timeout: 30_000,
    killSignal: "SIGKILL",
  });
  assert.equal(result.error, undefined,
    `Python parity transport failed: ${result.error?.message}\n${result.stderr}`);
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout) as PythonParity;
}

const boundaryValues = [
  -0, 0, 0.1, -2.5, 1e-7, 1e-6, 0.00001234, 5e-324,
  Number.MIN_VALUE, Number.MAX_SAFE_INTEGER, -Number.MAX_SAFE_INTEGER,
];
const values = [...boundaryValues, ...generatedNumbers(10_000)];
const unicode = {
  "\ue000": "bmp",
  "😀": "astral",
  lone: "\ud800",
  numericKeys: {
    "0": "zero",
    "2": "two",
    "10": "ten",
    "4294967294": "last-array-index",
    "4294967295": "not-an-array-index",
  },
};
const cutTrack = [{
  sourceId: "source-edge",
  start: 1e-7,
  end: 1e-6,
  speed: 1,
}];
const cutDecisions = {
  "2": { at: 1e-6, decision: "keep" },
  "10": { at: 1e-7, decision: "remove" },
};
const parity = pythonParity(values, unicode, cutTrack, cutDecisions);

assert.deepEqual(values.map(canonicalJson), parity.canonical);
assert.deepEqual(
  values.map((numericValue) => planObjectContentHash({ numericValue })),
  parity.planHashes,
);
assert.deepEqual(
  values.map((numericValue) => stableAuthorityHash({ numericValue })),
  parity.stableHashes,
);
assert.equal(canonicalJson(unicode), parity.unicodeCanonical);
assert.equal(stableAuthorityHash(unicode), parity.unicodeStableHash);
assert.equal(canonicalJsonSha256(cutTrack), parity.cutTrackHash);
assert.equal(canonicalJsonSha256(cutDecisions), parity.cutDecisionsHash);
assert.throws(() => canonicalJson(Number.NaN), /cross-runtime domain/);
assert.throws(() => canonicalJson(Number.POSITIVE_INFINITY), /cross-runtime/);
assert.throws(
  () => canonicalJson(Number.MAX_SAFE_INTEGER + 1),
  /cross-runtime domain/,
);
const sparse = Array<number>(3);
sparse[0] = 1;
sparse[2] = 3;
assert.equal(canonicalJson(Array(2)), "[null,null]");
assert.equal(canonicalJson(sparse), "[1,null,3]");
assert.throws(
  () => canonicalJson({ safe: 1, unsafe: BigInt(1) }),
  /bigint.*JSON domain/,
);
assert.equal(
  planObjectContentHash({ numericValue: Number.NaN }),
  undefined,
);

console.log(
  `canonical-json-cross-runtime.test.ts: ${values.length} values passed`,
);
