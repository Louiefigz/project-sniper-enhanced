import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {longCapturePoints,checkLongScene} from '../producer/studio/native_long_capture.mjs';
import {createHash} from 'node:crypto';
import {longStoragePlan,longSourceProbes,probeLongSourceSizes,sourceFrameInventory,withSourceProgress,
  prepareLongSources,requestLongDiskGrant} from '../producer/studio/native_long_sources.mjs';
import {nativeSourceCacheIdentity} from '../producer/studio/native_source_identity.mjs';
import {nativeSourceFrameCount} from '../producer/studio/runtime/frame-source-transport.mjs';

test('fifteen minute seam checks include last frame, exact cuts and reverse visits',()=>{
  const plan={canvas:{frameRate:'30/1',totalFrames:27000},scenes:[
    {startFrame:0,endFrame:18000},{startFrame:18000,endFrame:26999},{startFrame:26999,endFrame:27000}]};
  const points=longCapturePoints(plan),forward=points.slice(0,points.length/2);
  for(const frame of [0,17999,18000,18001,26998,26999])assert.ok(forward.includes(frame));
  assert.deepEqual(points.slice(points.length/2),forward.slice().reverse());
});

test('future allocation deduplicates identical ranges and charges each filesystem its own bytes',()=>{
  const row={key:'same',width:1920,height:1080,frames:27000,bytesPerFrame:100000,cached:false};
  const projection={sampleBytes:1920*1080*900,outputBytes:13996800000,miscBytes:1024**3};
  const once=longStoragePlan([row],projection),twice=longStoragePlan([row,row],projection);
  assert.equal(once.plannedBytes,twice.plannedBytes);
  assert.equal(once.sourceBytes,Math.ceil(100000*27000*1.6));
  assert.deepEqual(once.filesystems,{cache:once.sourceBytes*2,output:1920*1080*900+13996800000+1024**3});
  assert.equal(once.plannedBytes,once.filesystems.cache+once.filesystems.output);
  assert.equal(once.reserveBytes,10*1024**3);
  assert.equal(longStoragePlan([{...row,cached:true}],projection).sourceBytes,0);
  assert.equal(longStoragePlan([row,{...row,cached:true}],projection).sourceBytes,once.sourceBytes);
  assert.equal(longStoragePlan([{...row,cached:true,hdr:true}],projection).sourceBytes,once.sourceBytes);
  assert.throws(()=>longStoragePlan([{...row,frames:NaN}],projection));
  assert.throws(()=>longStoragePlan([row],undefined),/disk projection/);
  assert.throws(()=>longStoragePlan([row],{...projection,outputBytes:-1}),/disk projection/);
});

test('source probes cover later used windows and deduplicate only identical ranges',()=>{
  const first={src:'assets/test.mp4',start:0,end:10,mediaStart:0};
  const later={...first,start:10,end:30,mediaStart:100};
  const samples=longSourceProbes([first,{...first,id:'duplicate'},later],30);
  assert.equal(samples.length,6);
  assert.ok(samples.some(sample=>sample.mediaStart===100));
  assert.ok(samples.some(sample=>sample.mediaStart>119));
  assert.equal(new Set(samples.map(sample=>sample.id)).size,6);
});

test('a source ending short fails the bounded probe before allocating its full cache',async()=>{
  const video={id:'end',src:'assets/test.mp4',start:0,end:10,mediaStart:0};
  const sdk={extractAllVideoFrames:async samples=>{
    samples.at(-1).end-=1/30;
    return {success:true,errors:[],extracted:samples.map(row=>({videoId:row.id}))};
  }};
  await assert.rejects(probeLongSourceSizes({sdk,result:{composition:{videos:[video]}},
    project:'/TEST-unused',work:'/TEST-unused',rate:30,fps:{num:30,den:1}}),/source probe.*window/i);
});

test('a stale outgoing picture at the exact cut fails before the master',async()=>{
  const plan={scenes:[{startFrame:30,endFrame:60,mediaIds:['incoming']}]};
  await assert.rejects(checkLongScene({evaluate:async()=>['incoming','outgoing']},30,plan),/Stale/);
  assert.deepEqual(await checkLongScene({evaluate:async()=>['incoming']},30,plan),{frame:30,mediaIds:['incoming']});
});

test('source progress counts actual new frames and does not revive unchanged caches',async()=>{
  const root=fs.mkdtempSync(path.join(os.tmpdir(),'long-progress-'));
  try{
    const entry=path.join(root,'hfcache-test');fs.mkdirSync(entry);
    fs.writeFileSync(path.join(entry,'frame_000001.png'),'test fixture only');
    const baseline=sourceFrameInventory(root).identities;
    assert.equal(sourceFrameInventory(root,baseline).frames,0);
    fs.writeFileSync(path.join(entry,'frame_000002.png'),'test fixture only');
    fs.writeFileSync(path.join(entry,'metadata.json'),'{}');
    assert.equal(sourceFrameInventory(root,baseline).frames,2);
    assert.equal(await withSourceProgress(root,async signal=>{
      assert.equal(signal.aborted,false);return 'complete';
    }),'complete');
    await assert.rejects(withSourceProgress(root,async()=>{throw new Error('TEST extraction failed');}),/extraction failed/);
    fs.renameSync(entry,path.join(root,'hfcache-published'));
    assert.equal(sourceFrameInventory(root,baseline).frames,2);
  }finally{fs.rmSync(root,{recursive:true,force:true});}
});

/** TEST decoder at the SDK boundary: complete names hit, misses publish by rename; counts view decodes.
 * Like the SDK, one HDR source in a call keys every SDR source with `<clock>+sdr2hdr-<transfer>`. */
function longFakeSdk(calls, spaces={}) {
  const isHdr=space=>['smpte2084','arib-std-b67'].includes(space?.colorTransfer);
  return {extractMediaMetadata:async file=>({width:64,height:36,colorSpace:spaces[path.basename(file)]??null}),isHdrColorSpace:isHdr,
    async extractAllVideoFrames(videos, project, options, signal, config) {
      fs.mkdirSync(config.extractCacheDir,{recursive:true});const extracted=[];
      const space=video=>spaces[path.basename(video.src)]??null,anyHdr=videos.some(video=>isHdr(space(video)));
      const dominant=videos.some(video=>space(video)?.colorTransfer==='smpte2084')?'pq':'hlg';
      for(const video of videos){
        const transform=anyHdr&&!isHdr(space(video))?`sniper-zero-clock-v1+sdr2hdr-${dominant}`:'sniper-zero-clock-v1';
        const context={project,request:{cache:config.extractCacheDir},fps:options.fps};
        const name=nativeSourceCacheIdentity(context,video,config.extractCacheDir,transform).entry;
        const frames=nativeSourceFrameCount(video.end-video.start,options.fps.num/options.fps.den);
        if(!fs.existsSync(path.join(name,'.hf-complete'))){
          if(config.extractCacheDir.includes('/views/'))calls.viewDecodes++;
          const partial=`${name}.partial-TEST`;fs.mkdirSync(partial);
          for(let index=1;index<=frames;index++)fs.writeFileSync(path.join(partial,`frame_${String(index).padStart(5,'0')}.png`),`TEST ${index}`);
          fs.writeFileSync(path.join(partial,'.hf-complete'),'');fs.renameSync(partial,name);
        }
        const names=fs.readdirSync(name).filter(file=>file.startsWith('frame_')).sort();
        extracted.push({videoId:video.id,srcPath:path.resolve(project,video.src),outputDir:name,totalFrames:names.length,
          framePaths:new Map(names.map((file,index)=>[index,path.join(name,file)]))});
      }
      return {success:true,errors:[],extracted,phaseBreakdown:{},durationMs:1};
    }};
}

/** TEST owner: advertises the disk channel (native_run_admission) and answers one request the way studio/native_run_disk.serve_disk_request does. */
function fakeOwner(root, label, answer) {
  const file=path.join(root,`${label}.render.json`),request=path.join(root,`${label}.disk-request.json`),requests=[];
  const record={startedAt:new Date().toISOString(),runDeadlineSeconds:600,
    ...(answer?{diskExpansion:{status:'available',request}}:{})};
  fs.writeFileSync(file,JSON.stringify(record));
  const timer=setInterval(()=>{
    if(!answer||requests.length||!fs.existsSync(request))return;
    const value=JSON.parse(fs.readFileSync(request,'utf8'));requests.push(value);
    const grant=answer(value);
    if(grant===null)return; // TEST: an owner that never answers
    fs.writeFileSync(`${file}.pending`,JSON.stringify({...record,diskGrant:{id:value.id,...grant}}));
    fs.renameSync(`${file}.pending`,file);
  },20);
  return {file,request,requests,stop:()=>clearInterval(timer)};
}

/** TEST long attempts sharing one cache; each run has its own owner answering with `answer`. */
function longStoreFixture(root, calls) {
  const cache=path.join(root,'cache');fs.mkdirSync(cache);
  const sha=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');
  const tools=Object.fromEntries(['ffmpeg','ffprobe'].map(name=>{const file=path.join(root,name);fs.writeFileSync(file,`TEST ${name}`);return [name,file];}));
  return async(label,{mixed=false,answer=()=>({status:'granted'}),existingOnly=false}={})=>{
    const project=path.join(root,`project-${label}`),output=path.join(root,`attempt-${label}`),work=path.join(output,'work');
    fs.mkdirSync(path.join(project,'assets'),{recursive:true});fs.mkdirSync(work,{recursive:true});
    const sources=['source.mp4',...(mixed?['screen.mp4']:[])].map(name=>path.join(project,'assets',name));
    for(const file of sources)fs.writeFileSync(file,`TEST long source bytes ${path.basename(file)}`);
    const spaces=mixed?{'source.mp4':{colorTransfer:'arib-std-b67'},'screen.mp4':{colorTransfer:'bt709'}}:{};
    const videos=[{id:'long-0',src:'assets/source.mp4',mediaStart:0,start:0,end:2},
      ...(mixed?[{id:'long-1',src:'assets/screen.mp4',mediaStart:0,start:0,end:2}]:[])];
    const context={sdk:longFakeSdk(calls,spaces),project,work,fps:{num:25,den:1},rate:25,runtimeLibrarySha256:'4'.repeat(64),
      request:{adapter:'native-long',cache,output,sampleCount:2,tools,
        diskProjection:{sampleBytes:1920*1080*2,outputBytes:1920*1080*50/4,miscBytes:1024**3},
        pins:Object.fromEntries([...sources,...Object.values(tools)].map(file=>[file,sha(file)]))},
      plan:{canvas:{width:1920,height:1080,totalFrames:50}},cfg:{extractCacheMaxBytes:64*1024**3},
      result:{composition:{videos}}};
    const owner=fakeOwner(root,label,answer),previous=process.env.SNIPER_NATIVE_EXPORT_OWNER;
    process.env.SNIPER_NATIVE_EXPORT_OWNER=owner.file;
    try{await prepareLongSources(context,{existingOnly});return {context,owner};}
    finally{
      owner.stop();
      if(previous===undefined)delete process.env.SNIPER_NATIVE_EXPORT_OWNER;else process.env.SNIPER_NATIVE_EXPORT_OWNER=previous;
    }
  };
}

test('existing-only Long acquisition never turns missing full sources into a cold decode',async()=>{
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'sniper-long-existing-'))),calls={viewDecodes:0};
  try{
    const run=longStoreFixture(root,calls);
    await assert.rejects(run('cold',{existingOnly:true}));
    assert.equal(calls.viewDecodes,0);
    await run('admitted');
    const previous=calls.viewDecodes;
    const result=await run('retained',{existingOnly:true});
    assert.equal(calls.viewDecodes,previous);
    assert.equal(result.owner.requests.length,0);
    assert.equal(result.context.sourceEntries.get('long-0').outcome,'store-hit');
  }finally{fs.rmSync(root,{recursive:true,force:true});}
});

test('long sources publish through the shared store; a revision copy probes, charges and decodes nothing',async()=>{
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'sniper-long-store-'))),calls={viewDecodes:0};
  try{
    const run=longStoreFixture(root,calls);
    const {context:first,owner}=await run('v1');
    assert.equal(calls.viewDecodes,1);assert.ok(fs.existsSync(path.join(first.work,'storage-plan.json')));
    assert.equal(first.sourceEntries.get('long-0').outcome,'published-by-this-job');
    const storage=first.sourceCacheAcquisition.storage;
    assert.deepEqual(owner.requests.map(row=>row.directories),[[
      {role:'cache',path:first.request.cache,bytes:storage.filesystems.cache}]],
    'one request before the decode, for the cache share only: the attempt share is reserved at owner admission');
    assert.equal(storage.poolGrant.status,'granted');
    assert.equal(JSON.parse(fs.readFileSync(path.join(first.work,'storage-plan.json'),'utf8')).poolGrant.status,'granted');
    const {context:second,owner:revision}=await run('v2');
    assert.equal(calls.viewDecodes,1,'the revision copy decoded nothing');
    assert.equal(fs.existsSync(path.join(second.work,'storage-plan.json')),false,'nothing was probed or charged');
    assert.equal(revision.requests.length,0,'a store hit asks the pool for nothing');
    assert.equal(second.sourceEntries.get('long-0').outcome,'store-hit');
    assert.equal(second.sourceEntries.get('long-0').entry,first.sourceEntries.get('long-0').entry);
    assert.ok(second.sourceCacheAcquisition.entries.every(row=>row.entry.includes('/sniper-source-store-v1/entries-v2/')&&/^[a-f0-9]{64}$/.test(row.frameDigest)));
    const {context:mixed}=await run('mixed',{mixed:true});
    assert.equal(mixed.sourceEntries.get('long-0').contentBlob.transform,'sniper-zero-clock-v1');
    assert.equal(mixed.sourceEntries.get('long-1').contentBlob.transform,'sniper-zero-clock-v1+sdr2hdr-hlg',
      'an SDR source in an HDR composition is keyed by its negotiated conversion');
    assert.equal(mixed.sourceEntries.get('long-0').outcome,'store-hit','the same HDR bytes and window reuse their entry');
    assert.equal(mixed.sourceEntries.get('long-1').outcome,'published-by-this-job');
  }finally{fs.rmSync(root,{recursive:true,force:true});}
});

test('a refused or unavailable host-pool reservation stops long source extraction after the bounded probes',async()=>{
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'sniper-long-refused-'))),calls={viewDecodes:0};
  try{
    const run=longStoreFixture(root,calls);
    const reason='NativeWorkQueued: Disk expansion refused: disk headroom is reserved by running members; TEST';
    await assert.rejects(run('refused',{answer:()=>({status:'refused',reason})}),/refused by the host pool: NativeWorkQueued/);
    assert.equal(calls.viewDecodes,0,'no source extraction after the refusal');
    assert.equal(JSON.parse(fs.readFileSync(path.join(root,'attempt-refused/work/source-cache.json'),'utf8')).status,'failed');
    assert.equal(fs.existsSync(path.join(root,'attempt-refused/work/storage-plan.json')),false,'a plan is written only with its grant');
    const asked=JSON.parse(fs.readFileSync(path.join(root,'refused.disk-request.json'),'utf8'));
    assert.deepEqual(asked.directories.map(row=>row.role),['cache'],'the refused demand stays on record');
    await assert.rejects(run('ownerless',{answer:null}),/can still grow its host-pool disk reservation/);
    assert.equal(fs.existsSync(path.join(root,'ownerless.disk-request.json')),false);
    assert.equal(calls.viewDecodes,0);
  }finally{fs.rmSync(root,{recursive:true,force:true});}
});

test('a waiting answer keeps the child waiting until the owner grants',async()=>{
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'sniper-long-waiting-')));
  let answers=0;
  const owner=fakeOwner(root,'waiting',()=>null);
  const timer=setInterval(()=>{
    if(!owner.requests.length)return;
    const record=JSON.parse(fs.readFileSync(owner.file,'utf8')),id=owner.requests[0].id;
    answers++;
    const diskGrant=answers<4?{id,status:'waiting',lastWaitReason:'TEST running members'}:{id,status:'granted'};
    fs.writeFileSync(`${owner.file}.pending`,JSON.stringify({...record,diskGrant}));fs.renameSync(`${owner.file}.pending`,owner.file);
  },50);
  try{
    const request={cache:root,output:root},storage={filesystems:{cache:1,output:2}};
    const grant=await requestLongDiskGrant(request,storage,{SNIPER_NATIVE_EXPORT_OWNER:owner.file},5000);
    assert.equal(grant.status,'granted');assert.ok(answers>=4,'the waiting answers were not treated as final');
  }finally{clearInterval(timer);owner.stop();fs.rmSync(root,{recursive:true,force:true});}
});

test('an owner that never answers the disk request fails closed at the bounded wait',async()=>{
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'sniper-long-silent-')));
  const owner=fakeOwner(root,'silent',()=>null);
  try{
    const request={cache:root,output:root},storage={filesystems:{cache:1,output:2}};
    await assert.rejects(requestLongDiskGrant(request,storage,{SNIPER_NATIVE_EXPORT_OWNER:owner.file},300),/did not answer/);
    assert.equal(owner.requests.length,1);
    await assert.rejects(requestLongDiskGrant(request,storage,{SNIPER_NATIVE_EXPORT_OWNER:owner.file},300),
      /can still grow/,'one request per owner: a second is never silently answered by the first grant');
  }finally{owner.stop();fs.rmSync(root,{recursive:true,force:true});}
});

test('scoped references include exact private endpoints and never sample unfinished neighbors',()=>{
  const plan={canvas:{frameRate:'30/1',totalFrames:360},scenes:[
    {startFrame:0,endFrame:120},{startFrame:120,endFrame:240},{startFrame:240,endFrame:360}]};
  const points=longCapturePoints(plan,{frameRange:[120,240]});
  assert.deepEqual(points,[120,121,122,180,238,239,239,238,180,122,121,120]);
  assert.ok(points.every(frame=>120<=frame&&frame<240));
  assert.throws(()=>longCapturePoints(plan,{frameRange:[240,361]}),/Invalid capture scope/);
});
