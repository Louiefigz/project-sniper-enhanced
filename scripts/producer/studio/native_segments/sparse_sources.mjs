/** Sparse current-project probes through the existing content-bound source store.
 * Original composition/time/geometry are unchanged. Selected original grids support SDR CFR
 * only; VFR/HDR can use an already complete exact full cache, never a hidden full decode.
 * Real source-grid equivalence remains subject to the owned pixel comparison.
 */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {compileNativeCapture,finalizeNativeCaptureContext,nativeCaptureHash,nativeCaptureBatchPlan}
  from '../native_short_capture_context.mjs';
import {nativeSourceMetadata} from '../native_source_identity.mjs';
import {prepareLongSources} from '../native_long_sources.mjs';
import {nativeSourceFrameCount} from '../runtime/frame-source-transport.mjs';

const MAX_SOURCE_SAMPLES=2048;

/** Merge adjacent requested local indexes without widening across an unrequested frame. */
function indexSpans(indices,videoIndex) {
  const rows=[];
  for(const index of indices){
    const last=rows.at(-1);
    if(last?.endIndex===index){last.endIndex++;continue;}
    rows.push({videoIndex,startIndex:index,endIndex:index+1});
  }
  return rows;
}

/** Use the pinned SDK's original video-local floor clock and exclusive active interval. */
export function sparseSourceSpans(videos, points, rate) {
  assert.ok(Array.isArray(points)&&points.length>0&&points.length<=10000
    &&points.every(frame=>Number.isSafeInteger(frame)&&frame>=0),'Invalid bounded source frame inventory');
  const rows=[];
  for(const [videoIndex,video] of videos.entries()){
    assert.ok(!video.loop&&(video.playbackRate===undefined||video.playbackRate===1),'Sparse sources require speed one');
    const indices=[...new Set([0,...points].filter(frame=>frame/rate>=video.start&&frame/rate<video.end)
      .map(frame=>Math.floor((frame/rate-video.start)*rate+1e-9)))].sort((a,b)=>a-b);
    rows.push(...indexSpans(indices,videoIndex));
  }
  assert.ok(rows.reduce((sum,row)=>sum+row.endIndex-row.startIndex,0)<=MAX_SOURCE_SAMPLES,'Sparse source inventory exceeds bound');
  return rows.map((row,index)=>{
    const video=videos[row.videoIndex];
    return {...row,video:{...video,id:`dependency-${index}`,start:0,end:(row.endIndex-row.startIndex)/rate,
      mediaStart:video.mediaStart+row.startIndex/rate}};
  });
}

/** Never omit an active original source merely because a sparse frame was not acquired. */
export function checkedSparseLookup(lookup, videos, rate) {
  const original=lookup.getActiveFramePayloads.bind(lookup);
  lookup.getActiveFramePayloads=time=>{
    const result=original(time);
    const expected=videos.filter(video=>video.start<=time&&time<video.end).map(video=>video.id).sort();
    assert.deepEqual([...result.keys()].sort(),expected,`Unacquired active sparse source at output time ${time}`);
    for(const video of videos.filter(row=>expected.includes(row.id))){
      assert.equal(result.get(video.id).frameIndex,Math.floor((time-video.start)*rate+1e-9),'Sparse source frame clock changed');
    }
    return result;
  };
  return lookup;
}

/** Probe every compiled source before deciding if bounded new seeks are supported. */
async function sourceMetadata(context) {
  const rows=[];
  for(const video of context.result.composition.videos){
    const source=path.resolve(context.project,video.src);
    assert.ok(source.startsWith(context.project+path.sep)&&fs.realpathSync(source)===source);
    rows.push(await nativeSourceMetadata(context,source));
  }
  return rows;
}

/** Group all requested samples for a source under its original seek, never reset its fps phase. */
export function sparseSourceSelections(videos,points,rate) {
  const spans=sparseSourceSpans(videos,points,rate);
  return videos.flatMap((video,videoIndex)=>{
    const indices=spans.filter(row=>row.videoIndex===videoIndex)
      .flatMap(row=>Array.from({length:row.endIndex-row.startIndex},(_,offset)=>row.startIndex+offset));
    return indices.length?[{videoIndex,indices,video:{...video,id:`dependency-${videoIndex}`,start:0,
      end:indices.length/rate,nativeSourceFrameIndices:indices}}]:[];
  });
}

/** Preserve the admitted frame paths and their original absolute-local lookup keys. */
function spanFrames(matching,acquired,roots) {
  const frames=new Map();
  for(const span of matching){
    const entry=acquired.get(span.video.id);assert.ok(entry,'Sparse source owner omitted a span');
    assert.equal(entry.frames,span.indices.length,'Sparse acquired selected count differs');
    roots.push(entry.entry);
    for(const [offset,file] of entry.framePaths)frames.set(span.indices[offset],file);
  }
  return frames;
}

/** Map independently owned sparse entries back to unchanged original source frame indexes. */
function mappedEntries(context, spans, acquired, metadata) {
  const extracted=[],roots=[];
  for(const [index,video] of context.result.composition.videos.entries()){
    const matching=spans.filter(row=>row.videoIndex===index),frames=spanFrames(matching,acquired,roots);
    const source=path.resolve(context.project,video.src),directory=matching.length
      ?acquired.get(matching[0].video.id).entry:path.join(context.work,`inactive-source-${index}`);
    if(!matching.length){fs.mkdirSync(directory);roots.push(directory);}
    extracted.push({videoId:video.id,srcPath:source,outputDir:directory,framePattern:'frame_%05d.png',fps:context.rate,
      totalFrames:nativeSourceFrameCount(video.end-video.start,context.rate),metadata:metadata[index],framePaths:frames,ownedByLookup:true});
    context.cacheEntries.push({video,path:directory,count:frames.size,width:metadata[index].width,height:metadata[index].height,
      sourceSha256:context.request.pins[source],scope:'sparse-probe-frame-inventory'});
  }
  context.transportRoots=[...new Set(roots)];
  return extracted;
}

/** Compile original bytes once; acquire bounded spans or exact existing full entries only. */
export async function prepareSparseLongContext(context, points, sources=prepareLongSources) {
  assert.equal(context.request.adapter,'native-long','Sparse dependency capture requires the Long adapter');
  assert.ok(points.every(frame=>Number.isSafeInteger(frame)&&frame>=0&&frame<context.plan.canvas.totalFrames),
    'Sparse capture point leaves the admitted canvas');
  await compileNativeCapture(context);
  const videos=context.result.composition.videos,metadata=await sourceMetadata(context);
  if(metadata.some(row=>row.isVFR!==false||context.sdk.isHdrColorSpace(row.colorSpace))){
    await sources(context,{existingOnly:true});
    await finalizeNativeCaptureContext(context);
    context.sparseSources={mode:'existing-complete-cache-only',requestedFrames:points};
    return context;
  }
  const spans=sparseSourceSelections(videos,points,context.rate),work=path.join(context.work,'sparse-sources');fs.mkdirSync(work);
  context.sourceHashes??=new Map();
  const {sourceStoreOwner:_retention,...readerRequest}=context.request;
  const proxy={...context,request:readerRequest,work,cacheEntries:[],result:{...context.result,
    composition:{...context.result.composition,videos:spans.map(row=>row.video)}}};
  await sources(proxy);
  const extracted=mappedEntries(context,spans,proxy.sourceEntries,metadata);
  context.lookup=checkedSparseLookup(context.sdk.createFrameLookupTable(videos,extracted),videos,context.rate);
  context.compiledSha256=nativeCaptureHash(path.join(context.work,'compiled/index.html'));
  context.batchPlan=nativeCaptureBatchPlan(context.cacheEntries,videos.length);
  context.sourceCacheAcquisition=proxy.sourceCacheAcquisition;
  context.sparseSources={mode:'original-grid-sdr-cfr-selection',requestedFrames:points,
    sourceFrames:spans.reduce((sum,row)=>sum+row.indices.length,0),spans};
  return context;
}
