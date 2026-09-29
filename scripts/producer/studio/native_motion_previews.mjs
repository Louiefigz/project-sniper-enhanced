/** Continuous absolute-time windows through the same native capture and picture encoder. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {assertNativePreviewOwner} from './runtime/native-export-guard.mjs';
import {createNativeCaptureContext,prepareNativeCaptureContext,withNativeCaptureSession,captureNativeFrame,
  nativeCaptureBatches,nativeCaptureHash} from './native_short_capture_context.mjs';
import {nativeBatchEncoderArgs,encodeNativeBatchPicture} from './native_short_batched_render.mjs';
import {prepareSparseLongContext} from './native_segments/sparse_sources.mjs';
import {nativeWindowBatchPlan} from './native_window_batch_plan.mjs';
import {importNativeCaptureLibrary,nativeTimingLedger,nativeTimingSummary,timedNativeSdk,timedStep} from './native_capture_timing.mjs';

/** Validate all retained ranges before any source decode or frame inventory allocation. */
function previewFrameInventory(context,windows) {
  assert.ok(Array.isArray(windows)&&windows.length>0&&windows.length<=768,'Invalid preview window count');
  for(const {startFrame,endFrame} of windows)assert.ok(Number.isSafeInteger(startFrame)&&Number.isSafeInteger(endFrame)
    &&startFrame>=0&&endFrame<=context.plan.canvas.totalFrames&&endFrame>startFrame
    &&(endFrame-startFrame)/context.rate<=12,'Motion preview window exceeds its explicit clock or duration');
  const count=windows.reduce((sum,window)=>sum+window.endFrame-window.startFrame,0);
  assert.ok(count<=10000,'Preview frame inventory exceeds the bounded source preparation request');
  return windows.flatMap(window=>Array.from({length:window.endFrame-window.startFrame},(_,offset)=>window.startFrame+offset));
}

/** The original composition, clock, source lookup and full-quality encoder remain unchanged. */
export async function renderMotionWindows(request, windows, dependencies={}) {
  const work=path.join(request.output,`motion-preview-capture-${windows[0]?.startFrame??'empty'}`);
  const ledger=nativeTimingLedger();  // Telemetry only: the timed SDK passes every call through unchanged.
  const sdk=timedNativeSdk(dependencies.sdk??await importNativeCaptureLibrary(request),ledger);
  const context=await createNativeCaptureContext(request,work,sdk);
  const required=previewFrameInventory(context,windows);
  await timedStep(ledger,'prepare',()=>request.adapter==='native-long'
    ?prepareSparseLongContext(context,required):prepareNativeCaptureContext(context));
  const results=[];
  for(const [index,window] of windows.entries()){
    const {startFrame,endFrame}=window;
    assert.ok(Number.isSafeInteger(startFrame)&&Number.isSafeInteger(endFrame)&&startFrame>=0
      &&endFrame<=context.plan.canvas.totalFrames&&endFrame>startFrame&&(endFrame-startFrame)/context.rate<=12,
    'Motion preview window exceeds its explicit clock or duration');
    const directory=path.join(work,`window-${index}`);fs.mkdirSync(directory);
    const framesDir=path.join(directory,'frames');fs.mkdirSync(framesDir);
    const frames=Array.from({length:endFrame-startFrame},(_,offset)=>startFrame+offset),sessions=[],pins=[];
    // Only sources whose interval meets this window can decode here (studio/native_window_batch_plan.mjs).
    const batchPlan=nativeWindowBatchPlan(context,startFrame,endFrame);
    for(const points of nativeCaptureBatches(frames,batchPlan.maximumFrames)){
      const receipt={frames:points};sessions.push(receipt);
      await withNativeCaptureSession(context,{framesDir:path.join(directory,`source-${sessions.length}`),receipt},async session=>{
        for(const frame of points){
          const row=await captureNativeFrame(context,session,frame);
          const target=path.join(framesDir,`frame_${String(frame-startFrame).padStart(6,'0')}.jpg`);
          fs.copyFileSync(row.path,target,fs.constants.COPYFILE_EXCL);pins.push({path:target,sha256:row.sha256});
          console.log(`SNIPER_PROGRESS motion-preview ${results.reduce((sum,row)=>sum+row.frames,0)+pins.length}`);
        }
      });
    }
    await timedStep(ledger,'screenshotReverify',()=>{
      for(const row of pins)assert.equal(nativeCaptureHash(row.path),row.sha256,'Preview screenshot changed');
    });
    const output=path.join(directory,'picture.mp4');
    const args=nativeBatchEncoderArgs({fps:context.fps,framesDir,output,totalFrames:frames.length,version:'0.8.31'});
    args.splice(-2,0,'-bsf:v','h264_metadata=colour_primaries=1:transfer_characteristics=13:matrix_coefficients=1:video_full_range_flag=0');
    await timedStep(ledger,'encode',()=>(dependencies.encode??encodeNativeBatchPicture)(request.tools.ffmpeg,args));
    results.push({...window,frames:frames.length,path:output,sha256:nativeCaptureHash(output),sessions,batchPlan,
      timings:nativeTimingSummary(ledger)});
  }
  assert.equal(nativeCaptureHash(path.join(request.project,'index.html')),context.sourceHtmlSha256);
  return results;
}

if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url){
  assertNativePreviewOwner(process.argv[2]);
  const request=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
  const index=Number(process.argv[3]);
  assert.ok(Number.isSafeInteger(index)&&index>=0&&index<768,'Invalid preview section');
  const input=JSON.parse(fs.readFileSync(path.join(request.output,`preview-picture-${index}-input.json`),'utf8'));
  const results=await renderMotionWindows(request,[input.window]);
  fs.writeFileSync(path.join(request.output,`preview-picture-${index}-picture.json`),JSON.stringify(results[0],null,2),{flag:'wx'});
}
