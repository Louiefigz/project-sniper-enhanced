/** Fictional JPEG/SDK/encoder fixture; no decode, browser, editorial or runtime qualification. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {batchFixture} from './native_short_batched_render_fixture.mjs';
import {retainedFrameHash} from '../producer/studio/native_retained_frames.mjs';
import {renderFinalSegment} from '../producer/studio/native_segments/render.mjs';

/** Reuse the established fake SDK and real source-store path with zero compiled videos. */
function graphicsSdk(f) {
  const compile=f.sdk.runCompileStage;
  f.sdk.runCompileStage=async options=>{
    const result=await compile(options);
    Object.assign(result.composition,{width:f.plan.canvas.width,height:f.plan.canvas.height,videos:[],
      audios:[{id:'TEST-dialogue',src:f.video.src,start:0,end:f.video.end}]});
    return result;
  };
  f.sdk.isHdrColorSpace=()=>false;
  f.sdk.extractMediaMetadata=async()=>{throw new Error('TEST graphics fixture must not decode/probe media');};
  f.sdk.createFrameLookupTable=(videos,extracted)=>{
    assert.deepEqual(videos,[]);assert.deepEqual(extracted,[]);
    return {getActiveFramePayloads:()=>new Map()};
  };
}

/** A fake supervising receipt supplies only the source-store test deadline; no production seal. */
function testDeadline(f,t) {
  const owner=path.join(f.root,'TEST-owner.json'),previous=process.env.SNIPER_NATIVE_EXPORT_OWNER;
  fs.writeFileSync(owner,JSON.stringify({startedAt:new Date().toISOString(),runDeadlineSeconds:120}));
  process.env.SNIPER_NATIVE_EXPORT_OWNER=owner;
  t.after(()=>{if(previous===undefined)delete process.env.SNIPER_NATIVE_EXPORT_OWNER;
    else process.env.SNIPER_NATIVE_EXPORT_OWNER=previous;});
}

/** Build one absolute [50,110) codec window in a complete 140-frame fictional program. */
export function retainedFixture(t,{long=true}={}) {
  const f=batchFixture(140);t.after(()=>f.cleanup());
  Object.assign(f.plan.canvas,{width:long?1920:1080,height:long?1080:1920});
  f.plan.canvas.pictureViews=[];graphicsSdk(f);testDeadline(f,t);
  const window={index:0,gop:0,startFrame:50,endFrame:110,id:'section-000',generation:1,inputIdentity:'a'.repeat(64)};
  f.request.adapter=long?'native-long':'native-short';
  f.request.revision={mode:long?'initial-long':'full-render',identity:'b'.repeat(64),
    canvas:f.plan.canvas,renderWindows:[window],grid:{timescale:25},probes:[]};
  fs.writeFileSync(path.join(f.request.project,long?'LONG-PROJECT.json':'SHORT-PROJECT.json'),JSON.stringify(f.plan));
  const retained=60*f.plan.canvas.width*f.plan.canvas.height*4;
  f.request.diskProjection={retainedFrameBytes:retained,outputBytes:retained+Math.ceil(140*f.plan.canvas.width*f.plan.canvas.height/4)};
  f.request.pins={};
  f.run=async(name='work',encode=f.encode)=>renderFinalSegment(f.request,0,path.join(f.request.output,name),
    {sdk:f.sdk,encode,version:'TEST-encoder'});
  return f;
}

/** Freeze actual tiny donor bytes/pins; the fixture never calls this a compatible production donor. */
export function retainedPlan(f,dirty=[72,73],checkFrames=[50,60,71,74,91,109]) {
  const captureFrames=[...new Set([...dirty,...checkFrames])].sort((a,b)=>a-b);
  const root=path.join(f.root,'TEST-donor'),framesDir=path.join(root,'frames');
  fs.mkdirSync(framesDir,{recursive:true});
  const frames=Array.from({length:60},(_,offset)=>{
    const frame=offset+50,file=path.join(framesDir,`frame_${String(frame).padStart(6,'0')}.jpg`);
    fs.writeFileSync(file,checkFrames.includes(frame)?`TEST JPEG screenshot frame ${frame}`:`TEST prior JPEG ${frame}`);
    const row={frame,path:file,bytes:fs.statSync(file).size,sha256:retainedFrameHash(file,4096),origin:'captured'};
    f.request.pins[file]=row.sha256;return row;
  });
  const manifest=path.join(root,'retained-frames.json');fs.writeFileSync(manifest,'TEST donor manifest');
  const window=f.request.revision.renderWindows[0];
  const plan={window,planIdentity:f.request.revision.identity,frameRange:[50,110],captureFrames,checkFrames,
    copyFrames:frames.map(row=>row.frame).filter(frame=>!captureFrames.includes(frame)),
    baseline:{manifest:{path:manifest,sha256:retainedFrameHash(manifest,4096)},frames}};
  f.request.sectionRepair={parentAttempt:root};publishPlan(f,plan);
  return plan;
}

/** Publish TEST authored bytes before invoking the real cold sidecar reader. */
export function publishPlan(f,plan) {
  const file=path.join(f.request.output,'segment-picture-0-frame-plan.json');
  fs.writeFileSync(file,JSON.stringify(plan));
  const pin={path:file,sha256:retainedFrameHash(file,1024*1024)};
  f.request.sectionFrameReuse={'segment-picture-0':pin};f.request.pins[file]=pin.sha256;
}
