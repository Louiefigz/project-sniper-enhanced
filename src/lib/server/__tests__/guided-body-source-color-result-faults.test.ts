/** Actual source2 admission/phase/raw joins. Stopped/native/AV provenance is an explicit TEST leaf; no media executes. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { randomUUID } from "node:crypto";
import test from "node:test";
import { assertHeldBodyResultMetadata } from "../guided-body-result";
import { bodyResultV2Fixture } from "./_guided-body-result-v2-fixture";

type Fixture = Parameters<Parameters<Awaited<ReturnType<typeof bodyResultV2Fixture>>["run"]>[0]>[0];

/** Check the one literal TEST output directory/file before any temporary parent replacement. */
function outputTarget(f: Fixture) {
  const root = fs.realpathSync(f.phase.held.admission.before.job.ctx.dir), directory = f.phase.held.activation.outputRoot;
  assert.equal(directory, path.join(f.phase.held.admission.execution, "body-media-output"));
  assert(directory.startsWith(path.join(root, "guided-v2-operations") + path.sep));
  assert.equal(fs.realpathSync(directory), directory); assert.deepEqual(fs.readdirSync(directory), ["body-result.json"]);
  const file = path.join(directory, "body-result.json"), info = fs.lstatSync(file);
  assert.equal(file, f.result.path); assert.equal(fs.realpathSync(file), file);
  assert(info.isFile()); assert.equal(info.nlink, 1); assert.equal(info.uid, process.getuid!());
  return { directory, file, backup: path.join(path.dirname(directory), `TEST-output-parent-${randomUUID()}`), bytes: fs.readFileSync(file) };
}

test("source2 result retains original phase Buffer before the first input IO", async t => {
  const fixture = await bodyResultV2Fixture(t);
  await fixture.run(async f => {
    const open = fs.openSync, target = f.phase.held.activation.inputPath, original = Buffer.from(f.phase.current.bytes);
    let changed = false;
    const fault = t.mock.method(fs, "openSync", ((...args: Parameters<typeof fs.openSync>) => {
      const descriptor = open(...args);
      if (!changed && args[0] === target) { changed = true; f.phase.current.bytes[0] ^= 1; }
      return descriptor;
    }) as typeof fs.openSync);
    let error: unknown;
    try { f.read(); } catch (failure) { error = failure; }
    finally { fault.mock.restore(); original.copy(f.phase.current.bytes); }
    assert(changed, "TEST exact original input IO was reached");
    assert(error instanceof Error, "changed original phase Buffer was rebaselined after first IO");
    assert.deepEqual(f.phase.current.bytes, original);
  });
});

test("source2 result rechecks original output ancestry after its final file sweep", async t => {
  const fixture = await bodyResultV2Fixture(t);
  await fixture.run(async f => {
    const selected = f.read(), target = outputTarget(f), lstat = fs.lstatSync;
    let replaced = false;
    const fault = t.mock.method(fs, "lstatSync", ((...args: Parameters<typeof fs.lstatSync>) => {
      const value = lstat(...args);
      if (!replaced && args[0] === target.file) {
        replaced = true; fs.renameSync(target.directory, target.backup);
        fs.mkdirSync(target.directory, { mode: 0o700 });
        fs.renameSync(path.join(target.backup, "body-result.json"), target.file);
      }
      return value;
    }) as typeof fs.lstatSync);
    let error: unknown;
    try { assertHeldBodyResultMetadata(selected); } catch (failure) { error = failure; }
    finally {
      fault.mock.restore();
      if (replaced) {
        fs.renameSync(target.file, path.join(target.backup, "body-result.json"));
        fs.rmdirSync(target.directory); fs.renameSync(target.backup, target.directory);
      }
    }
    assert(replaced, "TEST original body-result file sweep was reached");
    assert.deepEqual(fs.readFileSync(target.file), target.bytes);
    assert(error instanceof Error, "original output parent changed after its only ancestry sweep");
  });
});

test("source2 result holds the actual parsed raw receipt before later metadata IO", async t => {
  const fixture = await bodyResultV2Fixture(t);
  await fixture.run(async f => {
    const raw = fs.readFileSync(f.result.path, "utf8"), parse = JSON.parse, lstat = fs.lstatSync;
    let parsed: Record<string, unknown> | undefined, changed = false;
    const parser = t.mock.method(JSON, "parse", (...args: Parameters<typeof JSON.parse>) => {
      const value = parse(...args);
      if (args[0] === raw) parsed = value;
      return value;
    });
    const fault = t.mock.method(fs, "lstatSync", ((...args: Parameters<typeof fs.lstatSync>) => {
      const value = lstat(...args);
      if (parsed && !changed && args[0] === f.result.path) {
        changed = true; parsed.media = { TEST: "not the actual raw receipt media" };
      }
      return value;
    }) as typeof fs.lstatSync);
    let error: unknown;
    try { f.read(); } catch (failure) { error = failure; }
    finally { parser.mock.restore(); fault.mock.restore(); }
    assert(changed, "TEST retained the actual raw parser return before later IO");
    assert.equal(fs.readFileSync(f.result.path, "utf8"), raw);
    assert(error instanceof Error, "changed parsed raw receipt was accepted as original result evidence");
  });
});
