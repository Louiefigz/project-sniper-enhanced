"use strict";

const { createHash } = require("node:crypto");
const { pathToFileURL } = require("node:url");
const moduleApi = require("node:module");
const policy = require("./review-policy.json");
const START = "function readJsonAttr(";
const END = "\nfunction collectCompositionIds(";
const RETURN = "  return match[1] ?? match[2] ?? null;";
const FUNCTION_SHA = "c458c0216daa4fcce96a21b89de6433c36d917456d56f1d4f14176b00aac0cac";
const hash = (value) => createHash("sha256").update(value).digest("hex");

// Pinned CLI 0.7.33's own patch-element serializer emits &quot; attributes,
// but its StaticGuard regex does not decode them. Decode exactly once using
// that CLI's own LinkeDOM parser, only for its two JSON attributes. Preserve
// every JSON.parse/object-shape check and all other lint rules. This is a
// process-local source compatibility patch, not a finding filter or write.
// A CLI or Node upgrade requires re-auditing this function and load hook.
function transformCliSource(input) {
  const source = typeof input === "string" ? input : Buffer.from(input).toString("utf8");
  if (hash(source) !== policy.cliSha256) {
    throw new Error("Sniper Studio JSON interoperability requires the exact audited CLI bytes");
  }
  const start = source.indexOf(START); const end = source.indexOf(END, start);
  if (start < 0 || end < 0 || source.indexOf(START, start + START.length) !== -1) {
    throw new Error("Sniper Studio JSON interoperability source marker count changed");
  }
  const original = source.slice(start, end);
  if (hash(original) !== FUNCTION_SHA || original.split(RETURN).length !== 2) {
    throw new Error("Sniper Studio JSON interoperability parser requires re-audit");
  }
  const corrected = original.replace(RETURN, [
    "  const raw = match[1] ?? match[2] ?? null;",
    '  if (raw === null || !["data-variable-values", "data-composition-variables"].includes(attr2)) return raw;',
    "  init_esm10();",
    "  return parseHTML('<div ' + match[0] + '></div>').document.querySelector('div').getAttribute(attr2);",
  ].join("\n"));
  return source.slice(0, start) + corrected + source.slice(end);
}

function registerCliInterop(cli, hooks = moduleApi) {
  if (typeof hooks.registerHooks !== "function") {
    throw new Error("Sniper Studio JSON interoperability requires Node registerHooks support; no unpatched fallback is allowed");
  }
  const target = pathToFileURL(cli).href;
  let registration;
  registration = hooks.registerHooks({
    load(url, context, nextLoad) {
      const result = nextLoad(url, context);
      if (url !== target) return result;
      if (result.format !== "module" || result.source == null) {
        throw new Error("Sniper Studio JSON interoperability requires the audited ESM source load");
      }
      const source = transformCliSource(result.source);
      if (typeof registration?.deregister !== "function") {
        throw new Error("Sniper Studio JSON interoperability requires one-shot hook deregistration");
      }
      // Remove before dependency loading: Node 23's global load hook changes
      // unrelated CommonJS interop even for pass-through results.
      registration.deregister();
      return { ...result, source };
    },
  });
  return registration;
}

module.exports = { registerCliInterop, transformCliSource };
