/** Phase protocol tests against the same fake SDK; no browser or media process runs. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {batchFixture} from './native_short_batched_render_fixture.mjs';
import {runNativeBatchedRender} from '../producer/studio/native_short_batched_render.mjs';
import {runNativeShortCapture,nativeCaptureQcPoints} from '../producer/studio/native_short_capture.mjs';
import {nativeCaptureHash} from '../producer/studio/native_short_capture_context.mjs';
import {nativeSourceCacheEntry} from '../producer/studio/native_source_cache.mjs';
import {planNativeShortQc,captureNativeShortQcChunk,finishNativeShortQc,nativeShortQcPhaseCli}
  from '../producer/studio/native_short_qc_phase.mjs';

async function withPicture(action, totalFrames=400, maximum=4) {
  const f=batchFixture(totalFrames);
  f.sdk.extractMediaMetadata=async()=>maximum===1?{width:20000,height:20000}:{width:12000,height:8000};
  try {
    const picture=await runNativeBatchedRender(f.request,{sdk:f.sdk,encode:f.encode});
    assert.equal(picture.status,'picture-encoded-awaiting-parent-qc',picture.error);
    assert.equal(picture.batchPlan.maximumFrames,maximum);
    await action(f,picture);
  }finally{f.cleanup();}
}

function newOutput(f) {
  const donor=f.request.output,output=path.join(f.root,'retry');fs.mkdirSync(output);
  fs.copyFileSync(path.join(donor,'picture.mp4'),path.join(output,'picture.mp4'));
  const file=path.join(donor,'batched-picture.json');
  f.request={...f.request,output,pictureDonor:donor,pins:{[file]:nativeCaptureHash(file)}};
}

const scheduleFile=f=>path.join(f.request.output,'native-qc-phases/schedule.json');
const chunkFile=(f,index)=>path.join(f.request.output,'native-qc-phases',`chunk-${String(index).padStart(3,'0')}`,'receipt.json');
const read=file=>JSON.parse(fs.readFileSync(file,'utf8'));
const change=(file,mutate)=>{const row=read(file);mutate(row);fs.writeFileSync(file,JSON.stringify(row));};

async function completeChunks(f, planned) {
  const results=[];
  for(let index=0;index<planned.chunkCount;index++){
    const result=await captureNativeShortQcChunk(f.request,{index,expectedScheduleSha256:planned.scheduleSha256},{sdk:f.sdk,encode:f.encode});
    assert.equal(result.status,'native-qc-chunk-complete',result.error);results.push(result);
  }
  return results;
}

test('phases preserve exact existing forward/reverse occurrences, seeds and four-frame session bound',()=>withPicture(async f=>{
  const first=f.calls.frames.length,original=await runNativeShortCapture(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(original.status,'native-references-and-seek-states-pass',original.error);
  const originalCalls=f.calls.frames.slice(first);newOutput(f);
  const before=f.calls.frames.length,planned=await planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode});
  assert.ok(planned.chunkCount>1&&planned.chunkCount<=128);
  const schedule=read(scheduleFile(f));
  assert.ok(schedule.chunks.every(chunk=>chunk.length>0&&chunk.length<=48));
  await completeChunks(f,planned);
  const result=await finishNativeShortQc(f.request,planned.scheduleSha256,{sdk:f.sdk,encode:f.encode});
  assert.equal(result.status,'native-references-and-seek-states-pass');
  const receipt=read(path.join(f.request.output,'native-frames.json'));
  assert.deepEqual(receipt.frames.map(row=>row.frame),nativeCaptureQcPoints(f.plan,true,4));
  assert.deepEqual(f.calls.frames.slice(before),originalCalls);
  assert.ok(receipt.sessions.every(row=>row.frames.length+1<=4&&row.sessionClosed&&row.mediaGuardDisposed));
  assert.ok(receipt.sessions.every(row=>row.reverseSeed.frame===f.plan.canvas.totalFrames-1));
  assert.equal(f.calls.sessionCloses,f.calls.sessions.length);
}));

test('schedule digest is mandatory and altered schedules fail before any browser',()=>withPicture(async f=>{
  const plan=await planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode}),count=f.calls.sessions.length;
  await assert.rejects(()=>captureNativeShortQcChunk(f.request,{index:0},{sdk:f.sdk,encode:f.encode}),/SHA256/);
  change(scheduleFile(f),row=>row.chunks[0][0].frames.reverse());
  await assert.rejects(()=>captureNativeShortQcChunk(f.request,{index:0,expectedScheduleSha256:plan.scheduleSha256},{sdk:f.sdk,encode:f.encode}),/digest differs/);
  assert.equal(f.calls.sessions.length,count);
}));

test('sequential cache admission retains new timing receipts without changing exact phase input identity',()=>withPicture(async f=>{
  f.request.sourceCacheMode='acquire-sequential-sdr';f.sdk.isHdrColorSpace=()=>false;let admissions=0;
  f.sdk.extractAllVideoFrames=async(videos,project,options)=>{
    const cached=nativeSourceCacheEntry({project,request:f.request,fps:options.fps,rate:25},videos[0]);
    return {success:true,errors:[],durationMs:++admissions,phaseBreakdown:{cacheHits:1,cacheMisses:0},
      extracted:[{videoId:videos[0].id,outputDir:cached.entry,framePaths:cached.framePaths,totalFrames:cached.names.length}]};
  };
  const plan=await planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode});await completeChunks(f,plan);
  const result=await finishNativeShortQc(f.request,plan.scheduleSha256,{sdk:f.sdk,encode:f.encode});
  assert.equal(result.status,'native-references-and-seek-states-pass');
  const receipt=read(path.join(f.request.output,'native-frames.json'));
  assert.equal(admissions,plan.chunkCount+2);
  assert.equal(receipt.sourceCacheAcquisition.entries[0].sdkResult.durationMs,admissions);
  assert.ok(receipt.sourceCacheAcquisition.entries[0].startedAt);
},80));

test('even a newly supplied digest cannot authorize a reduced schedule',()=>withPicture(async f=>{
  await planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode});
  change(scheduleFile(f),row=>row.chunks.pop());
  const result=await captureNativeShortQcChunk(f.request,{index:0,expectedScheduleSha256:nativeCaptureHash(scheduleFile(f))},{sdk:f.sdk,encode:f.encode});
  assert.equal(result.status,'failed');assert.match(result.error,/schedule changed/);
}));

test('changed source bytes between plan and chunk fail without a passing receipt',()=>withPicture(async f=>{
  const plan=await planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode});
  fs.appendFileSync(path.join(f.request.project,'assets/source.mp4'),' changed');
  const result=await captureNativeShortQcChunk(f.request,{index:0,expectedScheduleSha256:plan.scheduleSha256},{sdk:f.sdk,encode:f.encode});
  assert.equal(result.status,'failed');
  assert.equal(fs.existsSync(path.join(f.request.output,'native-frames.json')),false);
}));

test('interrupted session keeps failed evidence, runs disposal and cannot finish',()=>withPicture(async f=>{
  const plan=await planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode});
  f.failFrame=read(scheduleFile(f)).chunks[0][0].frames[0];
  const result=await captureNativeShortQcChunk(f.request,{index:0,expectedScheduleSha256:plan.scheduleSha256},{sdk:f.sdk,encode:f.encode});
  assert.equal(result.status,'failed');assert.match(result.error,/TEST screenshot decode failure/);
  const receipt=read(chunkFile(f,0));
  assert.equal(receipt.sessions[0].sessionClosed,true);assert.equal(receipt.sessions[0].serverClosed,true);
  await assert.rejects(()=>finishNativeShortQc(f.request,plan.scheduleSha256,{sdk:f.sdk,encode:f.encode}),/incomplete/);
  assert.equal(fs.existsSync(path.join(f.request.output,'native-frames.json')),false);
}));

for(const [name,mutate] of [
  ['omitted occurrence',row=>row.frames.pop()],
  ['reordered occurrences',row=>row.frames.reverse()],
  ['duplicated chunk index',row=>{row.index=1;}],
  ['changed scene state',row=>{row.frames[0].visualState=[];}],
  ['changed source payload',row=>{row.frames[0].payload[0].frameIndex=-1;}],
  ['missing typography',row=>{delete row.frames[0].typographyEvidence;}],
  ['changed typography',row=>{row.frames[0].typography.titleClip='changed';}],
  ['missing reverse seed',row=>{delete row.sessions[0].reverseSeed;}],
  ['incomplete disposal',row=>{row.sessions[0].mediaGuardDisposed=false;}],
  ['empty original-media contract',row=>{row.sessions[0].originalMedia.contract=[];}],
  ['wrong schedule binding',row=>{row.scheduleSha256='f'.repeat(64);}],
])test(`finish rejects ${name}`,()=>withPicture(async f=>{
  const plan=await planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode});await completeChunks(f,plan);
  change(chunkFile(f,0),mutate);
  await assert.rejects(()=>finishNativeShortQc(f.request,plan.scheduleSha256,{sdk:f.sdk,encode:f.encode}));
  assert.equal(fs.existsSync(path.join(f.request.output,'native-frames.json')),false);
},80));

test('finish rejects missing chunks and does not infer completion from JPEG files',()=>withPicture(async f=>{
  const plan=await planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode});
  await captureNativeShortQcChunk(f.request,{index:0,expectedScheduleSha256:plan.scheduleSha256},{sdk:f.sdk,encode:f.encode});
  await assert.rejects(()=>finishNativeShortQc(f.request,plan.scheduleSha256,{sdk:f.sdk,encode:f.encode}),/ENOENT/);
}));

for(const target of ['frame','seed'])test(`finish rejects changed ${target} image bytes`,()=>withPicture(async f=>{
  const plan=await planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode});await completeChunks(f,plan);
  const chunk=read(chunkFile(f,0));
  const row=target==='frame'?chunk.frames[0]:chunk.sessions[0].reverseSeed;
  fs.appendFileSync(row.path,' changed');
  await assert.rejects(()=>finishNativeShortQc(f.request,plan.scheduleSha256,{sdk:f.sdk,encode:f.encode}),/image bytes changed/);
},80));

test('plan/chunk/finish destinations are exclusive',()=>withPicture(async f=>{
  const plan=await planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode});
  await assert.rejects(()=>planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode}),/EEXIST/);
  await completeChunks(f,plan);
  await assert.rejects(()=>captureNativeShortQcChunk(f.request,{index:0,expectedScheduleSha256:plan.scheduleSha256},{sdk:f.sdk,encode:f.encode}),/EEXIST/);
  await finishNativeShortQc(f.request,plan.scheduleSha256,{sdk:f.sdk,encode:f.encode});
  await assert.rejects(()=>finishNativeShortQc(f.request,plan.scheduleSha256,{sdk:f.sdk,encode:f.encode}),/EEXIST/);
},80));

test('strict CLI rejects missing digest, extra plan options and invalid chunk index',()=>withPicture(async f=>{
  const file=path.join(f.root,'request.json');fs.writeFileSync(file,JSON.stringify(f.request));
  await assert.rejects(()=>nativeShortQcPhaseCli([file,'plan','--schedule-sha256','f'.repeat(64)]));
  await assert.rejects(()=>nativeShortQcPhaseCli([file,'chunk','0']));
  await assert.rejects(()=>nativeShortQcPhaseCli([file,'finish','--schedule-sha256','F'.repeat(64)]));
  await assert.rejects(()=>nativeShortQcPhaseCli([file,'chunk','-1','--schedule-sha256','f'.repeat(64)]));
},20));

test('valid legacy absent forward authority explicitly selects unchanged full replay without a schedule',()=>withPicture(async f=>{
  change(path.join(f.request.output,'batched-picture.json'),row=>{delete row.forwardQc;});
  const before=f.calls.frames.length,result=await planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode});
  assert.deepEqual(result,{status:'native-qc-phases-ineligible',reason:'forward-evidence-unavailable'});
  assert.equal(fs.existsSync(scheduleFile(f)),false);assert.equal(f.calls.frames.length,before);
  const replay=await runNativeShortCapture(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(replay.status,'native-references-and-seek-states-pass',replay.error);
  assert.deepEqual(f.calls.frames.slice(before),nativeCaptureQcPoints(f.plan,true,4));
},20));

test('one-frame sessions validate forward evidence before explicitly selecting unchanged full replay',()=>withPicture(async f=>{
  const before=f.calls.frames.length,result=await planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode});
  assert.deepEqual(result,{status:'native-qc-phases-ineligible',reason:'single-frame-session'});
  assert.equal(fs.existsSync(scheduleFile(f)),false);assert.equal(f.calls.frames.length,before);
  const replay=await runNativeShortCapture(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(replay.status,'native-references-and-seek-states-pass',replay.error);
  assert.deepEqual(f.calls.frames.slice(before),nativeCaptureQcPoints(f.plan,true,1));
},20,1));

for(const maximum of [4,1])test(`malformed present authority cannot select a compatibility fallback at max ${maximum}`,()=>withPicture(async f=>{
  change(path.join(f.request.output,'batched-picture.json'),row=>{row.forwardQc=null;});
  await assert.rejects(()=>planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode}),/authority differs/);
  assert.equal(fs.existsSync(scheduleFile(f)),false);
},20,maximum));

for(const [name,mutate] of [
  ['failed legacy picture',row=>{delete row.forwardQc;row.status='failed';}],
  ['changed legacy picture bytes',row=>{delete row.forwardQc;row.sha256='f'.repeat(64);}],
  ['empty legacy receipt',row=>{for(const key of Object.keys(row))delete row[key];}],
])test(`${name} cannot select a compatibility fallback`,()=>withPicture(async f=>{
  change(path.join(f.request.output,'batched-picture.json'),mutate);
  await assert.rejects(()=>planNativeShortQc(f.request,{sdk:f.sdk,encode:f.encode}));
  assert.equal(fs.existsSync(scheduleFile(f)),false);
},20));
