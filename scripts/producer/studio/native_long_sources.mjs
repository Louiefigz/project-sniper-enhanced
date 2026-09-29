/** Admit future cache allocation before the pinned SDK extracts any long sources.
 *
 * Source frames and SDK scratch land in the cache; samples and outputs land in the attempt, where
 * each owner already reserved what it writes at admission (native_short_pipeline.long_owner_disk).
 * Before extraction (after the bounded size probes) the owner grows its host-pool reservation by the
 * cache share atomically against every other member's reservation in the same shared space (an
 * APFS container or one filesystem; native_work_pool_disk.py), so two Longs can no longer pass a
 * free-space check against the same bytes.
 */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {nativeSourceMetadata,nativeSourceFileIdentity} from './native_source_identity.mjs';
import {openNativeSourcePlan,acquireNativeSources,stableSourceEvidence} from './native_source_acquisition.mjs';
import {inspectStoreEntry} from './native_source_store_entry.mjs';
import {nativeSourceFrameCount} from './runtime/frame-source-transport.mjs';

export const CONTENT_SOURCE_MODES=['acquire-content-store','acquire-content-store-sequential-sdr'];

/** Project measured source sizes with headroom; the continuous live disk guard stays mandatory.
 * `projection` is the request's attempt-side figures (native_long_contract.disk_projection). */
export function longStoragePlan(rows, projection) {
  const entries=new Map(),negotiated=rows.some(row=>row.hdr);
  for(const row of rows){
    assert.ok([row.width,row.height,row.frames].every(value=>Number.isSafeInteger(value)&&value>0));
    assert.ok(Number.isSafeInteger(row.bytesPerFrame)&&row.bytesPerFrame>0);
    const allocation=row.cached&&!negotiated?0:Math.ceil(row.bytesPerFrame*row.frames*1.6);
    entries.set(row.key,Math.max(entries.get(row.key)??0,allocation));
  }
  const sourceBytes=[...entries.values()].reduce((sum,value)=>sum+value,0);
  const {sampleBytes,outputBytes,miscBytes}=projection??{};
  assert.ok([sampleBytes,outputBytes,miscBytes].every(value=>Number.isSafeInteger(value)&&value>=0),
    'Long request lacks its attempt-side disk projection');
  // The SDK decodes into the store's private view and publishes by rename: frames and scratch stay in the cache.
  // Only the cache share is requested; the attempt share is evidence of the whole projection.
  const filesystems={cache:sourceBytes*2,output:sampleBytes+outputBytes+miscBytes};
  const plannedBytes=filesystems.cache+filesystems.output;
  assert.ok(Number.isSafeInteger(plannedBytes)&&plannedBytes>=0,'Unsafe long disk plan');
  return {sourceBytes,sampleBytes,outputBytes,plannedBytes,filesystems,reserveBytes:10*1024**3,
    basis:'Largest of source PNG samples × frame count × 1.6, plus simultaneous scratch, in the cache; '
      +'samples, estimated output and 1 GiB in the attempt; projection, not a guaranteed compression bound'};
}

/** The owner receipt is replaced atomically, so one read is a complete snapshot. */
function ownerRecord(file) {
  return JSON.parse(fs.readFileSync(file,'utf8'));
}

/** Ask the live native owner to grow its host-pool reservation by this plan's cache share; fail closed.
 * The owner publishes the grant only after the grown reservation is durable, so extraction after a
 * grant is always covered. While the refusal may clear the owner reports 'waiting' and retries (at
 * most 45 s, inside this bounded wait); a final refusal also aborts the owner. */
export async function requestLongDiskGrant(request, storage, environment=process.env, waitMs=60000) {
  const ownerFile=environment.SNIPER_NATIVE_EXPORT_OWNER;
  assert.ok(typeof ownerFile==='string'&&path.isAbsolute(ownerFile),'Long source extraction requires its native owner');
  const channel=ownerRecord(ownerFile).diskExpansion;
  assert.ok(channel?.status==='available'&&typeof channel.request==='string'
    &&path.dirname(channel.request)===path.dirname(ownerFile)&&!fs.existsSync(channel.request),
  'Long source extraction requires an owner that can still grow its host-pool disk reservation');
  const id=randomUUID(),pending=`${channel.request}.${process.pid}.pending`;
  fs.writeFileSync(pending,JSON.stringify({schemaVersion:1,id,directories:[
    {role:'cache',path:request.cache,bytes:storage.filesystems.cache}]}),{flag:'wx',mode:0o600});
  fs.renameSync(pending,channel.request);
  for(const until=Date.now()+waitMs;;){
    const grant=ownerRecord(ownerFile).diskGrant;
    if(grant?.id===id&&grant.status!=='waiting'){
      assert.equal(grant.status,'granted',`Long source allocation refused by the host pool: ${grant.reason}; `
        +'use selected media, a larger cache volume or wait for running work');
      return grant;
    }
    assert.ok(Date.now()<until,'The native owner did not answer the Long disk reservation request');
    await new Promise(resolve=>setTimeout(resolve,250));
  }
}

/** Include every distinct used range; a quiet opening cannot stand in for later footage. */
export function longSourceProbes(videos, rate) {
  const samples=[],seen=new Set();
  for(const video of videos){
    const key=JSON.stringify([video.src,video.mediaStart,video.end-video.start,video.nativeSourceFrameIndices]);
    if(seen.has(key))continue;
    seen.add(key);
    if(video.nativeSourceFrameIndices){
      const indices=video.nativeSourceFrameIndices;
      const selected=[...new Set([indices[0],indices[Math.floor(indices.length/2)],indices.at(-1)])];
      samples.push({...video,id:`budget-${samples.length}`,start:0,end:selected.length/rate,nativeSourceFrameIndices:selected});
      continue;
    }
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

function longVideo(context, video) {
  const file=path.resolve(context.project,video.src);
  assert.ok(file.startsWith(context.project+path.sep)&&fs.realpathSync(file)===file,'Long source must be staged locally');
  assert.ok(!video.loop&&(video.playbackRate===undefined||video.playbackRate===1),'Long source must use speed one');
  if(context.request.adapter!=='native-long')assert.ok([video.start,video.end,video.mediaStart].every(Number.isFinite)
    &&video.start>=0&&video.end>video.start&&video.end<=context.plan.canvas.totalFrames/context.rate&&video.mediaStart>=0,
  'Short source requires a finite retained interval within its timeline');
}

/** Rows share the store's content identity, so identical bytes are charged and extracted once.
 * Budgeting reads entry structure only (no frame hashing): acquisition admits by frame digest and
 * charges every entry this job ends up publishing, including a refused one it regenerates. */
async function inspectLongSources(context, plan) {
  const {sdk,request}=context,rows=[];
  const initialDisk=fs.statfsSync(request.output);
  for(const row of plan.rows){
    const metadata=await nativeSourceMetadata(context,row.source);
    rows.push({key:row.contentKey,file:row.source,cached:inspectStoreEntry(plan.store,row.contentKey,row.frames).state==='present',
      hdr:sdk.isHdrColorSpace(metadata.colorSpace),width:metadata.width,height:metadata.height,frames:row.frames});
  }
  const unique=new Map(rows.map(row=>[row.key,row]));
  const probeBytes=[...unique.values()].reduce((sum,row)=>sum+row.width*row.height*8*9,0);
  assert.ok(initialDisk.bavail*initialDisk.bsize>=probeBytes+10*1024**3,'Insufficient disk for bounded source probes');
  return rows;
}

/** Probe and admit projected allocation only when this job actually extracts. */
async function longStorage(context, rows) {
  const {work,request}=context;
  const sizes=await probeLongSourceSizes(context);
  for(const row of rows)row.bytesPerFrame=sizes.get(row.file);
  const storage=longStoragePlan(rows,request.diskProjection);
  const cacheDisk=fs.statfsSync(request.cache),outputDisk=fs.statfsSync(request.output);
  storage.cacheFreeBytes=cacheDisk.bavail*cacheDisk.bsize;storage.outputFreeBytes=outputDisk.bavail*outputDisk.bsize;
  // Replaces the old worker-local free-space check: the pool checks each shared space against every member.
  // A refusal is recorded in the owner receipt and the request file; the plan is written with its grant.
  storage.poolGrant=await requestLongDiskGrant(request,storage);
  fs.writeFileSync(path.join(work,'storage-plan.json'),JSON.stringify(storage,null,2),{flag:'wx'});
  return storage;
}

/** Complete SDK color negotiation in this job's private view; progress counts only this view. */
function longExtractor(context, plan, state) {
  return async owned=>{
    // Inspection ran before this job's lease: charge every entry it now owns, whatever it saw then.
    const ownedKeys=new Set(owned.map(row=>row.key));
    for(const row of state.rows)if(ownedKeys.has(row.key))row.cached=false;
    state.storage??=await longStorage(context,state.rows);
    state.receipt.storage=state.storage;
    const videos=structuredClone(context.result.composition.videos),before=JSON.stringify(videos);
    const identities=new Map(plan.rows.map(row=>[row.source,nativeSourceFileIdentity(row.source)]));
    const extracted=await extractSourceGroups(context,plan,videos);
    state.receipt.sdkCalls.push({phaseBreakdown:extracted.phaseBreakdown,durationMs:extracted.durationMs});state.persist();
    assert.ok(extracted.success&&extracted.errors.length===0&&extracted.extracted.length===videos.length,
      'Long source extraction failed before full picture render');
    assert.equal(JSON.stringify(videos),before,'Source ended before its declared window; author an explicit final-frame hold');
    for(const [file,identity] of identities)assert.deepEqual(nativeSourceFileIdentity(file),identity,'Long source changed');
    for(const row of plan.rows){
      const actual=extracted.extracted.find(item=>item.videoId===row.video.id);
      assert.equal(actual?.totalFrames,row.frames,
        'Decoded source lacks the declared final frame; author an explicit hold without truncating dialogue');
      assert.equal(actual.framePaths.size,actual.totalFrames,'Long source cache is incomplete');
      assert.equal(actual.outputDir,path.join(plan.view,row.pathName),'SDK used another source identity (clock or color negotiation differs)');
    }
  };
}

/** Sequential SDR keeps one SDK extraction active; normal acquisition keeps whole-program colour negotiation. */
async function extractSourceGroups(context, plan, videos) {
  const {sdk,project,work,fps,rate}=context;
  const sequential=context.request.sourceCacheMode==='acquire-content-store-sequential-sdr';
  const groups=sequential?videos.map(video=>[video]):[videos];
  const result={success:true,errors:[],extracted:[],phaseBreakdown:[],durationMs:0};
  for(const group of groups){
    const actual=await withSourceProgress(plan.view,signal=>sdk.extractAllVideoFrames(group,project,
      {fps,outputDir:path.join(work,'source-extraction'),format:'png',timelineEnd:context.plan.canvas.totalFrames/rate,
        maxTransientRetries:0,collectProbeFailures:true},signal,
      {...context.cfg,extractCacheDir:plan.view,extractCacheMaxBytes:Number.MAX_SAFE_INTEGER},path.join(work,'compiled')));
    if(!sequential)return actual;
    assert.ok(actual.success&&actual.errors.length===0&&actual.extracted.length===group.length,'Native source group failed');
    result.extracted.push(...actual.extracted);result.phaseBreakdown.push(actual.phaseBreakdown);result.durationMs+=actual.durationMs;
  }
  return result;
}

/** Use complete SDK color negotiation; conservatively charge cold space for HDR cache transforms. */
export async function prepareLongSources(context, {existingOnly=false}={}) {
  return prepareNativeSources(context,{existingOnly});
}

/** Share only newly digest-bound entries; legacy SDK caches are never adopted or migrated. */
export async function prepareNativeSources(context, {existingOnly=false}={}) {
  const plan=await openNativeSourcePlan(context,video=>longVideo(context,video));
  const long=context.request.adapter==='native-long',mode=long?'native-long':context.request.sourceCacheMode;
  assert.ok(long||CONTENT_SOURCE_MODES.includes(mode),'Unsupported native content source mode');
  const receipt={schemaVersion:2,scope:long?'native-long-content-source-store':'native-short-content-source-store',
    mode,status:'preparing',sdkCalls:[]};
  const state={receipt,rows:await inspectLongSources(context,plan),storage:null,
    persist:()=>fs.writeFileSync(path.join(context.work,'source-cache.json'),JSON.stringify(receipt,null,2))};
  if(mode==='acquire-content-store-sequential-sdr'){
    assert.ok(state.rows.every(row=>!row.hdr),'Sequential source acquisition does not admit HDR colour negotiation');
    receipt.maximumConcurrentExtractions=1;
  }
  try{
    await acquireNativeSources(context,plan,{receipt,extract:existingOnly?null:longExtractor(context,plan,state),persist:state.persist,
      collectBytes:()=>Math.max(context.cfg.extractCacheMaxBytes,(state.storage?.sourceBytes??0)*2)});
  }catch(error){receipt.status='failed';receipt.error=String(error?.stack||error);state.persist();throw error;}
  context.sourceCacheAcquisition={...stableSourceEvidence(receipt),storage:state.storage};
}

function directoryIdentity(directory) {
  const stat=fs.statSync(directory,{bigint:true});
  assert.ok(stat.isDirectory()&&!fs.lstatSync(directory).isSymbolicLink(),'Unsafe source cache directory');
  return `${stat.dev}:${stat.ino}:${stat.mtimeNs}`;
}

/** SDK atomic publication can rename a partial entry during progress observation. */
function sourceDirectoryFrames(file, previous) {
  try{
    const identity=directoryIdentity(file);
    const frames=identity===previous?0:fs.readdirSync(file).filter(name=>/^frame_\d+\.(png|jpg)$/.test(name)).length;
    return {identity,frames};
  }catch(error){if(error.code==='ENOENT')return null;throw error;}
}

/** Only changed/new cache directories can represent newly allocated source frames. */
export function sourceFrameInventory(directory, baseline=new Map()) {
  const entries=fs.readdirSync(directory,{withFileTypes:true});
  assert.ok(entries.length<=4096,'Source cache progress directory inventory exceeds its bound');
  const identities=new Map();let frames=0;
  for(const entry of entries){
    if(!entry.isDirectory()||!entry.name.startsWith('hfcache-'))continue;
    const file=path.join(directory,entry.name);
    const observed=sourceDirectoryFrames(file,baseline.get(entry.name));
    if(!observed)continue;
    identities.set(entry.name,observed.identity);frames+=observed.frames;
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
