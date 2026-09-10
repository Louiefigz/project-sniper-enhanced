import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import path from "node:path";
import {
  cutTrackHash,
  sameRefitJson,
} from "../../../app/api/_lib/plan-refit-receipt";

interface PythonRefitHash {
  canonical: string;
  hash: string;
}

function pythonHash(value: unknown): PythonRefitHash {
  const script = [
    "import json, sys",
    "from edit.refit_authority import _canonical, _hash_value",
    "value = json.load(sys.stdin)",
    "print(json.dumps({'canonical': _canonical(value), 'hash': _hash_value(value)}, ensure_ascii=True))",
  ].join("; ");
  const result = spawnSync(
    path.join(process.cwd(), ".venv", "bin", "python3"),
    ["-c", script],
    {
      encoding: "utf8",
      input: JSON.stringify(value),
      env: {
        ...process.env,
        PYTHONPATH: path.join(process.cwd(), "scripts", "producer"),
      },
    },
  );
  assert.equal(result.status, 0, result.stderr);
  return JSON.parse(result.stdout) as PythonRefitHash;
}

const cutTrack = [{
  sourceId: "raw-😀",
  start: 1e-7,
  end: 1e-6,
  proof: {
    "\ue000": "bmp",
    "😀": "astral",
    numericKeys: { "10": "ten", "2": "two" },
  },
}];
const python = pythonHash(cutTrack);

assert.equal(cutTrackHash(cutTrack), python.hash);
assert.equal(sameRefitJson(
  cutTrack,
  JSON.parse(python.canonical) as unknown,
), true);
assert.throws(
  () => cutTrackHash([{ start: Number.NaN }]),
  /cross-runtime domain/,
);

console.log("plan-refit-hash-cross-runtime.test.ts: passed");
