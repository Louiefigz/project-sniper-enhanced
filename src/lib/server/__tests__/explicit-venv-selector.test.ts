/** Pure filesystem selection checks; no interpreter, package installation or media is executed. */
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test, { type TestContext } from "node:test";
import { explicitVenvPython, pythonInterpreter } from "@/app/api/_lib/spawn-python";

function fixture(t: TestContext) {
  const temporary = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "sniper-venv-selector-")));
  const root = path.join(temporary, "installed"), bin = path.join(root, "bin");
  fs.mkdirSync(bin, { recursive: true });
  fs.writeFileSync(path.join(root, "pyvenv.cfg"), "TEST-only selection fixture, not an interpreter runtime\n");
  const executable = path.join(temporary, "TEST-unexecuted-binary");
  fs.writeFileSync(executable, "TEST only; must never be executed\n");
  fs.chmodSync(executable, 0o755);
  fs.symlinkSync(executable, path.join(bin, "python3"));
  t.after(() => fs.rmSync(temporary, { recursive: true, force: true }));
  return { temporary, root, bin, executable, python: path.join(bin, "python3") };
}

test("explicit canonical installed venv preserves invocation path rather than resolving out of the environment", t => {
  const f = fixture(t);
  assert.equal(explicitVenvPython(f.root), f.python);
  assert.notEqual(f.python, fs.realpathSync(f.python));
});

test("explicit root rejects relative, normalized aliases, trailing separators and controls", t => {
  const f = fixture(t);
  for (const value of ["", "relative", f.root + "/", f.root + "/../installed", f.root + "\n", f.root + "\\bin"]) {
    assert.throws(() => explicitVenvPython(value));
  }
});

test("whole-venv and bin symlink aliases remain forbidden", t => {
  const f = fixture(t), alias = path.join(f.temporary, "alias");
  fs.symlinkSync(f.root, alias);
  assert.throws(() => explicitVenvPython(alias));
  fs.renameSync(f.bin, path.join(f.root, "actual-bin"));
  fs.symlinkSync(path.join(f.root, "actual-bin"), f.bin);
  assert.throws(() => explicitVenvPython(f.root));
});

test("missing or nonregular interpreter/config cannot select ambient Python", t => {
  const f = fixture(t), config = path.join(f.root, "pyvenv.cfg");
  fs.unlinkSync(f.python);
  assert.throws(() => explicitVenvPython(f.root));
  fs.mkdirSync(f.python);
  assert.throws(() => explicitVenvPython(f.root));
  fs.rmdirSync(f.python); fs.symlinkSync(f.executable, f.python);
  fs.unlinkSync(config);
  assert.throws(() => explicitVenvPython(f.root));
  fs.symlinkSync(f.executable, config);
  assert.throws(() => explicitVenvPython(f.root));
});

test("nonexecutable interpreter is rejected before a worker is attempted", t => {
  const f = fixture(t);
  fs.chmodSync(f.executable, 0o644);
  assert.throws(() => explicitVenvPython(f.root));
});

test("empty, oversized and multiply linked configs are rejected", t => {
  const f = fixture(t), config = path.join(f.root, "pyvenv.cfg");
  fs.writeFileSync(config, "");
  assert.throws(() => explicitVenvPython(f.root));
  fs.writeFileSync(config, Buffer.alloc(64 * 1024 + 1));
  assert.throws(() => explicitVenvPython(f.root));
  fs.writeFileSync(config, "TEST config");
  fs.linkSync(config, path.join(f.temporary, "config-link"));
  assert.throws(() => explicitVenvPython(f.root));
});

test("explicit environment selection is strict and default behavior stays unchanged when absent", t => {
  const f = fixture(t), prior = process.env.SNIPER_PYTHON_VENV_ROOT;
  t.after(() => { if (prior === undefined) delete process.env.SNIPER_PYTHON_VENV_ROOT; else process.env.SNIPER_PYTHON_VENV_ROOT = prior; });
  delete process.env.SNIPER_PYTHON_VENV_ROOT;
  const normal = path.join(process.cwd(), ".venv", "bin", "python3");
  assert.equal(pythonInterpreter(), fs.existsSync(normal) ? normal : "python3");
  process.env.SNIPER_PYTHON_VENV_ROOT = f.root;
  assert.equal(pythonInterpreter(), f.python);
  process.env.SNIPER_PYTHON_VENV_ROOT = "";
  assert.throws(() => pythonInterpreter());
  process.env.SNIPER_PYTHON_VENV_ROOT = path.join(f.temporary, "missing");
  assert.throws(() => pythonInterpreter());
});
