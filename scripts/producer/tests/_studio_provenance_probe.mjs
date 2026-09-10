/** Execute only the installed Studio source resolver and generated TEST provenance. */
import fs from "node:fs";
import path from "node:path";
import vm from "node:vm";
import { createRequire } from "node:module";

const project = process.argv[3];
const requireProject = createRequire(path.join(project, "package.json"));
const requireParsers = createRequire(requireProject.resolve("@hyperframes/parsers/package.json"));
const { parse } = requireParsers("acorn");
const { parseHTML } = requireParsers("linkedom");

/** Read bounded installed source only; never execute the CLI or application entry. */
function readSource(file) {
  const stat = fs.lstatSync(file);
  if (!stat.isFile() || stat.size > 16 * 1024 * 1024 || fs.realpathSync(file) !== file) {
    throw new Error("Unsupported installed Studio source file");
  }
  return fs.readFileSync(file, "utf8");
}

/** Resolve the actual entry named by this version's packaged Studio HTML. */
function installedSource(cli) {
  const directory = path.dirname(cli);
  const pkg = JSON.parse(readSource(path.join(directory, "../package.json")));
  if (pkg.name !== "hyperframes" || pkg.version !== "0.8.31") {
    throw new Error("This provenance test requires the reviewed Studio 0.8.31 package");
  }
  const root = path.join(directory, "studio");
  const html = parseHTML(readSource(path.join(root, "index.html"))).document;
  const entries = [...html.querySelectorAll('script[type="module"][src]')];
  const relative = entries[0]?.getAttribute("src");
  if (entries.length !== 1 || !/^\/assets\/[A-Za-z0-9_-]+\.js$/.test(relative ?? "")) {
    throw new Error("Missing or ambiguous installed Studio entry");
  }
  return readSource(path.join(root, relative));
}

/** Visit syntax nodes only, preserving the complete installed module parse. */
function nodes(root) {
  const output = [], pending = [root];
  while (pending.length) {
    const node = pending.pop();
    if (!node || typeof node.type !== "string") continue;
    output.push(node);
    pending.push(...Object.values(node).flat().filter(value => value && typeof value === "object"));
  }
  return output;
}

/** Ambiguity fails rather than choosing the first function with a similar name. */
function one(values, label) {
  if (values.length !== 1) throw new Error(`Missing or ambiguous ${label}`);
  return values[0];
}

/** Match the closed two-field resolver shape, not a minifier-assigned symbol. */
function isResolver(fn) {
  if (fn.type !== "FunctionDeclaration" || fn.async || fn.params.length !== 2) return false;
  const body = fn.body.body, returned = body.at(-1)?.argument;
  if (body.length !== 2 || body[0].type !== "VariableDeclaration" || body[1].type !== "ReturnStatement"
      || returned?.type !== "ObjectExpression" || returned.properties.length !== 2) return false;
  const fields = returned.properties;
  return fields.every(field => field.type === "Property" && field.key.type === "Identifier" && !field.computed)
    && fields.map(field => field.key.name).join(",") === "sourceFile,compositionPath"
    && fields.every(field => field.value.type === "Identifier")
    && fields[0].value.name === fields[1].value.name
    && ["data-composition-file", "data-composition-src", "data-composition-id", "index.html"]
      .every(value => nodes(fn).some(node => node.type === "Literal" && node.value === value));
}

/** Retain only original top-level dependencies; unexpected free names fail closed. */
function freeNames(fn) {
  const all = nodes(fn), bound = new Set([fn.id.name, ...fn.params.map(param => param.name)]);
  for (const node of all.filter(node => node.type === "VariableDeclarator")) bound.add(node.id.name);
  for (const node of all.filter(node => node.type === "ArrowFunctionExpression")) {
    node.params.forEach(param => bound.add(param.name));
  }
  const ignored = new Set(all.flatMap(node => {
    if (node.type === "MemberExpression" && !node.computed) return [node.property];
    if (node.type === "Property" && !node.computed) return [node.key];
    return [];
  }));
  return new Set(all.filter(node => node.type === "Identifier" && !ignored.has(node)
    && !bound.has(node.name)).map(node => node.name));
}

/** Bind the actual resolver, two helpers, map initializer and its actual setter. */
function resolverParts(source) {
  const tree = parse(source, { ecmaVersion: "latest", sourceType: "module" });
  const resolver = one(tree.body.filter(isResolver), "source-file resolver");
  const calls = nodes(resolver).filter(node => node.type === "CallExpression" && node.callee.type === "Identifier");
  const names = [...new Set(calls.map(node => node.callee.name))];
  if (names.length !== 2 || [...freeNames(resolver)].some(name => !names.includes(name))) {
    throw new Error("Unexpected resolver dependency");
  }
  const helpers = names.map(name => one(tree.body.filter(node => node.type === "FunctionDeclaration"
    && node.id.name === name), "resolver dependency"));
  one(helpers.filter(fn => !fn.async && fn.params.length === 2 && freeNames(fn).size === 0), "ancestor helper");
  one(helpers.filter(fn => !fn.async && fn.params.length === 1 && freeNames(fn).size === 1), "map fallback helper");
  const mapName = one([...new Set(helpers.flatMap(fn => [...freeNames(fn)]))], "composition map dependency");
  const map = one(tree.body.filter(node => node.type === "VariableDeclaration" && node.declarations.length === 1
    && node.declarations[0].id.name === mapName), "composition map initializer");
  const init = map.declarations[0].init;
  if (map.kind !== "let" || init?.type !== "NewExpression" || init.callee.name !== "Map" || init.arguments.length) {
    throw new Error("Unexpected composition map initializer");
  }
  const setter = one(tree.body.filter(node => isMapSetter(node, mapName)), "composition map setter");
  return { resolver, helpers, map, setter };
}

/** Locate the installed assignment API so fallback is tested with real map state. */
function isMapSetter(fn, name) {
  if (fn.type !== "FunctionDeclaration" || fn.async || fn.params.length !== 1
      || fn.params[0].type !== "Identifier" || fn.body.body.length !== 1) return false;
  const assignment = fn.body.body[0].expression;
  return assignment?.type === "AssignmentExpression" && assignment.operator === "="
    && assignment.left.type === "Identifier" && assignment.right.type === "Identifier"
    && assignment.left.name === name && assignment.right.name === fn.params[0].name;
}

/** Fault only copied source strings, never installed package or generated HTML files. */
function sourceFault(source, fault) {
  if (!fault) return source;
  const parts = resolverParts(source);
  const target = { "missing-resolver": parts.resolver, "missing-helper": parts.helpers[0],
    "missing-map": parts.map, "missing-map-setter": parts.setter }[fault];
  if (target) return source.slice(0, target.start) + source.slice(target.end);
  if (fault === "ambiguous-resolver") {
    return source + "\n" + source.slice(parts.resolver.start, parts.resolver.end)
      .replace(`function ${parts.resolver.id.name}(`, "function TEST_duplicate_resolver(");
  }
  if (fault === "unexpected-dependency") {
    const at = parts.helpers[0].body.start + 1;
    return source.slice(0, at) + "TEST_FORBIDDEN();" + source.slice(at);
  }
  throw new Error("Unknown TEST source fault");
}

/** Execute exact dependency bytes without evaluating any Studio bootstrap code. */
function resolverScope(source) {
  const { resolver, helpers, map, setter } = resolverParts(source);
  const code = [map, ...helpers, resolver, setter].map(node => source.slice(node.start, node.end)).join("\n");
  parse(code, { ecmaVersion: "latest", sourceType: "script" });
  const scope = vm.createContext({});
  vm.runInContext(code + `\nglobalThis.resolve = ${resolver.id.name};globalThis.setSources = ${setter.id.name};`,
    scope, { timeout: 1000 });
  return scope;
}

/** Model only the original fixture's mount and MutationObserver notification leaf. */
function probe(input, scope) {
  const doc = parseHTML(input.html).document, host = doc.getElementById("gfx-01");
  host.setAttribute("data-composition-file", "compositions/one.html");
  host.removeAttribute("data-composition-src");
  host.innerHTML = '<div id="inner"><span id="copy">Words</span></div><div id="nested" data-composition-file="compositions/nested.html"></div>';
  const initial = scope.resolve(host).sourceFile;
  if (input.mode === "bad-id") host.setAttribute("data-hf-id", "someone-else");
  if (input.mode === "bad-file") host.setAttribute("data-composition-file", "compositions/unknown.html");
  const script = [...doc.querySelectorAll("script")].find(el => el.textContent.includes("const bindings ="));
  const errors = []; let observer;
  const context = { document: doc, console: { error: message => errors.push(message) }, window: {},
    gsap: { timeline: () => ({ to() {} }) },
    MutationObserver: class { constructor(callback) { observer = callback; } observe() {} } };
  vm.runInNewContext(script.textContent, context, { timeout: 1000 });
  const inner = scope.resolve(doc.getElementById("copy")).sourceFile;
  const nested = scope.resolve(doc.getElementById("nested")).sourceFile;
  const late = doc.createElement("div"); host.appendChild(late); observer(); observer();
  const mapped = doc.createElement("div"); mapped.setAttribute("data-composition-id", "TEST-mapped");
  doc.body.appendChild(mapped);
  scope.setSources(new Map([["TEST-mapped", "compositions/mapped.html"]]));
  return { initial, host: scope.resolve(host).sourceFile, inner, nested,
    compositionSrc: host.getAttribute("data-composition-file"), late: scope.resolve(late).sourceFile,
    errors, timing: [host.getAttribute("data-start"), host.getAttribute("data-duration")],
    script: script.textContent, mapped: scope.resolve(mapped, "wrong-fallback.html").sourceFile };
}

const input = JSON.parse(fs.readFileSync(0, "utf8"));
const source = sourceFault(installedSource(fs.realpathSync(process.argv[2])), input.fault);
process.stdout.write(JSON.stringify(probe(input, resolverScope(source))));
