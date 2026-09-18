/** Exact SDK source PNG acquisition, explicitly selected and sequential under the existing owner. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {NATIVE_SOURCE_FRAME_CLOCK,nativeSourceFrameCount} from './runtime/frame-source-transport.mjs';

export const SEQUENTIAL_SOURCE_CACHE_MODE = 'acquire-sequential-sdr';

/** Bind per-run memoization to a canonical file and precise mutation/replacement evidence. */
export function nativeSourceFileIdentity(source) {
  const file=fs.realpathSync(source),stat=fs.statSync(file,{bigint:true});
  assert.ok(stat.isFile(),'Native source inspection requires a regular file');
  return {file,device:stat.dev,inode:stat.ino,size:stat.size,modified:stat.mtimeNs,changed:stat.ctimeNs};
}

/** Reuse exact SDK metadata within this preparation; never reuse a changed source. */
export async function nativeSourceMetadata(context, source) {
  const identity=nativeSourceFileIdentity(source);
  context.sourceMetadata??=new Map();
  let row=context.sourceMetadata.get(identity.file);
  if(row)assert.deepEqual(identity,row.identity,'Native source changed after metadata inspection');
  else {
    const metadata=await context.sdk.extractMediaMetadata(source);
    assert.deepEqual(nativeSourceFileIdentity(source),identity,'Native source changed during metadata inspection');
    row={identity,metadata:structuredClone(metadata)};context.sourceMetadata.set(identity.file,row);
  }
  return structuredClone(row.metadata);
}

/** Preserve the SDK v4 identity, original pixels and exact rational frame clock. */
export function nativeSourceCacheIdentity(context, video) {
  const source=path.resolve(context.project,video.src),stat=fs.statSync(source),{num,den}=context.fps;
  const keyBlob={p:source,m:Math.floor(stat.mtimeMs),s:stat.size,ms:video.mediaStart,
    d:video.end-video.start,f:den===1?String(num):`${num}/${den}`,fmt:'png',t:NATIVE_SOURCE_FRAME_CLOCK};
  const key=createHash('sha256').update(JSON.stringify(keyBlob)).digest('hex');
  return {source,keyBlob,entry:path.join(context.request.cache,'hfcache-v4-'+key.slice(0,16))};
}

/** A cache marker is insufficient without every exact consecutive source frame. */
export function nativeSourceCacheEntry(context, video) {
  const identity=nativeSourceCacheIdentity(context,video),{entry,keyBlob}=identity;
  assert.ok(fs.existsSync(path.join(entry,'.hf-complete')),`Exact native source frame cache missing: ${JSON.stringify(keyBlob)}`);
  const names=fs.readdirSync(entry).filter(name=>/^frame_\d{5}\.png$/.test(name)).sort();
  assert.equal(names.length,nativeSourceFrameCount(video.end-video.start,context.rate),'Incomplete native source cache');
  const framePaths=new Map(names.map((name,index)=>{
    assert.equal(name,`frame_${String(index+1).padStart(5,'0')}.png`,'Native source cache has a frame gap');
    return [index,path.join(entry,name)];
  }));
  return {...identity,names,framePaths};
}

function localVideo(context, video) {
  assert.ok(typeof video.src==='string'&&!/^[a-z][a-z0-9+.-]*:|^\/\//i.test(video.src),'Cold cache requires staged local video');
  assert.ok([video.start,video.end,video.mediaStart].every(Number.isFinite)&&video.start>=0
    &&video.end>video.start&&video.end<=context.plan.canvas.totalFrames/context.rate&&video.mediaStart>=0
    &&(video.playbackRate===undefined||video.playbackRate===1)&&!video.loop,'Cold cache requires finite speed-1 non-looping native video');
  const identity=nativeSourceCacheIdentity(context,video);
  assert.ok(identity.source.startsWith(context.project+path.sep)&&fs.realpathSync(identity.source)===identity.source,
    'Cold cache source must be a canonical staged project file');
  return identity;
}

function persist(context, receipt) {
  fs.writeFileSync(path.join(context.work,'source-cache.json'),JSON.stringify(receipt,null,2));
}

/** Probe all sources before any extraction; one-video calls cannot reproduce mixed-HDR negotiation. */
async function inspectSources(context, receipt) {
  const inspected=new Map();
  for(const video of context.result.composition.videos){
    const {source,keyBlob}=localVideo(context,video);
    if(inspected.has(source))continue;
    const metadata=await nativeSourceMetadata(context,source);
    assert.ok(!context.sdk.isHdrColorSpace(metadata.colorSpace),'Sequential cold cache does not admit HDR source negotiation');
    assert.ok(metadata.width>0&&metadata.height>0,'Cold cache source lacks original dimensions');
    assert.deepEqual(nativeSourceCacheIdentity(context,video).keyBlob,keyBlob,'Cold cache source changed during its probe');
    const row={source,keyBlob,width:metadata.width,height:metadata.height,isVFR:!!metadata.isVFR,colorSpace:metadata.colorSpace??null};
    inspected.set(source,row);receipt.sources.push(row);persist(context,receipt);
  }
}

/** Await the real SDK publisher for one video; never manufacture or migrate a completed entry. */
async function acquireVideo(context, video, receipt) {
  const {source,keyBlob,entry}=localVideo(context,video);
  const row={videoId:video.id,source,keyBlob,entry,status:'checking',startedAt:new Date().toISOString()};
  receipt.entries.push(row);persist(context,receipt);
  const existing=fs.existsSync(path.join(entry,'.hf-complete'));
  if(existing)nativeSourceCacheEntry(context,video);
  else assert.ok(!fs.existsSync(entry),'Incomplete cache directory must be preserved; select a new cache root');
  // SDK hits touch their completion marker before later SDK calls may perform cache GC.
  row.status=existing?'checking-sdk-cache-hit':'extracting-one-video';persist(context,receipt);
  const selected=structuredClone(video),before=JSON.stringify(selected);
  const result=await context.sdk.extractAllVideoFrames([selected],context.project,
    {fps:context.fps,outputDir:path.join(context.work,'source-extraction'),format:'png',
      timelineEnd:context.plan.canvas.totalFrames/context.rate,maxTransientRetries:0,collectProbeFailures:true},
    undefined,{extractCacheDir:context.request.cache,extractCacheMaxBytes:context.cfg.extractCacheMaxBytes},
    path.join(context.work,'compiled'));
  row.sdkResult={success:result.success,errors:result.errors,phaseBreakdown:result.phaseBreakdown,durationMs:result.durationMs};
  persist(context,receipt);
  assert.ok(result.success&&result.errors.length===0&&result.extracted.length===1,'SDK source extraction failed or omitted its video');
  assert.equal(JSON.stringify(selected),before,'SDK changed the requested extraction window');
  assert.deepEqual(nativeSourceCacheIdentity(context,video).keyBlob,keyBlob,'Cold cache source changed during extraction');
  const cached=nativeSourceCacheEntry(context,video),extracted=result.extracted[0];
  assert.equal(extracted.outputDir,cached.entry,'SDK did not publish the exact source cache entry');
  assert.equal(extracted.videoId,video.id);assert.equal(extracted.totalFrames,cached.names.length);
  assert.deepEqual([...extracted.framePaths],[...cached.framePaths],'SDK source frame inventory differs from the exact cache');
  row.frames=cached.names.length;row.status=existing?'exact-cache-hit':'sdk-published-exact-cache';persist(context,receipt);
}

/** Explicit cold-cache work stays before browser capture and within the parent's original deadline. */
export async function prepareNativeSourceCache(context) {
  const mode=context.request.sourceCacheMode??'existing-only';
  if(mode==='existing-only')return;
  assert.equal(mode,SEQUENTIAL_SOURCE_CACHE_MODE,'Unsupported source cache acquisition mode');
  assert.equal(context.request.captureMode,'cached-native-batches','Cold cache acquisition requires explicit bounded native batches');
  assert.equal(typeof context.sdk.extractAllVideoFrames,'function','Pinned SDK lacks source extraction primitive');
  assert.equal(typeof context.sdk.isHdrColorSpace,'function','Pinned SDK lacks exact HDR classification');
  const receipt={schemaVersion:1,scope:'native-sdk-sequential-source-cache',mode,status:'preparing',
    maximumConcurrentExtractions:1,format:'png',sourceGeometry:'original',sources:[],entries:[]};
  context.sourceCacheAcquisition=receipt;persist(context,receipt);
  try {
    await inspectSources(context,receipt);
    for(const video of context.result.composition.videos)await acquireVideo(context,video,receipt);
    receipt.status='exact-source-caches-ready';
  }catch(error){receipt.status='failed';receipt.error=String(error?.stack||error);throw error;}
  finally{persist(context,receipt);}
}
