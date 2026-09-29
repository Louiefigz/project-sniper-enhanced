/** Acquire an attempt's exact shared source frames and publish the private view its SDK render reads.
 *
 * Runs inside the render/picture owner immediately before the SDK CLI render. It compiles the same
 * project, leases every compiled video's content-bound entry for the export supervisor (publishing
 * owned misses under the same ownership protocol as capture), admits each by its frame-byte digest and
 * links them under the SDK's own path-keyed names. The render then passes this view as
 * `--frames-cache-dir`, so it can only hit; the supervisor's live lease keeps every linked entry in place.
 */
import fs from 'node:fs';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {assertNativeRenderOwner} from './runtime/native-export-guard.mjs';
import {createNativeCaptureContext,compileNativeCapture,acquireNativeCaptureSources} from './native_short_capture_context.mjs';
import {CONTENT_SOURCE_MODES} from './native_long_sources.mjs';

export const SOURCE_VIEW_STATUS='native-source-view-ready';

export async function prepareRenderSourceView(request, dependencies={}) {
  if(request.adapter!=='native-long'&&!CONTENT_SOURCE_MODES.includes(request.sourceCacheMode))
    throw new Error('Native source view requires the shared content store; historical cache modes require a fresh export');
  // The SDK render reads this view after this step exits, so only the supervisor's lease may cover it.
  if(typeof request.sourceStoreOwner!=='string')throw new Error('The render source view requires the export supervisor owner lock');
  const work=path.join(request.output,'render-source-view');
  const context=await createNativeCaptureContext(request,work,dependencies.sdk);
  context.sourceViewIdentity=request.output;
  await compileNativeCapture(context);
  await acquireNativeCaptureSources(context);
  const result={schemaVersion:1,status:SOURCE_VIEW_STATUS,view:context.sourceView,
    entries:[...context.sourceEntries.values()].map(row=>({videoId:row.video.id,pathName:row.pathName,
      contentKey:row.contentKey,entry:row.entry,frameDigest:row.frameDigest,outcome:row.outcome,waitedMs:row.waitedMs}))};
  fs.writeFileSync(path.join(work,'source-view.json'),JSON.stringify(result,null,2),{flag:'wx'});
  return result;
}

if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url){
  const request=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
  assertNativeRenderOwner(['render',request.project,'--output',path.join(request.output,'picture.mp4')]);
  const result=await prepareRenderSourceView(request);
  console.log(JSON.stringify({status:result.status,view:result.view,entries:result.entries.length}));
}
