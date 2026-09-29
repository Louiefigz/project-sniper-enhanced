/**
 * Engineering standards checker for TypeScript/JavaScript files (MASTER-PLAN G11; P0 Step 7.0). Static only.
 *
 * Per function (declarations, methods, arrow functions and function expressions): at most 50 lines, at most 4
 * parameters, nesting of at most 2 control statements (if/for/while/do/switch/try; an `else if` stays at its
 * `if`'s level; a nested function starts again at 0). Every exported function or class carries a JSDoc block.
 * Uses the checkout's own `node_modules/typescript` parser.
 *
 *   node ts_standards_check.cjs [--baseline FILE] FILE...
 *   node ts_standards_check.cjs --write-baseline FILE FILE...
 *
 * Keys are path + rule + name, so a line shift is not a new violation; a recorded violation fails only when it
 * got worse. Exit 0 when nothing new, 1 otherwise. It cannot judge semantics or JSDoc content.
 */
"use strict";
const fs = require("node:fs");
const path = require("node:path");
const ts = require(path.resolve(__dirname, "../../../node_modules/typescript"));

const LIMITS = { lines: 50, params: 4, nesting: 2 };
const CONTROL = new Set([ts.SyntaxKind.IfStatement, ts.SyntaxKind.ForStatement, ts.SyntaxKind.ForInStatement,
  ts.SyntaxKind.ForOfStatement, ts.SyntaxKind.WhileStatement, ts.SyntaxKind.DoStatement,
  ts.SyntaxKind.SwitchStatement, ts.SyntaxKind.TryStatement]);

/** True for a node that starts a new function scope. */
function isFunction(node) {
  return ts.isFunctionDeclaration(node) || ts.isMethodDeclaration(node) || ts.isArrowFunction(node)
    || ts.isFunctionExpression(node) || ts.isConstructorDeclaration(node) || ts.isGetAccessor(node)
    || ts.isSetAccessor(node);
}

/** Deepest control nesting under `node` without entering nested functions. */
function depth(node, level) {
  let deepest = level;
  ts.forEachChild(node, (child) => {
    if (isFunction(child)) return;
    const elseIf = ts.isIfStatement(node) && node.elseStatement === child && ts.isIfStatement(child);
    const inner = CONTROL.has(child.kind) && !elseIf ? level + 1 : level;
    deepest = Math.max(deepest, depth(child, inner));
  });
  return deepest;
}

/** A readable name for a function node. */
function nameOf(node, source) {
  if (node.name) return node.name.getText(source);
  const parent = node.parent;
  if (parent && ts.isVariableDeclaration(parent)) return parent.name.getText(source);
  if (parent && ts.isPropertyAssignment(parent)) return parent.name.getText(source);
  if (parent && ts.isCallExpression(parent)) {
    const first = parent.arguments[0];
    const label = first && ts.isStringLiteralLike(first) ? `(${JSON.stringify(first.text.slice(0, 80))})` : "";
    return `<callback of ${parent.expression.getText(source).slice(0, 60)}${label} #${parent.arguments.indexOf(node)}>`;
  }
  return "<anonymous>";  // stable across line shifts; several anonymous functions share this key (max value kept)
}

/** Whether a declaration is exported. */
function exported(node) {
  const modifiers = ts.canHaveModifiers(node) ? ts.getModifiers(node) || [] : [];
  return modifiers.some((modifier) => modifier.kind === ts.SyntaxKind.ExportKeyword);
}

/** Whether `/** … *\/` precedes the node (or its variable statement). */
function hasJsDoc(node, source) {
  const ranges = ts.getLeadingCommentRanges(source.getFullText(), node.getFullStart()) || [];
  return ranges.some((range) => source.getFullText().slice(range.pos, range.end).startsWith("/**"));
}

/** Every rule the functions and exports of one file break. */
function check(file) {
  const text = fs.readFileSync(file, "utf8");
  const kind = /\.(ts|tsx)$/.test(file) ? ts.ScriptKind.TS : ts.ScriptKind.JS;
  const source = ts.createSourceFile(file, text, ts.ScriptTarget.Latest, true, kind);
  const rows = [];
  const add = (node, rule, name, value) => rows.push({ file, line: source.getLineAndCharacterOfPosition(node.getStart(source)).line + 1, rule, name, value });
  const visit = (node) => {
    if (isFunction(node)) {
      const name = nameOf(node, source);
      const start = source.getLineAndCharacterOfPosition(node.getStart(source)).line;
      const lines = source.getLineAndCharacterOfPosition(node.getEnd()).line - start + 1;
      const nesting = node.body ? depth(node.body, 0) : 0;
      if (lines > LIMITS.lines) add(node, "function-lines", name, lines);
      if (node.parameters.length > LIMITS.params) add(node, "parameters", name, node.parameters.length);
      if (nesting > LIMITS.nesting) add(node, "nesting", name, nesting);
    }
    const declared = ts.isFunctionDeclaration(node) || ts.isClassDeclaration(node);
    const exportedConst = ts.isVariableStatement(node) && exported(node);
    if ((declared && exported(node) && !hasJsDoc(node, source)) || (exportedConst && !hasJsDoc(node, source))) {
      add(node, "jsdoc", declared ? nameOf(node, source) : node.declarationList.declarations[0].name.getText(source), 0);
    }
    ts.forEachChild(node, visit);
  };
  visit(source);
  return rows;
}

/** Entry point. */
function main(argv) {
  const at = (flag) => (argv.includes(flag) ? argv[argv.indexOf(flag) + 1] : null);
  const baselineFile = at("--baseline");
  const writeFile = at("--write-baseline");
  const files = argv.filter((value, index) => !value.startsWith("--") && !["--baseline", "--write-baseline"].includes(argv[index - 1]));
  const rows = files.flatMap(check);
  const key = (row) => `${row.file}::${row.rule}::${row.name}`;
  if (writeFile) {
    const recorded = {};
    for (const row of rows) recorded[key(row)] = Math.max(row.value, recorded[key(row)] ?? row.value);
    fs.writeFileSync(writeFile, JSON.stringify(recorded, null, 0));
    console.log(`baseline written: ${rows.length} recorded violation(s)`);
    return 0;
  }
  const baseline = baselineFile ? JSON.parse(fs.readFileSync(baselineFile, "utf8")) : {};
  let fresh = 0;
  for (const row of rows) {
    const known = baseline[key(row)] !== undefined && row.value <= baseline[key(row)];
    if (!known) fresh += 1;
    console.log(`${known ? "baseline" : "VIOLATION"} ${row.file}:${row.line} ${row.rule} ${row.name} (${row.value})`);
  }
  console.log(`ts standards: ${fresh} new, ${rows.length - fresh} recorded in the baseline, ${files.length} file(s)`);
  return fresh ? 1 : 0;
}

process.exitCode = main(process.argv.slice(2));
