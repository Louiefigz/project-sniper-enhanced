import assert from "node:assert/strict";
import path from "node:path";
import { ownershipArgs } from "../../../app/api/producer/palmier/ownership/runner";

const dir = path.join(path.sep, "tmp", "project", "producer");
const handoff = ownershipArgs(dir, "handoff");
const reclaim = ownershipArgs(dir, "reclaim");
const invalidate = ownershipArgs(dir, "invalidate");

assert.ok(handoff[0].endsWith(path.join("producer", "palmier", "ownership.py")));
assert.deepEqual(handoff.slice(1), [dir, "--handoff"]);
assert.deepEqual(reclaim.slice(1), [dir, "--reclaim"]);
assert.deepEqual(invalidate.slice(1), [dir, "--invalidate"]);
assert.notEqual(handoff, reclaim);

console.log("palmier-ownership.test.ts: all assertions passed");
