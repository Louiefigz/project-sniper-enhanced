/** Admit future cache allocation before the pinned SDK extracts any long sources. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {nativeSourceMetadata,nativeSourceFileIdentity,nativeSourceCacheEntry,nativeSourceCacheIdentity} from './native_source_cache.mjs';
import {nativeSourceFrameCount} from './runtime/frame-source-transport.mjs';

/** Project measured source sizes with headroom; the continuous live disk guard stays mandatory. */
export function longStoragePlan(rows, canvas, sampleCount) {
  const entries=new Map(),negotiated=rows.some(row=>row.hdr);
  for(const row of rows){
    assert.ok([row.width,row.height,row.frames].every(value=>Number.isSafeInteger(value)&&value>0));
    assert.ok(Number.isSafeInteger(row.bytesPerFrame)&&row.bytesPerFrame>0);
    const allocation=row.cached&&!negotiated?0:Math.ceil(row.bytesPerFrame*row.frames*1.6);
    entries.set(row.key,Math.max(entries.get(row.key)??0,allocation));
  }
  const sourceBytes=[...entries.values()].reduce((sum,value)=>sum+value,0);
  const sampleBytes=canvas.width*canvas.height*sampleCount;
  // Includes picture, AAC candidate and review copies at >2× the largest observed client recording's bytes/frame.
  const outputBytes=Math.ceil(canvas.totalFrames*canvas.width*canvas.height*.25);
  const plannedBytes=sourceBytes*2+sampleBytes+outputBytes+1024**3;
  assert.ok(Number.isSafeInteger(plannedBytes)&&plannedBytes>=0,'Unsafe long disk plan');
  return {sourceBytes,sampleBytes,outputBytes,plannedBytes,reserveBytes:10*1024**3,
    requiredFreeBytes:plannedBytes+10*1024**3,
    basis:'Largest of source PNG samples × frame count × 1.6, plus simultaneous scratch and estimated output; projection, not a guaranteed compression bound'};
}

/** Include every distinct used range; a quiet opening cannot stand in for later footage. */
export function longSourceProbes(videos, rate) {
  const samples=[],seen=new Set();
  for(const video of videos){
    const key=JSON.stringify([video.src,video.mediaStart,video.end-video.start]);
    if(seen.has(key))continue;
    seen.add(key);
    const length=Math.min(video.end-video.start,3/rate);
    for(const fraction of [0,.5,1])samples.push({...video,id:`budget-${samples.length}`,
      start:0,end:length,mediaStart:video.mediaStart+Math.max(0,video.end-video.start-length)*fraction});
  }
  return samples;
}

/** Reject short ending windows during bounded probing, before the complete source cache. */
export async function probeLongSourceSizes(context) {
  const {sdk,result,project,work,rate,fps}=context;
  const samples=longSourceProbes(result.composition.videos,rate),before=JSON.stringify(samples);
  const rows=await sdk.extractAllVideoFrames(samples,project,{fps,format:'png',
    outputDir:path.join(work,'budget-source-frames'),maxTransientRetries:0,collectProbeFailures:true},
    undefined,{extractCacheDir:path.join(work,'budget-cache')},path.join(work,'compiled'));
  assert.ok(rows.success&&rows.errors.length===0&&rows.extracted.length===samples.length,'Source disk sampling failed');
  assert.equal(JSON.stringify(samples),before,'Source probe changed its declared window; author an explicit final-frame hold');
  const sizes=new Map();
  for(const row of rows.extracted){
    const sample=samples.find(item=>item.id===row.videoId);
    assert.equal(row.totalFrames,nativeSourceFrameCount(sample.end-sample.start,rate),'Source probe lacks its ending frame');
    for(const file of row.framePaths.values()){
      sizes.set(row.srcPath,Math.max(sizes.get(row.srcPath)??0,fs.statSync(file).size));
    }
  }
  console.log('SNIPER_PROGRESS source-budget 1');
  return sizes;
}

async function inspectLongSources(context) {
  const {sdk,result,project,rate,request}=context;
  const rows=[],identities=new Map();
  const initialDisk=fs.statfsSync(request.output);
  for(const video of result.composition.videos){
    const file=path.resolve(project,video.src);
    assert.ok(file.startsWith(project+path.sep)&&fs.realpathSync(file)===file,'Long source must be staged locally');
    assert.ok(!video.loop&&(video.playbackRate===undefined||video.playbackRate===1),'Long source must use speed one');
    const metadata=await nativeSourceMetadata(context,file);
    identities.set(file,nativeSourceFileIdentity(file));
    let cached=false;
    if(fs.existsSync(nativeSourceCacheIdentity(context,video).entry)){
      nativeSourceCacheEntry(context,video);cached=true;
    }
    rows.push({key:JSON.stringify([file,video.mediaStart,video.end-video.start]),file,cached,
      hdr:sdk.isHdrColorSpace(metadata.colorSpace),
      width:metadata.width,height:metadata.height,frames:nativeSourceFrameCount(video.end-video.start,rate)});
  }
  const unique=new Map(rows.map(row=>[row.key,row]));
  const probeBytes=[...unique.values()].reduce((sum,row)=>sum+row.width*row.height*8*9,0);
  assert.ok(initialDisk.bavail*initialDisk.bsize>=probeBytes+10*1024**3,'Insufficient disk for bounded source probes');
  return {rows,identities};
}

/** Use complete SDK color negotiation; conservatively charge cold space for HDR cache transforms. */
export async function prepareLongSources(context) {
  const {sdk,result,project,work,fps,rate,request,plan}=context;
  const {rows,identities}=await inspectLongSources(context);
  const sizes=await probeLongSourceSizes(context);
  for(const row of rows)row.bytesPerFrame=sizes.get(row.file);
  const storage=longStoragePlan(rows,plan.canvas,request.sampleCount);
  const cacheDisk=fs.statfsSync(request.cache),outputDisk=fs.statfsSync(request.output);
  storage.cacheFreeBytes=cacheDisk.bavail*cacheDisk.bsize;storage.outputFreeBytes=outputDisk.bavail*outputDisk.bsize;
  fs.writeFileSync(path.join(work,'storage-plan.json'),JSON.stringify(storage,null,2),{flag:'wx'});
  assert.ok(storage.cacheFreeBytes>=storage.requiredFreeBytes&&storage.outputFreeBytes>=storage.requiredFreeBytes,
    'Long source allocation exceeds free disk plus reserve; use selected media or a larger cache volume before extraction');
  // Retain the SDK publisher, cache validation, original source geometry and full negotiation.
  const videos=structuredClone(result.composition.videos),before=JSON.stringify(videos);
  const extracted=await withSourceProgress(request.cache,signal=>sdk.extractAllVideoFrames(videos,project,
    {fps,outputDir:path.join(work,'source-extraction'),format:'png',timelineEnd:plan.canvas.totalFrames/rate,
      maxTransientRetries:0,collectProbeFailures:true},signal,
    {...context.cfg,extractCacheDir:request.cache,extractCacheMaxBytes:Math.max(context.cfg.extractCacheMaxBytes,storage.sourceBytes*2)},
    path.join(work,'compiled')));
  assert.ok(extracted.success&&extracted.errors.length===0&&extracted.extracted.length===videos.length,
    'Long source extraction failed before full picture render');
  assert.equal(JSON.stringify(videos),before,'Source ended before its declared window; author an explicit final-frame hold');
  for(const [file,identity] of identities)assert.deepEqual(nativeSourceFileIdentity(file),identity,'Long source changed');
  for(const video of videos){
    const row=extracted.extracted.find(item=>item.videoId===video.id);
    assert.equal(row.totalFrames,nativeSourceFrameCount(video.end-video.start,rate),
      'Decoded source lacks the declared final frame; author an explicit hold without truncating dialogue');
    assert.equal(row.framePaths.size,row.totalFrames,'Long source cache is incomplete');
  }
  context.longExtracted=extracted.extracted;
  context.sourceCacheAcquisition={status:'exact-source-caches-ready',storage,
    phaseBreakdown:extracted.phaseBreakdown,durationMs:extracted.durationMs};
}

function directoryIdentity(directory) {
  const stat=fs.statSync(directory,{bigint:true});
  assert.ok(stat.isDirectory()&&!fs.lstatSync(directory).isSymbolicLink(),'Unsafe source cache directory');
  return `${stat.dev}:${stat.ino}:${stat.mtimeNs}`;
}

/** Only changed/new cache directories can represent newly allocated source frames. */
export function sourceFrameInventory(directory, baseline=new Map()) {
  const entries=fs.readdirSync(directory,{withFileTypes:true});
  assert.ok(entries.length<=4096,'Source cache progress directory inventory exceeds its bound');
  const identities=new Map();let frames=0;
  for(const entry of entries){
    if(!entry.isDirectory()||!entry.name.startsWith('hfcache-'))continue;
    const file=path.join(directory,entry.name);
    try{
      const identity=directoryIdentity(file);identities.set(entry.name,identity);
      if(identity===baseline.get(entry.name))continue;
      frames+=fs.readdirSync(file).filter(name=>/^frame_\d+\.(png|jpg)$/.test(name)).length;
    }catch(error){if(error.code==='ENOENT')continue;throw error;} // SDK atomic publication can rename a partial entry.
    assert.ok(frames<=500000,'Source cache progress frame inventory exceeds its bound');
  }
  return {frames,identities};
}

/** SDK abort and the parent owner still control cancellation, deadlines and process cleanup. */
export async function withSourceProgress(directory, action) {
  const baseline=sourceFrameInventory(directory).identities,controller=new AbortController();
  let highest=0,fault;
  const observe=()=>{
    try{
      const {frames}=sourceFrameInventory(directory,baseline);
      if(frames>highest){highest=frames;console.log(`SNIPER_PROGRESS source-frames ${highest}`);}
    }catch(error){fault=error;controller.abort(error);}
  };
  const timer=setInterval(observe,5000);
  try{
    const result=await action(controller.signal);observe();
    if(fault)throw fault;
    return result;
  }finally{clearInterval(timer);}
}
