/** Bound phase evidence to unchanged native inputs, exact occurrences and real local files. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {nativeCaptureHash,nativeCaptureEvidence} from './native_short_capture_context.mjs';

const HERE=path.dirname(fileURLToPath(import.meta.url));
const MAX_BYTES=32*1024*1024;
const CODE=['native_short_qc_phase.mjs','native_short_qc_records.mjs','native_short_qc_compiler.mjs','native_short_capture.mjs',
  'native_short_capture_context.mjs','native_short_capture_checks.mjs','native_forward_qc.mjs'];
export const jsonHash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');

/** Only regular bounded files are evidence; check the open file and its pathname identity. */
export function readQcBytes(file, expected) {
  if(expected!==undefined)assert.match(expected,/^[a-f0-9]{64}$/,'Expected schedule SHA256 is required');
  const identity=stat=>[stat.dev,stat.ino,stat.size,stat.mtimeNs,stat.ctimeNs];
  const before=fs.lstatSync(file,{bigint:true});
  assert.ok(before.isFile()&&!before.isSymbolicLink()&&before.size<=BigInt(MAX_BYTES),'Invalid bounded QC receipt');
  const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
  let bytes;
  try {
    assert.deepEqual(identity(fs.fstatSync(fd,{bigint:true})),identity(before),'QC receipt changed before open');
    bytes=Buffer.alloc(Number(before.size)+1);let count=0,read;
    while(count<bytes.length&&(read=fs.readSync(fd,bytes,count,bytes.length-count,null))>0)count+=read;
    assert.equal(count,Number(before.size),'QC receipt changed size');bytes=bytes.subarray(0,count);
    assert.deepEqual(identity(fs.fstatSync(fd,{bigint:true})),identity(before),'QC receipt changed during read');
    assert.deepEqual(identity(fs.lstatSync(file,{bigint:true})),identity(before),'QC receipt path changed');
  }finally{fs.closeSync(fd);}
  const sha256=createHash('sha256').update(bytes).digest('hex');
  if(expected!==undefined)assert.equal(sha256,expected,'QC schedule digest differs');
  return {bytes,sha256};
}

/** Decode bounded JSON only after verifying the exact file bytes. */
export function readQcRecord(file, expected) {
  const {bytes,sha256}=readQcBytes(file,expected);
  const value=JSON.parse(bytes.toString('utf8'));
  assert.ok(value&&typeof value==='object'&&!Array.isArray(value),'QC receipt must be an object');
  return {value,sha256};
}

/** Publish an exclusive, flushed receipt; no partial file ever receives a passing status. */
export function writeQcBytes(file, bytes) {
  assert.ok(Buffer.byteLength(bytes)<=MAX_BYTES,'QC receipt exceeds 32 MiB');
  const fd=fs.openSync(file,'wx',0o600);
  try {fs.writeFileSync(fd,bytes);fs.fsyncSync(fd);}finally{fs.closeSync(fd);}
  return nativeCaptureHash(file);
}

export function writeQcRecord(file, value) {
  return writeQcBytes(file,JSON.stringify(value,null,2));
}

/** Bind current compiled/source/checker bytes and the independently verified forward authority. */
export function qcIdentity(context, forward) {
  context.verifyCompiler?.();
  return {requestSha256:jsonHash(context.request),evidence:stableCaptureEvidence(context),compiler:context.compiler,
    projectSha256:nativeCaptureHash(path.join(context.project,'SHORT-PROJECT.json')),
    pictureSha256:nativeCaptureHash(path.join(context.request.output,'picture.mp4')),
    code:Object.fromEntries(CODE.map(name=>[name,nativeCaptureHash(path.join(HERE,name))])),
    forwardAuthority:forward.evidence};
}

/** Cache admission is repeated; its observation clock/SDK timing is not source identity. */
function stableCaptureEvidence(context) {
  const evidence=nativeCaptureEvidence(context),acquired=evidence.sourceCacheAcquisition;
  if(!acquired)return evidence;
  const entries=acquired.entries.map(entry=>{
    const row={...entry};delete row.startedAt;delete row.sdkResult;return row;
  });
  return {...evidence,sourceCacheAcquisition:{...acquired,entries}};
}

/** Absence is a compatibility route only; an existing malformed or changed receipt is an error. */
export function verifyLegacyForwardAbsence(context) {
  const root=context.request.pictureDonor??context.request.output,file=path.join(root,'batched-picture.json');
  if(!fs.existsSync(file)){
    assert.ok(!context.request.pictureDonor,'Validated picture donor receipt is missing');return;
  }
  const {value:picture,sha256}=readQcRecord(file);
  assert.ok(!Object.hasOwn(picture,'forwardQc'),'Present forward authority cannot select legacy replay');
  if(context.request.pictureDonor)assert.equal(context.request.pins[file],sha256,'Legacy donor receipt is not pinned');
  assert.equal(picture.status,'picture-encoded-awaiting-parent-qc','Legacy picture is incomplete');
  assert.equal(picture.pictureMode,'cached-native-batches');assert.equal(picture.project,context.project);
  assert.equal(picture.referenceEncoding,'jpeg95-matching-opaque-render');
  for(const key of ['sourceHtmlSha256','compiledSha256','runtimeLibrarySha256','batchPlan']){
    assert.deepEqual(picture[key],context[key],`Legacy picture ${key} differs`);
  }
  assert.equal(picture.frameRate,context.plan.canvas.frameRate);
  assert.equal(picture.totalFrames,context.plan.canvas.totalFrames);assert.equal(picture.encodeResult.exitCode,0);
  assert.equal(picture.output,path.join(root,'picture.mp4'));
  assert.equal(picture.sha256,nativeCaptureHash(picture.output),'Legacy picture changed');
  assert.equal(picture.sha256,nativeCaptureHash(path.join(context.request.output,'picture.mp4')),'Current picture differs');
  assert.deepEqual(picture.frames.map(row=>row.frame),Array.from({length:context.plan.canvas.totalFrames},(_,i)=>i));
  assert.equal(readQcRecord(file).sha256,sha256,'Legacy picture receipt changed');
}

/** Screenshots must be the regular files at the exact owned output paths. */
export function verifyQcImage(row, expectedPath) {
  assert.equal(row.path,expectedPath,'QC screenshot path differs');
  const stat=fs.lstatSync(expectedPath);
  assert.ok(stat.isFile()&&!stat.isSymbolicLink()&&stat.size>0,'QC image is not a regular file');
  assert.equal(fs.realpathSync(expectedPath),expectedPath,'QC image escaped the owned directory');
  assert.match(row.sha256,/^[a-f0-9]{64}$/);
  assert.equal(nativeCaptureHash(expectedPath),row.sha256,'QC image bytes changed');
}

/** Recheck measured font/image/source observations; new assertions do not replace capture checks. */
function verifyObserved(context, row) {
  assert.equal(row.time,row.frame/context.rate,'QC occurrence time differs');
  const active=context.lookup.getActiveFramePayloads(row.time);
  const payload=[...active].map(([id,value])=>({id,frameIndex:value.frameIndex,
    sha256:nativeCaptureHash(value.framePath),path:value.framePath}));
  assert.deepEqual(row.payload,payload,'QC source payload differs');
  assert.ok(row.observed.fonts.length>0&&row.observed.fonts.every(font=>font.status==='loaded'));
  for(const source of payload)assert.ok(row.observed.images.some(image=>image.id===source.id&&image.loaded));
}

/** Every reverse occurrence retains exact state/payload equality and its measured typography. */
export function verifyReverseRow(context, row, baseline, expectedPath) {
  verifyQcImage(row,expectedPath);verifyObserved(context,row);
  assert.equal(row.repeat,true,'Reverse occurrence lost its repeated flag');
  assert.equal(row.byteIdentical,row.sha256===baseline.sha256,'Incorrect byte-identity evidence');
  assert.deepEqual(row.visualState,baseline.visualState,'Reverse seek changed scene state');
  assert.deepEqual(row.payload,baseline.payload,'Reverse seek changed source frames');
  assert.ok(row.typography&&typeof row.typography==='object','Missing measured typography');
  assert.equal(row.typographyEvidence?.status,'passed','Typography check did not pass');
  assert.equal(row.typographyEvidence.observedSha256,jsonHash(row.typography),'Typography evidence changed');
}

/** A phase is eligible only after every native session and original-media guard was disposed. */
export function verifyQcSession(context, session, expected, directory) {
  assert.equal(session.index,expected.index);assert.deepEqual(session.frames,expected.frames);
  assert.equal(session.status,'captured-and-disposed','QC session incomplete');
  assert.ok(session.frames.length+1<=context.batchPlan.maximumFrames,'QC session exceeded its bound');
  for(const key of ['sessionClosed','browserPoolDrained','mediaGuardDisposed','serverClosed'])assert.equal(session[key],true);
  assert.equal(session.transport.errors,0,'QC transport failed');
  assert.equal(session.originalMedia.status,'original-payloads-suppressed');
  assert.equal(session.originalMedia.disposed,true);
  assert.deepEqual(session.originalMedia.unexpectedMedia,[]);assert.deepEqual(session.originalMedia.requestErrors,[]);
  assert.ok(Array.isArray(session.originalMedia.contract)&&session.originalMedia.contract.length>0,'Original media contract is absent');
  for(const row of session.originalMedia.contract){
    assert.equal(row.receivedDataBytes,0);assert.equal(row.receivedEncodedBytes,0);
  }
  const seed=session.reverseSeed;
  assert.equal(seed.frame,context.plan.canvas.totalFrames-1,'Reverse seed differs');
  verifyQcImage(seed,path.join(directory,`reverse-seed-${session.index}.jpg`));verifyObserved(context,seed);
}
