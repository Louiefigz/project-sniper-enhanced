"use strict";

// A missing HOME still lets Node discover the image account's home directory.
// HyperFrames uses os.homedir() for config and caches, so bind both CJS and ESM
// views to attempt-owned scratch before the immutable CLI starts.
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
