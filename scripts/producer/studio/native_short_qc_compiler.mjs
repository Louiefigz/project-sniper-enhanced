/** Reuse one real compile within one pinned run; source admission and captures remain unchanged. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {serialize,deserialize} from 'node:v8';
import {fileURLToPath} from 'node:url';
import {nativeCaptureHash} from './native_short_capture_context.mjs';
import {readQcRecord,writeQcRecord,readQcBytes,writeQcBytes,jsonHash} from './native_short_qc_records.mjs';

const HERE=path.dirname(fileURLToPath(import.meta.url));
const MAX_FILES=4094;
const planRoot=context=>path.join(context.request.output,'native-qc-phases/plan');
const receiptPath=context=>path.join(planRoot(context),'compiler-result.json');
const payloadPath=context=>path.join(planRoot(context),'compiler-result.bin');

/** Public V8 serialization preserves Maps, undefined, shared references and compiler cfg effects. */
export function serializeCompilerResult(value) {
  verifyCompilerProperties(value);
  const bytes=serialize(value);
  assert.ok(bytes.length<=32*1024*1024,'Compiler result exceeds its serialized size bound');
  assert.deepEqual(deserialize(bytes),value,'Compiler serialization changed its result');
  return bytes;
}

function compilerChildren(value) {
  const prototype=Object.getPrototypeOf(value),array=Array.isArray(value);
  assert.ok([Object.prototype,Array.prototype,Map.prototype,Set.prototype,null].includes(prototype),'Unsupported compiler prototype');
  const children=[];
  for(const key of Reflect.ownKeys(value)){
    if(array&&key==='length')continue;
    const descriptor=Object.getOwnPropertyDescriptor(value,key);
    assert.ok(typeof key==='string'&&descriptor.enumerable&&descriptor.writable&&descriptor.configurable
      &&Object.hasOwn(descriptor,'value'),'Unsupported compiler property descriptor');
    children.push(descriptor.value);
  }
  if(value instanceof Map||value instanceof Set){
    assert.equal(children.length,0,'Compiler collection has custom properties');
    return value instanceof Map?[...value].flat():[...value];
  }
  return children;
}

function verifyCompilerProperties(value) {
  const pending=[value],seen=new Set();
  while(pending.length){
    const item=pending.pop();if(item===null||typeof item!=='object'||seen.has(item))continue;
    seen.add(item);assert.ok(seen.size<=100000,'Compiler graph exceeds its node bound');
    pending.push(...compilerChildren(item));
  }
}

function inventoryEntry(root, relative, state) {
  const file=path.join(root,relative),stat=fs.lstatSync(file);
  assert.ok(!stat.isSymbolicLink(),'Compiler dependency is a symlink');
  if(stat.isDirectory()){state.directories.push(relative);state.pending.push(relative);return;}
  assert.ok(stat.isFile(),'Compiler dependency is not a regular file');state.files.push(relative);
}

/** Capture every file and empty directory; local server fallbacks cannot gain unpinned assets. */
function inventory(root) {
  assert.equal(fs.realpathSync(root),root,'Compiler directory is not canonical');
  const state={files:[],directories:[],pending:['']};
  while(state.pending.length){
    const relative=state.pending.pop();
    for(const name of fs.readdirSync(path.join(root,relative)))inventoryEntry(root,path.join(relative,name),state);
    assert.ok(state.files.length<=MAX_FILES&&state.directories.length<=MAX_FILES,'Compiler inventory exceeds its bound');
  }
  return {files:state.files.sort(),directories:state.directories.sort()};
}

function checkedFile(file, expected) {
  const before=fs.lstatSync(file,{bigint:true});
  assert.ok(before.isFile()&&!before.isSymbolicLink()&&fs.realpathSync(file)===file,'Compiler input is not a canonical regular file');
  const sha256=nativeCaptureHash(file),after=fs.lstatSync(file,{bigint:true});
  const identity=stat=>[stat.dev,stat.ino,stat.size,stat.mtimeNs,stat.ctimeNs];
  assert.deepEqual(identity(before),identity(after),'Compiler file changed while hashing');
  if(expected!==undefined)assert.equal(sha256,expected,`Compiler dependency changed: ${file}`);
  return sha256;
}

function inputPaths(context, result) {
  const project=inventory(context.project),files=new Set(project.files.map(name=>path.join(context.project,name)));
  Object.keys(context.request.pins??{}).forEach(file=>files.add(file));files.add(fs.realpathSync(process.execPath));
  for(const name of ['native_short_qc_compiler.mjs','native_short_qc_phase.mjs','native_short_qc_records.mjs'])files.add(path.join(HERE,name));
  for(const name of ['cli.js','native-capture-library.mjs'])files.add(path.join(context.runtime,'dist',name));
  const external=result?.compiled?.externalAssets;
  if(external!==undefined){
    assert.ok(external instanceof Map,'Compiler externalAssets must remain a Map');
    for(const file of external.values())addExternalInput(files,file,planRoot(context));
  }
  return {project,files:[...files].sort()};
}

function addExternalInput(files, file, root) {
  assert.ok(typeof file==='string'&&path.isAbsolute(file),'Invalid compiler external asset path');
  if(!file.startsWith(root+path.sep))files.add(file);
}

function verifyExternalWork(record, result) {
  for(const file of result.compiled?.externalAssets?.values()??[]){
    if(!file.startsWith(record.originalWorkDir+path.sep))continue;
    const relative=path.relative(record.originalWorkDir,file);
    assert.ok(record.work.files.includes(relative),'Compiler external work dependency is missing');
    assert.equal(ownedPath(record.originalWorkDir,relative),file,'Noncanonical compiler work dependency');
  }
}

function compileSignature(input) {
  const values={...input};delete values.workDir;delete values.log;delete values.assertNotAborted;
  return values;
}

function ownedPath(root, relative) {
  assert.ok(typeof relative==='string'&&!path.isAbsolute(relative),'Invalid compiler relative path');
  const file=path.join(root,relative);
  assert.ok(file.startsWith(root+path.sep)&&path.relative(root,file)===relative,'Compiler file escaped its root');return file;
}

function verifyWork(record, root) {
  const actual={files:[],directories:[]};
  const roots=[...new Set([...record.work.files,...record.work.directories].map(name=>name.split(path.sep)[0]))].sort();
  for(const relative of roots){
    const file=ownedPath(root,relative);
    if(!record.work.directories.includes(relative)){checkedFile(file,record.workPins[relative]);actual.files.push(relative);continue;}
    const nested=inventory(file);actual.directories.push(relative,...nested.directories.map(name=>path.join(relative,name)));
    actual.files.push(...nested.files.map(name=>path.join(relative,name)));
  }
  actual.files.sort();actual.directories.sort();assert.deepEqual(actual,record.work,'Compiler output inventory changed');
  for(const relative of record.work.files)checkedFile(ownedPath(root,relative),record.workPins[relative]);
}

function validateInputs(context, record, result) {
  const inputs=inputPaths(context,result);
  assert.deepEqual(inputs.project,record.projectInventory,'Compiler project inventory changed');
  assert.deepEqual(inputs.files,Object.keys(record.inputPins),'Compiler dependency inventory changed');
  for(const [file,sha256] of Object.entries(record.inputPins))checkedFile(file,sha256);
}

function validateRecord(context, authority) {
  assert.equal(authority.path,receiptPath(context),'Compiler receipt must belong to this run');
  const {value:record}=readQcRecord(authority.path,authority.sha256);
  assert.equal(record.schemaVersion,1);assert.equal(record.kind,'native-qc-compiler-result');
  assert.equal(record.requestSha256,jsonHash(context.request),'Compiler request changed');
  assert.equal(record.originalWorkDir,planRoot(context),'Compiler work directory changed');
  assert.equal(record.payload.path,payloadPath(context),'Compiler payload escaped its run');
  checkedFile(record.payload.path,record.payload.sha256);
  const decoded=deserialize(readQcBytes(record.payload.path,record.payload.sha256).bytes);
  validateInputs(context,record,decoded.result);
  assert.ok(record.work.files.length<=MAX_FILES&&record.work.files.includes('compiled/index.html'),'Invalid compiler file manifest');
  assert.deepEqual(Object.keys(record.workPins),record.work.files,'Compiler output digest inventory changed');
  verifyExternalWork(record,decoded.result);verifyWork(record,record.originalWorkDir);return {record,decoded};
}

function copyCompiled(record, destination) {
  assert.equal(fs.realpathSync(destination),destination,'Compiler destination is not canonical');
  assert.deepEqual(fs.readdirSync(destination),[],'Compiler replay requires an empty destination');
  for(const relative of record.work.directories){
    const target=ownedPath(destination,relative);
    assert.equal(fs.realpathSync(path.dirname(target)),path.dirname(target),'Compiler parent escaped its root');fs.mkdirSync(target);
  }
  for(const relative of record.work.files){
    const source=ownedPath(record.originalWorkDir,relative),target=ownedPath(destination,relative);
    assert.equal(fs.realpathSync(path.dirname(target)),path.dirname(target),'Compiler parent escaped its root');
    checkedFile(source,record.workPins[relative]);fs.copyFileSync(source,target,fs.constants.COPYFILE_EXCL);
  }
  verifyWork(record,destination);
}

function attachEvidence(context, authority) {
  context.compiler=authority;
  context.verifyCompiler=()=>{
    const {record}=validateRecord(context,authority);
    if(context.work!==record.originalWorkDir)verifyWork(record,context.work);
  };
}

function publishCompile(context, prepared) {
  if(prepared.error)throw prepared.error;
  const {signature,payload,work,before}=prepared;
  const decoded=deserialize(payload),inputs=inputPaths(context,decoded.result);
  assert.deepEqual(inputs.project,before.project,'Project changed during compilation');
  for(const [file,sha256] of Object.entries(prepared.beforePins))checkedFile(file,sha256);
  const inputPins=Object.fromEntries(inputs.files.map(file=>[file,checkedFile(file,context.request.pins?.[file])]));
  assert.ok(work.files.includes('compiled/index.html'),'Compiler did not publish its index');
  const record={schemaVersion:1,kind:'native-qc-compiler-result',requestSha256:jsonHash(context.request),
    originalWorkDir:context.work,projectInventory:inputs.project,inputPins,work,workPins:prepared.workPins,
    payload:{path:payloadPath(context),sha256:writeQcBytes(payloadPath(context),payload)}};
  assert.deepEqual(decoded.signature,deserialize(signature),'Compiler signature changed');
  verifyExternalWork(record,decoded.result);verifyWork(record,context.work);
  const authority={path:receiptPath(context),sha256:writeQcRecord(receiptPath(context),record)};
  attachEvidence(context,authority);
}

async function recordCompile(context, input, sdk) {
  assert.equal(input.workDir,planRoot(context),'Compiler publication requires the current plan directory');
  const prepared={};
  // Compatibility eligibility must survive unsupported serialization; eligible publication fails closed.
  try {
    prepared.signature=serializeCompilerResult(compileSignature(input));prepared.before=inputPaths(context);
    prepared.beforePins=Object.fromEntries(prepared.before.files.map(file=>[file,checkedFile(file,context.request.pins?.[file])]));
  }catch(error){prepared.error=error;}
  const result=await sdk.runCompileStage(input);
  try {
    prepared.work=inventory(input.workDir);
    prepared.workPins=Object.fromEntries(prepared.work.files.map(file=>[file,checkedFile(ownedPath(input.workDir,file))]));
    if(!prepared.error)prepared.payload=serializeCompilerResult({result,cfg:input.cfg,signature:deserialize(prepared.signature)});
  }catch(error){prepared.error??=error;}
  context.publishCompiler=()=>publishCompile(context,prepared);return result;
}

function replayCompile(context, input, authority) {
  const {record,decoded}=validateRecord(context,authority);
  assert.deepEqual(compileSignature(input),decoded.signature,'Compiler parameters/configuration changed');
  copyCompiled(record,input.workDir);
  input.cfg=decoded.cfg;context.cfg=decoded.cfg;
  attachEvidence(context,authority);return decoded.result;
}

/** Substitute only the compiler call; exact source/cache/metadata and every capture still execute. */
export function qcCompilerSdk(context, authority) {
  const sdk=context.sdk;
  return {...sdk,runCompileStage:async input=>authority?replayCompile(context,input,authority):recordCompile(context,input,sdk)};
}

/** Live parent pins both serialization files and all immutable compiler artifacts through finish. */
export function compilerPins(context) {
  const {record}=validateRecord(context,context.compiler);
  return {[context.compiler.path]:context.compiler.sha256,[record.payload.path]:record.payload.sha256,
    ...Object.fromEntries(record.work.files.map(file=>[ownedPath(record.originalWorkDir,file),record.workPins[file]]))};
}
