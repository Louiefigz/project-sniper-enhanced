/** Sequential native QC phases; preserve the existing capture schedule and session/resource bounds. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {nativeCaptureQcPoints} from './native_short_capture.mjs';
import {encodeSamples} from './native_long_capture.mjs';
import {reuseNativeForwardQc} from './native_forward_qc.mjs';
import {checkTypography,visualState} from './native_short_capture_checks.mjs';
import {qcCompilerSdk,compilerPins} from './native_short_qc_compiler.mjs';
import {createNativeCaptureContext,prepareNativeCaptureContext,withNativeCaptureSession,captureNativeFrame,
  nativeCaptureBatches,nativeCaptureEvidence,nativeCaptureFailure} from './native_short_capture_context.mjs';
import {readQcRecord,writeQcRecord,qcIdentity,jsonHash,verifyQcImage,verifyLegacyForwardAbsence,
  verifyReverseRow,verifyQcSession} from './native_short_qc_records.mjs';

const PHASE_SESSIONS=48;
const MAX_CHUNKS=128;
const rootFor=request=>path.join(request.output,'native-qc-phases');
const scheduleFor=request=>path.join(rootFor(request),'schedule.json');
const chunkFor=(request,index)=>path.join(rootFor(request),`chunk-${String(index).padStart(3,'0')}`);

/** Prepare unchanged primitives; only validated legacy absence can select original full replay. */
async function prepare(request, work, dependencies) {
  assert.equal(request.captureMode,'cached-native-batches','Phased QC requires cached native batches');
  const context=await createNativeCaptureContext(request,work,dependencies.sdk);
  context.sdk=qcCompilerSdk(context,dependencies.compiler);
  await prepareNativeCaptureContext(context);
  const maximum=context.batchPlan.maximumFrames;
  const points=nativeCaptureQcPoints(context.plan,true,maximum);
  const forwardCount=points.indexOf(context.plan.canvas.totalFrames-1)+1;
  const forward=reuseNativeForwardQc(context,points.slice(0,forwardCount));
  if(!forward)verifyLegacyForwardAbsence(context);
  if(!forward?.frames)return {context,forward,
    ineligible:maximum===1?'single-frame-session':'forward-evidence-unavailable'};
  context.publishCompiler?.();
  const groups=nativeCaptureBatches(points.slice(forwardCount),maximum-1)
    .map((frames,index)=>({index,frames}));
  const chunks=Array.from({length:Math.ceil(groups.length/PHASE_SESSIONS)},(_,index)=>
    groups.slice(index*PHASE_SESSIONS,(index+1)*PHASE_SESSIONS));
  assert.ok(chunks.length>0&&chunks.length<=MAX_CHUNKS,'Invalid bounded native QC chunk count');
  const schedule={schemaVersion:1,kind:'native-qc-phase-schedule',identity:qcIdentity(context,forward),
    compiler:context.compiler,
    expectedCapturePoints:points,forwardCount,maximumSessionsPerChunk:PHASE_SESSIONS,
    chunkCount:chunks.length,chunks};
  return {context,forward,schedule};
}

/** A plan is an exclusive schedule, not an assertion that reverse or encoded checks passed. */
export async function planNativeShortQc(request, dependencies={}) {
  const root=rootFor(request);fs.mkdirSync(root);
  try {
    const prepared=await prepare(request,path.join(root,'plan'),dependencies);
    if(prepared.ineligible)return {status:'native-qc-phases-ineligible',reason:prepared.ineligible};
    const scheduleSha256=writeQcRecord(scheduleFor(request),prepared.schedule);
    return {status:'native-qc-phases-planned',chunkCount:prepared.schedule.chunkCount,scheduleSha256,
      compilerPins:compilerPins(prepared.context)};
  }catch(error){
    writeQcRecord(path.join(root,'plan-error.json'),{status:'failed',error:nativeCaptureFailure(error)});
    throw error;
  }
}

/** Validate the caller's pinned schedule before preparing any chunk or finish context. */
function pinnedSchedule(request, expectedScheduleSha256) {
  assert.match(expectedScheduleSha256??'',/^[a-f0-9]{64}$/,'Expected schedule SHA256 is required');
  return readQcRecord(scheduleFor(request),expectedScheduleSha256).value;
}

/** Copy each actual capture before its scratch filename can be reused. */
function keepImage(row, destination) {
  fs.copyFileSync(row.path,destination,fs.constants.COPYFILE_EXCL);
  const kept={...row,path:destination};verifyQcImage(kept,destination);return kept;
}

async function inspect(context, session, spec, baseline) {
  const captured=await captureNativeFrame(context,session,spec.frame);
  const row=keepImage(captured,spec.path),state=await visualState(session.page);
  assert.deepEqual(state,baseline.visualState,`Reverse seek changed scene state at ${spec.frame}`);
  assert.deepEqual(row.payload,baseline.payload,`Reverse seek changed source frames at ${spec.frame}`);
  const typography=await checkTypography(session.page,spec.frame,context.plan);
  return {...row,repeat:true,byteIdentical:row.sha256===baseline.sha256,visualState:state,typography,
    typographyEvidence:{status:'passed',observedSha256:jsonHash(typography)}};
}

async function captureGroup(prepared, group, receipt, directory) {
  const {context,forward}=prepared,session={...group,startedAt:new Date().toISOString()};
  receipt.sessions.push(session);
  const baseline=new Map(forward.frames.map(row=>[row.frame,row]));
  await withNativeCaptureSession(context,{framesDir:path.join(directory,'frames'),receipt:session},async active=>{
    const seed=await captureNativeFrame(context,active,context.plan.canvas.totalFrames-1);
    session.reverseSeed=keepImage(seed,path.join(directory,`reverse-seed-${group.index}.jpg`));
    for(const frame of group.frames){
      const offset=receipt.occurrenceStart+receipt.frames.length;
      receipt.frames.push(await inspect(context,active,{frame,path:path.join(directory,`pose-${offset}.jpg`)},baseline.get(frame)));
    }
  });
  session.status='captured-and-disposed';session.finishedAt=new Date().toISOString();
  verifyQcSession(context,session,group,directory);
}

/** One child owns whole fresh-session groups; an interrupted child never publishes a passing receipt. */
export async function captureNativeShortQcChunk(request, selection, dependencies={}) {
  const {index,expectedScheduleSha256}=selection,schedule=pinnedSchedule(request,expectedScheduleSha256);
  assert.ok(Number.isSafeInteger(index)&&index>=0&&index<schedule.chunkCount,'Invalid QC chunk index');
  const directory=chunkFor(request,index);fs.mkdirSync(directory);
  const before=schedule.chunks.slice(0,index).flatMap(groups=>groups.flatMap(group=>group.frames)).length;
  const receipt={schemaVersion:1,kind:'native-qc-phase-chunk',status:'failed',index,
    scheduleSha256:expectedScheduleSha256,occurrenceStart:schedule.forwardCount+before,frames:[],sessions:[]};
  try {
    const prepared=await prepare(request,path.join(directory,'context'),{...dependencies,compiler:schedule.compiler});
    assert.ok(!prepared.ineligible,'Planned native QC eligibility changed');
    assert.deepEqual(prepared.schedule,schedule,'QC inputs or schedule changed');
    for(const group of schedule.chunks[index])await captureGroup(prepared,group,receipt,directory);
    assert.deepEqual(receipt.frames.map(row=>row.frame),schedule.chunks[index].flatMap(group=>group.frames));
    assert.deepEqual(qcIdentity(prepared.context,prepared.forward),schedule.identity,'QC inputs changed during capture');
    pinnedSchedule(request,expectedScheduleSha256);receipt.status='native-qc-chunk-complete';
  }catch(error){receipt.error=nativeCaptureFailure(error);}
  const receiptSha256=writeQcRecord(path.join(directory,'receipt.json'),receipt);
  return {status:receipt.status,index,receiptSha256,...(receipt.error?{error:receipt.error}:{})};
}

function verifyChunk(prepared, chunk, index, directory) {
  const {context,schedule,forward}=prepared,expected=schedule.chunks[index];
  assert.equal(chunk.status,'native-qc-chunk-complete','QC chunk incomplete');assert.equal(chunk.index,index);
  const start=schedule.forwardCount+schedule.chunks.slice(0,index).flatMap(groups=>groups.flatMap(group=>group.frames)).length;
  assert.equal(chunk.occurrenceStart,start,'QC chunk occurrence offset differs');
  assert.deepEqual(chunk.frames.map(row=>row.frame),expected.flatMap(group=>group.frames),'QC chunk omitted or reordered occurrences');
  assert.equal(chunk.sessions.length,expected.length,'QC chunk session inventory differs');
  chunk.sessions.forEach((session,offset)=>verifyQcSession(context,session,expected[offset],directory));
  const baseline=new Map(forward.frames.map(row=>[row.frame,row]));
  chunk.frames.forEach((row,offset)=>verifyReverseRow(context,row,baseline.get(row.frame),path.join(directory,`pose-${start+offset}.jpg`)));
}

/** Aggregate only complete byte-verified chunks, then expose the unchanged final QC read contract. */
export async function finishNativeShortQc(request, expectedScheduleSha256, dependencies={}) {
  const schedule=pinnedSchedule(request,expectedScheduleSha256);
  const prepared=await prepare(request,path.join(rootFor(request),'finish'),{...dependencies,compiler:schedule.compiler});
  assert.ok(!prepared.ineligible,'Planned native QC eligibility changed');
  assert.deepEqual(prepared.schedule,schedule,'QC finish inputs or schedule changed');
  const frames=[...prepared.forward.frames],sessions=[],chunks=[];
  for(let index=0;index<schedule.chunkCount;index++){
    const directory=chunkFor(request,index),file=path.join(directory,'receipt.json');
    const {value:chunk,sha256}=readQcRecord(file);
    assert.equal(chunk.scheduleSha256,expectedScheduleSha256,'QC chunk belongs to another schedule');
    assert.equal(chunk.schemaVersion,1);assert.equal(chunk.kind,'native-qc-phase-chunk');
    verifyChunk(prepared,chunk,index,directory);
    frames.push(...chunk.frames);sessions.push(...chunk.sessions);chunks.push({file,sha256});
  }
  assert.deepEqual(frames.map(row=>row.frame),schedule.expectedCapturePoints,'Native QC omitted or reordered a capture occurrence');
  for(const chunk of chunks)assert.equal(readQcRecord(chunk.file).sha256,chunk.sha256,'QC receipt changed during finish');
  pinnedSchedule(request,expectedScheduleSha256);
  assert.deepEqual(qcIdentity(prepared.context,prepared.forward),schedule.identity,'QC finish inputs changed');
  const receipt={scope:'native-render-reference-and-reverse-seek-check',fromEncodedOutput:false,
    status:'native-references-and-seek-states-pass',project:request.project,referenceEncoding:'jpeg95-matching-opaque-render',
    sessionMode:'bounded-fresh-native-sessions',frames,sessions,failedSceneStates:[],fonts:[],
    ...nativeCaptureEvidence(prepared.context),expectedCapturePoints:schedule.expectedCapturePoints,
    forwardReuse:prepared.forward.evidence,transport:{sessions:sessions.map(row=>row.transport),errors:0},
    phaseEvidence:{schedule:scheduleFor(request),scheduleSha256:expectedScheduleSha256,chunks}};
  await encodeSamples(prepared.context,receipt,dependencies.encode);
  const sha256=writeQcRecord(path.join(request.output,'native-frames.json'),receipt);
  return {status:receipt.status,occurrences:frames.length,sessions:sessions.length,sha256};
}

/** Strict phase CLI; the caller retains 180-second child and original outer owner deadlines. */
export async function nativeShortQcPhaseCli(args) {
  const [file,command,...rest]=args,request=readQcRecord(file).value;
  if(command==='plan'){
    assert.equal(rest.length,0,'plan does not accept a schedule digest');return planNativeShortQc(request);
  }
  const options=command==='chunk'?rest.slice(1):rest;
  assert.deepEqual(options.slice(0,1),['--schedule-sha256']);assert.equal(options.length,2);
  assert.match(options[1],/^[a-f0-9]{64}$/,'Expected schedule SHA256 is required');
  if(command==='finish')return finishNativeShortQc(request,options[1]);
  assert.equal(command,'chunk','Unknown native QC phase');assert.match(rest[0]??'',/^(0|[1-9]\d*)$/);
  return captureNativeShortQcChunk(request,{index:Number(rest[0]),expectedScheduleSha256:options[1]});
}

if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url){
  try {
    const result=await nativeShortQcPhaseCli(process.argv.slice(2));console.log(JSON.stringify(result));
    if(result.status==='failed')process.exitCode=1;
  }catch(error){console.error(nativeCaptureFailure(error));process.exitCode=1;}
}
