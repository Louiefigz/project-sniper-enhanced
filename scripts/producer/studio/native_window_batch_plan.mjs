/** Size one rendered frame range by the admitted sources that can be active inside it. */
import assert from 'node:assert/strict';
import {nativeCaptureBatchPlan} from './native_short_capture_context.mjs';

/**
 * The composition-wide heuristic sums every compiled video as if all decoded on every frame.
 * A bounded window only injects sources whose timeline interval meets its frames, so its
 * workload is the sum over that subset. Intervals are compared closed on both ends, which
 * can only include more sources (a more conservative plan), never fewer. The existing live
 * owned-memory guards remain authoritative; this is a planning estimate, not a measurement.
 */
export function nativeWindowBatchPlan(context, startFrame, endFrame) {
  const total=context.plan.canvas.totalFrames;
  assert.ok(Number.isSafeInteger(startFrame)&&Number.isSafeInteger(endFrame)&&startFrame>=0
    &&endFrame>startFrame&&endFrame<=total,'Invalid native window range');
  assert.equal(context.cacheEntries.length,context.result.composition.videos.length,
    'Window planning requires every compiled video to have an admitted source entry');
  const first=startFrame/context.rate,last=(endFrame-1)/context.rate;
  const active=context.cacheEntries.filter(({video})=>{
    assert.ok(Number.isFinite(video.start)&&Number.isFinite(video.end)&&video.end>=video.start,'Invalid compiled video interval');
    return video.start<=last&&first<=video.end;
  });
  const plan=active.length?nativeCaptureBatchPlan(active):nativeCaptureBatchPlan([],0);
  assert.ok(plan.maximumFrames>=context.batchPlan.maximumFrames,'Window plan cannot be stricter than its composition subset');
  return {...plan,rule:'window-active-source-rgba-v1',window:{startFrame,endFrameExclusive:endFrame},
    activeVideoIds:active.map(({video})=>video.id),
    composition:{rule:context.batchPlan.rule,maximumFrames:context.batchPlan.maximumFrames,
      decodedBytesPerFrame:context.batchPlan.decodedBytesPerFrame},
    scope:'Workload estimate over sources whose interval meets this window; live owned-memory guards remain authoritative'};
}
