/** Scope standalone page styles using the installed SDK's JavaScript parser. */
import fs from 'node:fs';
import crypto from 'node:crypto';
import { createRequire } from 'node:module';

const local = createRequire(import.meta.url);
const sdk = createRequire(local.resolve('@hyperframes/parsers/package.json'));
const { parse } = sdk('acorn');
const { full } = sdk('acorn-walk');
const LIMIT = 4 * 1024 * 1024;

function pageStyle(node) {
  if (node.type !== 'MemberExpression' || node.computed || node.property.name !== 'style') return false;
  const target = node.object;
  return target.type === 'MemberExpression' && !target.computed
    && ['documentElement', 'body'].includes(target.property.name)
    && target.object.type === 'Identifier' && target.object.name === 'document';
}

function bindsDocument(node) {
  if (node.type === 'VariableDeclarator') return node.id.type === 'Identifier' && node.id.name === 'document';
  if (['FunctionDeclaration', 'FunctionExpression', 'ArrowFunctionExpression'].includes(node.type)) {
    return node.params.some(param => param.type === 'Identifier' && param.name === 'document');
  }
  return node.type === 'CatchClause' && node.param?.type === 'Identifier' && node.param.name === 'document';
}

export function scopeScript(source, rootId) {
  if (typeof source !== 'string' || typeof rootId !== 'string' || !/^[A-Za-z][\w-]*$/.test(rootId)) {
    throw new Error('Invalid composition style scope');
  }
  if (!/document\s*\.\s*(?:documentElement|body)\s*\.\s*style/.test(source)) return source;
  const tree = parse(source, {ecmaVersion: 'latest', sourceType: 'script'}), edits = [];
  let shadowed = false;
  full(tree, node => {
    if (bindsDocument(node)) shadowed = true;
    if (pageStyle(node)) edits.push([node.start, node.end]);
  });
  if (edits.length && shadowed) throw new Error('Composition shadows document while using page styles');
  const replacement = `document.getElementById(${JSON.stringify(rootId)}).style`;
  let result = source;
  for (const [start, end] of edits.sort((a, b) => b[0] - a[0])) {
    result = result.slice(0, start) + replacement + result.slice(end);
  }
  parse(result, {ecmaVersion: 'latest', sourceType: 'script'});
  return result;
}

function readInput() {
  const [file, hash] = process.argv.slice(3);
  if (process.argv.length !== 5 || !/^[a-f0-9]{64}$/.test(hash || '') || fs.realpathSync(file) !== file) {
    throw new Error('Invalid style request reference');
  }
  const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);
  try {
    const before=fs.fstatSync(fd);
    if (!before.isFile() || before.nlink!==1 || before.uid!==process.getuid() || before.size>LIMIT) {
      throw new Error('Invalid bounded style request file');
    }
    const raw=fs.readFileSync(fd),after=fs.fstatSync(fd);
    if (raw.length!==before.size || before.size!==after.size || before.mtimeMs!==after.mtimeMs
      || before.ctimeMs!==after.ctimeMs || crypto.createHash('sha256').update(raw).digest('hex')!==hash) {
      throw new Error('Style request changed');
    }
    return raw;
  } finally { fs.closeSync(fd); }
}

function batch() {
  const raw = readInput();
  const request = JSON.parse(raw.toString('utf8'));
  if (!request || Object.keys(request).sort().join(',') !== 'rootId,scripts'
    || !Array.isArray(request.scripts) || request.scripts.length > 128) {
    throw new Error('Invalid composition style request');
  }
  const result = JSON.stringify({scripts: request.scripts.map(source => scopeScript(source, request.rootId))});
  if (Buffer.byteLength(result) > 2 * LIMIT) throw new Error('Composition style response exceeds8MiB');
  process.stdout.write(result);
}

if (process.argv[2] === '--batch') {
  try { batch(); }
  catch (error) { process.stderr.write(String(error.message)); process.exitCode = 1; }
}
