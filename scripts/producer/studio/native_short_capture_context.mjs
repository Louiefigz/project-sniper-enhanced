/** Shared exact-cache compilation and disposable native screenshot sessions. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {nativeSourceCacheEntry,prepareNativeSourceCache,nativeSourceFileIdentity,nativeSourceMetadata} from './native_source_cache.mjs';
import {nativeOriginalMediaGuard} from './native_original_media.mjs';
export {nativeSourceCacheEntry} from './native_source_cache.mjs';

export const NATIVE_CAPTURE_BATCH_FRAMES = 48;
const NATIVE_SOURCE_RGBA_PLANNING_BYTES = 1536 * 1024 ** 2;
const NATIVE_CAPTURE_BATCH_PRESETS = [48,24,12,8,4,2,1];

/** Keep checksum memory bounded even when the supplied recording is large. */
export function nativeCaptureHash(file) {
  const digest=createHash('sha256'),buffer=Buffer.allocUnsafe(1024*1024),descriptor=fs.openSync(file,'r');
  try { let count;while((count=fs.readSync(descriptor,buffer,0,buffer.length,null))>0)digest.update(buffer.subarray(0,count)); }
  finally { fs.closeSync(descriptor); }
  return digest.digest('hex');
}

/** Stream exact source bytes with bounded reads so SDK children can exit and be reaped. */
export async function nativeCaptureSourceHash(context, file) {
  const identity=nativeSourceFileIdentity(file);
  const inspected=context.sourceMetadata?.get(identity.file);
  if(inspected)assert.deepEqual(identity,inspected.identity,'Native source changed after metadata inspection');
  context.sourceHashes??=new Map();
  const previous=context.sourceHashes.get(identity.file);
  if(previous){
    assert.deepEqual(identity,previous.identity,'Native source changed after hashing');
    return previous.sha256;
  }
  const digest=createHash('sha256');
  for await(const chunk of fs.createReadStream(identity.file,{highWaterMark:1024*1024}))digest.update(chunk);
  assert.deepEqual(nativeSourceFileIdentity(file),identity,'Native source changed during hashing');
  const sha256=digest.digest('hex');context.sourceHashes.set(identity.file,{identity,sha256});
  return sha256;
}

/** Partition without dropping, reordering or deduplicating reverse-QC occurrences. */
export function nativeCaptureBatches(points, maximum=NATIVE_CAPTURE_BATCH_FRAMES) {
  assert.ok(Number.isSafeInteger(maximum)&&maximum>0&&maximum<=NATIVE_CAPTURE_BATCH_FRAMES,'Invalid native session bound');
  assert.ok(Array.isArray(points)&&points.every(frame=>Number.isSafeInteger(frame)&&frame>=0),'Invalid native capture inventory');
  return Array.from({length:Math.ceil(points.length/maximum)},(_,index)=>points.slice(index*maximum,(index+1)*maximum));
}

/** Conservative source-pixel workload heuristic; the existing live memory guards remain authoritative. */
export function nativeCaptureBatchPlan(entries, compiledVideoCount) {
  assert.ok(Array.isArray(entries),'Native batch planning requires admitted source dimensions');
  assert.ok(entries.length>0||compiledVideoCount===0,'Native empty source planning requires compiled zero-video evidence');
  if(compiledVideoCount!==undefined)assert.ok(Number.isSafeInteger(compiledVideoCount)&&compiledVideoCount>=0
    &&compiledVideoCount===entries.length,'Native admitted sources must match the compiled video count');
  const sources=entries.map(entry=>{
    assert.ok(Number.isSafeInteger(entry.width)&&entry.width>0&&Number.isSafeInteger(entry.height)&&entry.height>0,
      'Native batch planning requires original integer source dimensions');
    const rgbaBytes=entry.width*entry.height*4;
    assert.ok(Number.isSafeInteger(rgbaBytes),'Native source pixel workload exceeds the safe integer range');
    return {videoId:entry.video.id,width:entry.width,height:entry.height,rgbaBytes};
  });
  const decodedBytesPerFrame=sources.reduce((sum,row)=>sum+row.rgbaBytes,0);
  assert.ok(Number.isSafeInteger(decodedBytesPerFrame),'Native combined source workload exceeds the safe integer range');
  const fitting=decodedBytesPerFrame===0?NATIVE_CAPTURE_BATCH_FRAMES:Math.floor(NATIVE_SOURCE_RGBA_PLANNING_BYTES/decodedBytesPerFrame);
  const maximumFrames=NATIVE_CAPTURE_BATCH_PRESETS.find(size=>size<=fitting)??1;
  return {schemaVersion:1,rule:'admitted-source-rgba-v1',maximumFrames,
    planningBudgetBytes:NATIVE_SOURCE_RGBA_PLANNING_BYTES,decodedBytesPerFrame,sources,
    singleFrameExceedsPlanningBudget:decodedBytesPerFrame>NATIVE_SOURCE_RGBA_PLANNING_BYTES,
    scope:decodedBytesPerFrame===0
      ?'Compiled zero-video source workload only; graphics, images and browser memory remain under the existing live resource guards'
      :'Workload estimate only; not observed memory, allocation ownership or a replacement resource limit'};
}

/** Load pinned local inputs; callers retain their own failed-attempt receipts. */
export async function createNativeCaptureContext(request, work, sdkOverride) {
  const {project,runtime}=request;
  const library=path.join(runtime,'dist/native-capture-library.mjs');
  const sdk=sdkOverride??await import(pathToFileURL(library).href);
  const plan=JSON.parse(fs.readFileSync(path.join(project,'SHORT-PROJECT.json'),'utf8'));
  const [num,den]=plan.canvas.frameRate.split('/').map(Number),rate=num/den;
  assert.ok(Number.isSafeInteger(num)&&Number.isSafeInteger(den)&&den>0&&rate>=1&&rate<=60,'Invalid native capture clock');
  assert.ok(Number.isSafeInteger(plan.canvas.totalFrames)&&plan.canvas.totalFrames>0
    &&plan.canvas.totalFrames/rate<=180,'Native capture exceeds Short bounds');
  fs.mkdirSync(work);
  process.env.SNIPER_NATIVE_FRAME_TRANSPORT='url-v1';
  const log=Object.fromEntries(['info','warn','error','debug'].map(key=>[key,(...values)=>console.log(key,...values)]));
  return {request,project,runtime,work,sdk,plan,fps:{num,den},rate,log,cacheEntries:[],
    sourceHtmlSha256:nativeCaptureHash(path.join(project,'index.html')),runtimeLibrarySha256:nativeCaptureHash(library)};
}

/** Compile once and admit only the exact complete retained source-frame entries. */
export async function prepareNativeCaptureContext(context) {
  const {sdk,project,work,fps,plan,rate,log}=context;
  context.cfg=sdk.resolveConfig({chromePath:process.env.HYPERFRAMES_BROWSER_PATH,
    browserGpuMode:'software',forceScreenshot:true,useDrawElement:false,lowMemoryMode:true,
    enableBrowserPool:false,staticFrameDedup:false,frameDataUriCacheLimit:32,frameDataUriCacheBytesLimitMb:64});
  context.result=await sdk.runCompileStage({projectDir:project,workDir:work,
    htmlPath:path.join(project,'index.html'),entryFile:'index.html',
    job:{config:{fps,quality:'high',format:'mp4',workers:1}},cfg:context.cfg,
    needsAlpha:false,log,assertNotAborted:()=>{},failClosedFontFetch:true});
  assert.equal(context.result.composition.width,1080);assert.equal(context.result.composition.height,1920);
  assert.equal(context.result.composition.duration,plan.canvas.totalFrames/rate);
  await prepareNativeSourceCache(context);
  const extracted=[];
  for(const video of context.result.composition.videos){
    const cached=nativeSourceCacheEntry(context,video),metadata=await nativeSourceMetadata(context,cached.source);
    extracted.push({videoId:video.id,srcPath:cached.source,outputDir:cached.entry,framePattern:'frame_%05d.png',
      fps:rate,totalFrames:cached.names.length,metadata,framePaths:cached.framePaths});
    context.cacheEntries.push({video,keyBlob:cached.keyBlob,path:cached.entry,count:cached.names.length,
      width:metadata.width,height:metadata.height,sourceSha256:await nativeCaptureSourceHash(context,cached.source)});
  }
  context.compiledSha256=nativeCaptureHash(path.join(work,'compiled/index.html'));
  context.batchPlan=nativeCaptureBatchPlan(context.cacheEntries,context.result.composition.videos.length);
  context.lookup=sdk.createFrameLookupTable(context.result.composition.videos,extracted);
  return context;
}

/** Preserve screenshot encoding, absolute output time and original source geometry. */
export function nativeCaptureOptions(context) {
  return {width:1080,height:1920,fps:context.fps,format:'jpeg',quality:95,deviceScaleFactor:1,captureBeyondViewport:true,
    skipReadinessVideoIds:context.result.composition.videos.map(video=>video.id),
    videoMetadataHints:context.cacheEntries.map(entry=>({id:entry.video.id,width:entry.width,height:entry.height})),
    compositionDurationSeconds:context.plan.canvas.totalFrames/context.rate};
}

async function cleanupSession(context, owned, receipt) {
  const {session,server,media}=owned;
  const actions=[['sessionClosed',()=>session&&context.sdk.closeCaptureSession(session)],
    ['browserPoolDrained',()=>context.sdk.drainBrowserPool()],['mediaGuardDisposed',()=>media&&media.dispose()],
    ['serverClosed',()=>server&&server.close()]],errors=[];
  for(const [name,action] of actions){
    try { await action();receipt[name]=true; }catch(error){receipt[name]=false;errors.push(error);}
  }
  return errors;
}

/** A fresh browser for one bounded group; all disposals run even on capture failure. */
export async function withNativeCaptureSession(context, options, action) {
  const {sdk,project,work,fps}=context,receipt=options.receipt;
  let server,session,media,value,error;
  try {
    server=await sdk.createFileServer2({projectDir:project,compiledDir:path.join(work,'compiled'),port:0,preHeadScripts:[sdk.VIRTUAL_TIME_SHIM],fps});
    assert.ok(server.frameTransport);
    assert.equal(context.cacheEntries.length,context.result.composition.videos.length,'Native source transport requires every compiled video');
    // Zero-video picture keeps the transport unconfigured: accidental resolution stays denied.
    if(context.cacheEntries.length)server.frameTransport.configure(context.cacheEntries.map(entry=>entry.path));
    const injector=sdk.createVideoFrameInjector(context.lookup,{frameDataUriCacheLimit:32,
      frameDataUriCacheBytesLimitMb:64,strictFrameDecode:true,frameSrcResolver:file=>server.frameTransport.resolve(file)});
    session=await sdk.createCaptureSession(server.url,options.framesDir,nativeCaptureOptions(context),injector,context.cfg);
    if(context.request.captureMode==='cached-native-batches'){
      receipt.originalMedia={};media=nativeOriginalMediaGuard(context,server.url,receipt.originalMedia);
      await media.attach(session.page);
    }
    await sdk.initializeSession(session);assert.equal(session.captureMode,'screenshot');
    await media?.assertHealthy();value=await action(session);await media?.assertHealthy();
    receipt.transport=server.frameTransport.stats();assert.equal(receipt.transport.errors,0);
  }catch(caught){error=caught;}
  const errors=await cleanupSession(context,{session,server,media},receipt);
  if(error||errors.length)throw new AggregateError([...(error?[error]:[]),...errors],'Native capture session failed or cleanup was incomplete');
  return value;
}

/** The same source/font inspection serves both complete picture capture and QC samples. */
export async function captureNativeFrame(context, session, frame) {
  const time=frame/context.rate,active=context.lookup.getActiveFramePayloads(time);
  const payload=[...active].map(([id,row])=>({id,frameIndex:row.frameIndex,sha256:nativeCaptureHash(row.framePath),path:row.framePath}));
  const captured=await context.sdk.captureFrame(session,frame,time);
  const observed=await session.page.evaluate(()=>({fonts:[...document.fonts].map(font=>({family:font.family,status:font.status})),
    images:[...document.querySelectorAll('.__render_frame__')].map(img=>({id:img.previousElementSibling?.id,
      loaded:img.complete&&img.naturalWidth>0,display:getComputedStyle(img).display})),
    texts:[...document.querySelectorAll('.type,.caption')].filter(el=>getComputedStyle(el).visibility==='visible'&&getComputedStyle(el).display!=='none')
      .map(el=>({id:el.id,text:el.textContent,clipPath:getComputedStyle(el).clipPath}))}));
  assert.ok(observed.fonts.length&&observed.fonts.every(font=>font.status==='loaded'));
  for(const source of payload){assert.equal(nativeCaptureHash(source.path),source.sha256);assert.ok(observed.images.some(image=>image.id===source.id&&image.loaded));}
  return {frame,time,path:captured.path,sha256:nativeCaptureHash(captured.path),payload,observed,captureTimeMs:captured.captureTimeMs};
}

export function nativeCaptureEvidence(context) {
  return {sourceHtmlSha256:context.sourceHtmlSha256,runtimeLibrarySha256:context.runtimeLibrarySha256,
    compiledSha256:context.compiledSha256,cacheEntries:context.cacheEntries,width:1080,height:1920,frameRate:context.plan.canvas.frameRate,
    ...(context.sourceCacheAcquisition?{sourceCacheAcquisition:context.sourceCacheAcquisition}:{}),
    ...(context.batchPlan?{batchPlan:context.batchPlan}:{})};
}

/** Retain the underlying frame/decode error when disposal aggregates failures. */
export function nativeCaptureFailure(error) {
  return [String(error?.stack||error),...(error instanceof AggregateError?error.errors.map(value=>String(value?.stack||value)):[])].join('\n');
}
