"use strict";

// Node falls back to the OS account directory when HOME is absent. HyperFrames
// calls os.homedir() for config, registry, browser, and credential paths, so a
// clean environment alone is not isolation. Rebind both CommonJS and ESM views
// of the built-in before the CLI module loads.
const os = require("node:os");
const path = require("node:path");
const { syncBuiltinESMExports } = require("node:module");

const isolatedUserDir = process.env.SNIPER_ISOLATED_USER_DIR;
if (!isolatedUserDir || !path.isAbsolute(isolatedUserDir)) {
  throw new Error("SNIPER_ISOLATED_USER_DIR must be an absolute path");
}

Object.defineProperty(os, "homedir", {
  configurable: false,
  enumerable: true,
  value: () => isolatedUserDir,
  writable: false,
});
syncBuiltinESMExports();
