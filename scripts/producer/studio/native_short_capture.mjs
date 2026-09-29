/** Reuse native compile/capture and the actual render's retained source PNGs. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {assertNativeCaptureOwner} from './runtime/native-export-guard.mjs';
import {reuseNativeForwardQc} from './native_forward_qc.mjs';
import {assertNativeFrameState,capturePoints,readNativeFrameState} from './native_short_capture_checks.mjs';
import {encodeSamples} from './native_long_capture.mjs';
import {compactNativeTypography} from './native_capture_receipt.mjs';
import {importNativeCaptureLibrary,nativeTimingLedger,nativeTimingSummary,timedNativeSdk,timedStep} from './native_capture_timing.mjs';
import {createNativeCaptureContext,prepareNativeCaptureContext,withNativeCaptureSession,captureNativeFrame,
  nativeCaptureHash,nativeCaptureBatches,nativeCaptureEvidence,nativeCaptureFailure,NATIVE_CAPTURE_BATCH_FRAMES} from './native_short_capture_context.mjs';

/** Include both sides of every fresh render-session boundary, forward and backward. */
export function nativeCaptureQcPoints(plan, batched=false, maximum=NATIVE_CAPTURE_BATCH_FRAMES) {
  const points=capturePoints(plan);
  if(!batched)return points;
  nativeCaptureBatches([],maximum); // Shared bound validation, including empty capture inventories.
  const lastForward=points.indexOf(plan.canvas.totalFrames-1),boundaries=[];
  for(let frame=maximum;frame<plan.canvas.totalFrames;frame+=maximum)boundaries.push(frame-1,frame);
  const forward=[...new Set([...points.slice(0,lastForward+1),...boundaries])].sort((left,right)=>left-right);
  const reverse=[...new Set([...points.slice(lastForward+1,-1),...boundaries])].sort((left,right)=>right-left);
  const result=[...forward,...reverse,points.at(-1)];
  assert.ok(result.length<=3000,'Native batched QC exceeds its bounded capture inventory');
  return result;
}

async function inspectFrame(context, session, frame, receipt) {
  const row=await captureNativeFrame(context,session,frame),destination=path.join(context.work,`pose-${receipt.frames.length}.jpg`);
  fs.copyFileSync(row.path,destination,fs.constants.COPYFILE_EXCL);
  // One page read supplies scene state, typography, catalog mounts and checkpoints; checks are unchanged.
  const observed=await timedStep(context.timing,'frameStateRead',()=>readNativeFrameState(session.page,frame,context.plan));
  const prior=receipt.frames.find(previous=>previous.frame===frame),state=observed.visualState;
  if(prior){
    try{assert.deepEqual(state,prior.visualState,`Reverse seek changed scene state at ${frame}`);}
    catch(error){receipt.failedSceneStates.push({frame,error:String(error)});}
    assert.deepEqual(row.payload,prior.payload,`Reverse seek changed source frames at ${frame}`);
  }
  receipt.frames.push({...row,path:destination,repeat:!!prior,byteIdentical:prior?row.sha256===prior.sha256:null,
    visualState:state,typography:assertNativeFrameState(observed,frame,context.plan)});
}

/** Default QC keeps its original single session; explicit batch mode preserves every occurrence. */
export async function runNativeShortCapture(request, dependencies={}) {
  const work=path.join(request.output,'native-capture'),receiptPath=path.join(request.output,'native-frames.json');
  const batched=request.captureMode==='cached-native-batches';
  const receipt={scope:'native-render-reference-and-reverse-seek-check',fromEncodedOutput:false,status:'failed',
    project:request.project,referenceEncoding:'jpeg95-matching-opaque-render',
    sessionMode:batched?'bounded-fresh-native-sessions':'original-single-native-session',
    frames:[],cacheEntries:[],failedSceneStates:[],fonts:[],sessions:[]};
  let context;
  const ledger=nativeTimingLedger();  // Telemetry only: the timed SDK passes every call through unchanged.
  try {
    const sdk=timedNativeSdk(dependencies.sdk??await importNativeCaptureLibrary(request),ledger);
    context=await createNativeCaptureContext(request,work,sdk);context.timing=ledger;
    await timedStep(ledger,'prepare',()=>prepareNativeCaptureContext(context));Object.assign(receipt,nativeCaptureEvidence(context));
    const maximum=context.batchPlan.maximumFrames,points=nativeCaptureQcPoints(context.plan,batched,maximum);
    const forward=points.slice(0,points.indexOf(context.plan.canvas.totalFrames-1)+1);
    const retained=batched?reuseNativeForwardQc(context,forward):null;
    const reused=retained?.frames?retained:null;
    if(retained&&!reused)receipt.forwardReuseUnavailable=retained.evidence;
    if(reused){receipt.frames.push(...reused.frames);receipt.forwardReuse=reused.evidence;}
    const remaining=reused?points.slice(forward.length):points;
    const groups=batched?nativeCaptureBatches(remaining,reused?maximum-1:maximum):[remaining];
    receipt.expectedCapturePoints=points;
    for(const [index,frames] of groups.entries()){
      const session={index,frames,startedAt:new Date().toISOString()};receipt.sessions.push(session);
      await withNativeCaptureSession(context,{framesDir:path.join(work,'frames'),receipt:session},async active=>{
        if(reused){
          const seed=await captureNativeFrame(context,active,context.plan.canvas.totalFrames-1);
          const destination=path.join(work,`reverse-seed-${index}.jpg`);
          fs.copyFileSync(seed.path,destination,fs.constants.COPYFILE_EXCL);
          session.reverseSeed={...seed,path:destination};
        }
        for(const frame of frames)await inspectFrame(context,active,frame,receipt);
      });
      session.status='captured-and-disposed';session.finishedAt=new Date().toISOString();
    }
    assert.deepEqual(receipt.frames.map(row=>row.frame),points,'Native QC omitted or reordered a capture occurrence');
    assert.equal(receipt.failedSceneStates.length,0,JSON.stringify(receipt.failedSceneStates));
    assert.equal(context.sourceHtmlSha256,nativeCaptureHash(path.join(request.project,'index.html')));
    receipt.transport={sessions:receipt.sessions.map(row=>row.transport),errors:0};
    await timedStep(ledger,'encodeSamples',()=>encodeSamples(context,receipt,dependencies.encode));
    compactNativeTypography(receipt);  // Exact per-frame expansion asserted (studio/native_capture_receipt.mjs).
    receipt.status='native-references-and-seek-states-pass';
  }catch(error){receipt.error=nativeCaptureFailure(error);}
  finally{
    if(context)Object.assign(receipt,nativeCaptureEvidence(context));
    receipt.timings=nativeTimingSummary(ledger);
    fs.writeFileSync(receiptPath,JSON.stringify(receipt),{flag:'wx'});
  }
  return receipt;
}

if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url){
  assertNativeCaptureOwner(process.argv[2]);
  const result=await runNativeShortCapture(JSON.parse(fs.readFileSync(process.argv[2],'utf8')));
  if(result.status!=='native-references-and-seek-states-pass')process.exitCode=1;
}
