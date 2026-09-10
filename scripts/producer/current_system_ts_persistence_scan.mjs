#!/usr/bin/env node
/** TypeScript-compiler AST discovery for bounded filesystem persistence calls. */
import process from "node:process";
import ts from "typescript";

const FS_MODULES = new Set([
  "fs",
  "fs/promises",
  "node:fs",
  "node:fs/promises",
]);
const PROCESS_MODULES = new Set(["child_process", "node:child_process"]);
const MUTATORS = new Set([
  "appendFile",
  "appendFileSync",
  "copyFile",
  "copyFileSync",
  "createWriteStream",
  "link",
  "linkSync",
  "mkdir",
  "mkdirSync",
  "mkdtemp",
  "mkdtempSync",
  "open",
  "openSync",
  "rename",
  "renameSync",
  "rm",
  "rmSync",
  "rmdir",
  "rmdirSync",
  "symlink",
  "symlinkSync",
  "truncate",
  "truncateSync",
  "unlink",
  "unlinkSync",
  "writeFile",
  "writeFileSync",
]);
const CUSTOM = /^(?:atomicWrite|publishImmutable|writeContentAddressed)/u;
const PROCESS_CALLS = new Set([
  "exec",
  "execFile",
  "execFileSync",
  "execSync",
  "fork",
  "spawn",
  "spawnSync",
]);
const CUSTOM_PROCESS = new Set(["runCmd", "spawnPython"]);

function addNamedBindings(bindings, direct, namespaces) {
  if (!bindings) return;
  if (ts.isNamespaceImport(bindings)) {
    namespaces.add(bindings.name.text);
    return;
  }
  if (!ts.isNamedImports(bindings)) return;
  for (const element of bindings.elements) {
    direct.set(
      element.name.text,
      element.propertyName?.text ?? element.name.text,
    );
  }
}

function addImport(statement, result) {
  if (!ts.isImportDeclaration(statement)
      || !ts.isStringLiteral(statement.moduleSpecifier)
      || !statement.importClause) return;
  const moduleName = statement.moduleSpecifier.text;
  if (!FS_MODULES.has(moduleName) && !PROCESS_MODULES.has(moduleName)) return;
  const filesystem = FS_MODULES.has(moduleName);
  addNamedBindings(
    statement.importClause.namedBindings,
    filesystem ? result.direct : result.processDirect,
    filesystem ? result.namespaces : result.processNamespaces,
  );
}

function importBindings(sourceFile) {
  const result = {
    direct: new Map(),
    namespaces: new Set(),
    processDirect: new Map(),
    processNamespaces: new Set(),
  };
  for (const statement of sourceFile.statements) {
    addImport(statement, result);
  }
  return result;
}

function processName(expression, bindings) {
  if (ts.isIdentifier(expression)) {
    const imported = bindings.processDirect.get(expression.text);
    if (imported && PROCESS_CALLS.has(imported)) return imported;
    return CUSTOM_PROCESS.has(expression.text) ? expression.text : null;
  }
  if (!ts.isPropertyAccessExpression(expression)) return null;
  const parts = propertyParts(expression);
  const leaf = parts.at(-1) ?? "";
  if (CUSTOM_PROCESS.has(leaf)) return leaf;
  return bindings.processNamespaces.has(parts[0]) && PROCESS_CALLS.has(leaf)
    ? parts.join(".") : null;
}

function propertyParts(expression) {
  const parts = [];
  let cursor = expression;
  while (ts.isPropertyAccessExpression(cursor)) {
    parts.unshift(cursor.name.text);
    cursor = cursor.expression;
  }
  if (ts.isIdentifier(cursor)) parts.unshift(cursor.text);
  return parts;
}

function calleeName(expression, bindings) {
  if (ts.isIdentifier(expression)) {
    const imported = bindings.direct.get(expression.text);
    if (imported && MUTATORS.has(imported)) return imported;
    return CUSTOM.test(expression.text) ? expression.text : null;
  }
  if (!ts.isPropertyAccessExpression(expression)) return null;
  const parts = propertyParts(expression);
  const leaf = parts.at(-1) ?? "";
  if (CUSTOM.test(leaf)) return leaf;
  const filesystemNamespace = bindings.namespaces.has(parts[0])
    || parts[0] === "fs";
  return filesystemNamespace && MUTATORS.has(leaf) ? parts.join(".") : null;
}

function openWrites(node, callee, source) {
  const leaf = callee.split(".").at(-1);
  if (leaf !== "open" && leaf !== "openSync") return true;
  const flags = node.arguments[1];
  if (!flags) return true;
  if (ts.isStringLiteral(flags)) return /[wax+]/u.test(flags.text);
  const text = flags.getText(source);
  const writers = ["O_WRONLY", "O_RDWR", "O_CREAT", "O_TRUNC", "O_APPEND"];
  if (writers.some((token) => text.includes(token))) return true;
  return !text.includes("O_RDONLY");
}

function scan(path, text) {
  const kind = path.endsWith(".tsx") ? ts.ScriptKind.TSX : ts.ScriptKind.TS;
  const source = ts.createSourceFile(
    path, text, ts.ScriptTarget.Latest, true, kind);
  if (source.parseDiagnostics.length) {
    const diagnostic = source.parseDiagnostics[0];
    throw new Error(
      `cannot parse ${path}: ${ts.flattenDiagnosticMessageText(
        diagnostic.messageText, " ")}`,
    );
  }
  const bindings = importBindings(source);
  const sites = [];
  const boundaries = [];
  function visit(node) {
    if (ts.isCallExpression(node)) {
      const callee = calleeName(node.expression, bindings);
      if (callee && openWrites(node, callee, source)) {
        const line = source.getLineAndCharacterOfPosition(
          node.getStart(source)).line + 1;
        sites.push({ path, language: "typescript", callee, line });
      }
      const process = processName(node.expression, bindings);
      if (process) {
        const line = source.getLineAndCharacterOfPosition(
          node.getStart(source)).line + 1;
        boundaries.push({
          path, language: "typescript", callee: process, line,
        });
      }
    }
    ts.forEachChild(node, visit);
  }
  visit(source);
  return { sites, boundaries };
}

let body = "";
for await (const chunk of process.stdin) body += chunk;
try {
  const sources = JSON.parse(body);
  const rows = Object.entries(sources).map(([path, text]) => scan(path, text));
  const sites = rows.flatMap((row) => row.sites);
  const boundaries = rows.flatMap((row) => row.boundaries);
  process.stdout.write(`${JSON.stringify({ ok: true, sites, boundaries })}\n`);
} catch (error) {
  process.stdout.write(`${JSON.stringify({
    ok: false,
    error: error instanceof Error ? error.message : String(error),
  })}\n`);
  process.exitCode = 1;
}
