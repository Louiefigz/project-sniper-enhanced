/** Window-aware preview sessions and capture timing: synthetic SDK only, no browser or encoder. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {nativeCaptureBatchPlan} from '../producer/studio/native_short_capture_context.mjs';
import {nativeSourceFrameCount} from '../producer/studio/runtime/frame-source-transport.mjs';
import {nativeWindowBatchPlan} from '../producer/studio/native_window_batch_plan.mjs';
import {nativeTimingLedger,nativeTimingSummary,timedNativeSdk,timedStep} from '../producer/studio/native_capture_timing.mjs';
import {renderMotionWindows} from '../producer/studio/native_motion_previews.mjs';
import {batchFixture,seedStoreEntry} from './native_short_batched_render_fixture.mjs';

/** Sequential views of one size: F used six 1920x1080 views; the IMG_7138 edits used 4K views. */
function sequential(count, seconds, width, height, rate=30) {
  const videos=Array.from({length:count},(_,index)=>({id:`source-${index}-${index}`,start:index*seconds,end:(index+1)*seconds,mediaStart:index*seconds}));
  const cacheEntries=videos.map(video=>({video,width,height}));
  return {rate,plan:{canvas:{totalFrames:count*seconds*rate}},cacheEntries,result:{composition:{videos}},
    batchPlan:nativeCaptureBatchPlan(cacheEntries,videos.length)};
}

test('a window counts only the views whose interval meets it',()=>{
  const context=sequential(6,5,1920,1080);
  assert.equal(context.batchPlan.maximumFrames,24,'composition-wide sum of six 1080p views');
  const opening=nativeWindowBatchPlan(context,0,120);
  assert.deepEqual(opening.activeVideoIds,['source-0-0']);assert.equal(opening.maximumFrames,48);
  const join=nativeWindowBatchPlan(context,140,260);
  assert.deepEqual(join.activeVideoIds,['source-0-0','source-1-1']);assert.equal(join.maximumFrames,48);
  assert.equal(join.decodedBytesPerFrame,2*1920*1080*4);
  assert.equal(join.composition.maximumFrames,24);assert.equal(join.rule,'window-active-source-rgba-v1');
});

test('4K views keep a stricter but still window-local bound',()=>{
  const context=sequential(7,6,3840,2160);
  assert.equal(context.batchPlan.maximumFrames,4);
  assert.equal(nativeWindowBatchPlan(context,0,120).maximumFrames,48);
  assert.equal(nativeWindowBatchPlan(context,120,240).maximumFrames,24);
  assert.equal(nativeWindowBatchPlan(context,160,400).maximumFrames,12);
});

test('interval edges are counted conservatively and a graphics-only window has no source workload',()=>{
  const context=sequential(2,5,1920,1080);
  assert.deepEqual(nativeWindowBatchPlan(context,150,160).activeVideoIds,['source-0-0','source-1-1'],'a view ending at the first frame is included');
  context.result.composition.videos[1].start=context.cacheEntries[1].video.start=6;
  context.plan.canvas.totalFrames=400;
  const gap=nativeWindowBatchPlan(context,151,179);
  assert.deepEqual(gap.activeVideoIds,[]);assert.equal(gap.maximumFrames,48);assert.equal(gap.decodedBytesPerFrame,0);
});

test('invalid ranges and incomplete admission fail closed',()=>{
  const context=sequential(2,5,1920,1080);
  for(const [start,end] of [[-1,10],[10,10],[0,301],[1.5,10]])assert.throws(()=>nativeWindowBatchPlan(context,start,end),/Invalid native window range/);
  context.cacheEntries.pop();
  assert.throws(()=>nativeWindowBatchPlan(context,0,10),/every compiled video/);
});

/** Six sequential 1080p views over the shared fake SDK, with exact per-view store entries. */
function sixViewFixture() {
  const f=batchFixture(100),rate=30,seconds=5,total=6*seconds*rate;
  f.plan.canvas.frameRate='30/1';f.plan.canvas.totalFrames=total;f.plan.canvas.pictureViews=[{startFrame:0,endFrame:total}];
  f.plan.strategy.scenes=[{startFrame:0,endFrame:total}];
  fs.writeFileSync(path.join(f.request.project,'SHORT-PROJECT.json'),JSON.stringify(f.plan));
  const videos=Array.from({length:6},(_,index)=>({id:`source-${index}-${index}`,src:'assets/source.mp4',
    mediaStart:index*seconds,start:index*seconds,end:(index+1)*seconds}));
  // Exact per-view entries published into the shared content store (the route's only frame source).
  const entries=videos.map(video=>seedStoreEntry(f.request,video,nativeSourceFrameCount(seconds,rate),rate));
  f.sdk.runCompileStage=async options=>{
    f.calls.compiles.push(options);fs.mkdirSync(path.join(options.workDir,'compiled'));
    fs.writeFileSync(path.join(options.workDir,'compiled/index.html'),'TEST compiled');
    return {composition:{width:1080,height:1920,duration:total/rate,videos}};
  };
  f.sdk.extractMediaMetadata=async()=>({width:1920,height:1080});
  f.sdk.createFrameLookupTable=()=>({getActiveFramePayloads:time=>{
    const index=Math.min(5,Math.floor(time/seconds+1e-9)),local=Math.round((time-index*seconds)*rate);
    return new Map([[videos[index].id,{frameIndex:local,framePath:path.join(entries[index],`frame_${String(local+1).padStart(5,'0')}.png`)}]]);
  }});
  return f;
}

test('a 120-frame preview window uses 48-frame sessions where the composition plan allowed 24',async()=>{
  const f=sixViewFixture();
  try {
    const [result]=await renderMotionWindows(f.request,[{startFrame:0,endFrame:120}],{sdk:f.sdk,encode:f.encode});
    assert.deepEqual(result.sessions.map(row=>row.frames.length),[48,48,24]);
    assert.deepEqual(result.sessions.flatMap(row=>row.frames),Array.from({length:120},(_,frame)=>frame));
    assert.deepEqual(f.calls.frames,Array.from({length:120},(_,frame)=>frame));
    assert.equal(result.batchPlan.maximumFrames,48);assert.equal(result.batchPlan.composition.maximumFrames,24);
    assert.deepEqual(result.batchPlan.activeVideoIds,['source-0-0']);
    assert.equal(f.calls.sessions.length,3);assert.equal(f.calls.sessionCloses,3);assert.equal(f.calls.poolDrains,3);
    assert.equal(result.timings.phases.captureFrame.calls,120);assert.equal(result.timings.phases.browserLaunch.calls,3);
    assert.equal(result.timings.phases.compile.calls,1);assert.equal(result.timings.phases.encode.calls,1);
    assert.equal(result.timings.sessions.length,3);assert.doesNotThrow(()=>JSON.stringify(result));
  }finally{f.cleanup();}
});

test('the timing wrapper passes arguments, results and errors through unchanged',async()=>{
  const ledger=nativeTimingLedger(),calls=[];
  const sdk={VALUE:7,resolveConfig:value=>value,captureFrame:async(...args)=>{calls.push(args);return {path:'TEST'};},
    closeCaptureSession:async session=>{calls.push(session);},initializeSession:async()=>{throw new Error('TEST init failure');}};
  const timed=timedNativeSdk(sdk,ledger);
  assert.equal(timed.VALUE,7);assert.equal(timed.resolveConfig,sdk.resolveConfig,'synchronous helpers are not wrapped');
  assert.deepEqual(await timed.captureFrame('session',3,0.1),{path:'TEST'});
  assert.deepEqual(calls[0],['session',3,0.1]);
  const session={capturePerf:{frames:2,seekMs:4,beforeCaptureMs:5,screenshotMs:6,totalMs:15,frameMs:[7,8]}};
  await timed.closeCaptureSession(session);assert.equal(calls[1],session);
  await assert.rejects(timed.initializeSession(),/TEST init failure/);
  await assert.rejects(timedStep(ledger,'TEST step',async()=>{throw new Error('TEST step failure');}),/TEST step failure/);
  const summary=nativeTimingSummary(ledger);
  assert.deepEqual(Object.keys(summary.phases).sort(),['TEST step','captureFrame','sessionClose','sessionInitialize']);
  assert.deepEqual(summary.sessions,[{frames:2,seekMs:4,beforeCaptureMs:5,screenshotMs:6,totalMs:15}]);
  assert.equal(summary.phases.sessionInitialize.calls,1);
});
