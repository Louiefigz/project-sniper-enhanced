// Actual installed CLI function bodies, executed only in an inert VM.
// No CLI import, browser, encoder, native media or container is launched.
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import test from "node:test";
import vm from "node:vm";
import { instrument } from "../../../templates/motion/container/layout_observer_patch.mjs";

const cli = new URL("../../../templates/motion/node_modules/hyperframes/dist/cli.js", import.meta.url);
const patched = instrument(readFileSync(cli, "utf8"));

test("entire exact patched CLI remains syntactically valid without executing it", () => {
  const result = spawnSync(process.execPath, ["--input-type=module", "--check"], {
    input: patched, encoding: "utf8", timeout: 10_000, maxBuffer: 1024 * 1024,
  });
  assert.equal(result.error, undefined);
  assert.equal(result.status, 0, result.stderr);
});

function actualFunction(name) {
  const anchor = `async function ${name}(`;
  assert.equal(patched.split(anchor).length, 2);
  const start = patched.indexOf(anchor), end = patched.indexOf("\n}", start);
  assert.ok(end > start);
  return patched.slice(start, end + 2);
}

function captureFixture(failure) {
  const events = [], buffer = Buffer.from("TEST screenshot bytes"), cdp = {};
  const session = { page: {}, options: { fps: { num: 30, den: 1 } }, captureMode: "screenshot",
    capturePerf: { frames: 0, seekMs: 0, beforeCaptureMs: 0, screenshotMs: 0, totalMs: 0, frameMs: [] } };
  const context = { session, fpsToNumber: () => 30, getCdpSession: async () => cdp,
    prepareFrameForCapture: async () => { events.push("seek"); return { quantizedTime: 0, seekMs: 0, beforeCaptureMs: 0 }; },
    pageScreenshotCapture: async () => { events.push("capture"); return buffer; },
    __sniperLayout: {
      before: async (held, index, time, client) => {
        assert.equal(held, session); assert.equal(client, cdp); assert.equal(index, 0); assert.equal(time, 0);
        events.push("before"); if (failure === "before") throw new Error("TEST before refusal");
        return { TEST: "original before" };
      },
      after: async (client, value) => {
        assert.equal(client, cdp); assert.equal(value.buffer, buffer); assert.equal(value.prior.TEST, "original before");
        events.push("after"); if (failure === "after") throw new Error("TEST after refusal");
      },
    } };
  return { events, buffer, run: () => vm.runInNewContext(`${actualFunction("captureFrameCore")}\ncaptureFrameCore(session, 0, 0)`, context) };
}

test("ported actual capture body brackets the same screenshot before returning", async () => {
  const fixture = captureFixture();
  const result = await fixture.run();
  assert.equal(result.buffer, fixture.buffer);
  assert.deepEqual(fixture.events, ["seek", "before", "capture", "after"]);
});

test("ported actual capture body preserves both observer refusal boundaries", async () => {
  for (const failure of ["before", "after"]) {
    const fixture = captureFixture(failure);
    await assert.rejects(fixture.run(), new RegExp(`TEST ${failure} refusal`));
    assert.deepEqual(fixture.events, failure === "before" ? ["seek", "before"] : ["seek", "before", "capture", "after"]);
  }
});

test("ported actual dedup entry cannot skip per-capture observations", async () => {
  const session = {};
  await vm.runInNewContext(`${actualFunction("armStaticDedup")}\narmStaticDedup(session, null, null)`, { session });
  assert.equal(session.staticDedupEnabled, false);
  assert.equal(session.staticFrames, undefined);
});

test("ported actual write statements acknowledge only successful same-buffer writes", async () => {
  const expression = /ensureFrameWritten\(await currentEncoder.writeFrame\(buffer\), (i\d*), currentEncoder\);\n\s+__sniperLayout.commit\(\1, buffer\);/g;
  const matches = [...patched.matchAll(expression)];
  assert.equal(matches.length, 1);
  for (const accepted of [true, false]) {
    const events = [], buffer = Buffer.from("TEST encoded input");
    const currentEncoder = { writeFrame: async (value) => { assert.equal(value, buffer); events.push("write"); return accepted; } };
    const context = { [matches[0][1]]: 0, buffer, currentEncoder,
      ensureFrameWritten: (value, index, encoder) => {
        assert.equal(index, 0); assert.equal(encoder, currentEncoder);
        if (!value) throw new Error("TEST encoder refused");
      },
      __sniperLayout: { commit: (index, value) => { assert.equal(index, 0); assert.equal(value, buffer); events.push("commit"); } } };
    const run = vm.runInNewContext(`(async () => { ${matches[0][0]} })()`, context);
    if (accepted) await run;
    else await assert.rejects(run, /TEST encoder refused/);
    assert.deepEqual(events, accepted ? ["write", "commit"] : ["write"]);
  }
});
