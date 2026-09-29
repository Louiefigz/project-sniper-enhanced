/** spawn-python never falls back to an ambient `python3` (M9; P0 Step 4.2): a missing engine venv is a named
 * refusal. TEST-only temporary folders; the interpreter file is an empty placeholder, never a real binary or link. */
import assert from "node:assert/strict";
import { mkdirSync, mkdtempSync, realpathSync, rmSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { test } from "node:test";
import { pythonInterpreter } from "@/app/api/_lib/spawn-python";

/** Put one environment variable back as it was. */
function restore(name: string, value: string | undefined): void {
  if (value === undefined) delete process.env[name];
  else process.env[name] = value;
}

/** Run `body` with SNIPER_PIPELINE_ROOT at a fresh TEST folder and SNIPER_PYTHON_VENV_ROOT unset. */
function withPipelineRoot(t: { after: (fn: () => void) => void }, body: (root: string) => void): void {
  const saved = { pipeline: process.env.SNIPER_PIPELINE_ROOT, venv: process.env.SNIPER_PYTHON_VENV_ROOT };
  const root = realpathSync(mkdtempSync(path.join(os.tmpdir(), "TEST-spawn-python-")));
  t.after(() => {
    rmSync(root, { recursive: true, force: true });
    restore("SNIPER_PIPELINE_ROOT", saved.pipeline);
    restore("SNIPER_PYTHON_VENV_ROOT", saved.venv);
  });
  process.env.SNIPER_PIPELINE_ROOT = root;
  delete process.env.SNIPER_PYTHON_VENV_ROOT;
  body(root);
}

test("pythonInterpreter refuses when neither SNIPER_PYTHON_VENV_ROOT nor <root>/.venv exists", (t) => {
  withPipelineRoot(t, (root) => {
    assert.throws(() => pythonInterpreter(), (error: Error) => {
      assert.match(error.message, /^no engine Python venv/);
      assert.ok(error.message.includes(`${root}/.venv`));
      return true;
    });
  });
});

test("pythonInterpreter returns <pipeline root>/.venv/bin/python3 when present", (t) => {
  withPipelineRoot(t, (root) => {
    const bin = path.join(root, ".venv", "bin");
    mkdirSync(bin, { recursive: true });
    writeFileSync(path.join(bin, "python3"), "");  // TEST placeholder file: never a real interpreter or a link
    assert.equal(pythonInterpreter(), path.join(root, ".venv", "bin", "python3"));
  });
});
