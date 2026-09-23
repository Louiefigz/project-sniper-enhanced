/** Experimental route contract tests only; real capture/encode/QC remains separately supervised. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import {test} from 'node:test';
import {runNativeBatchedRender,nativeBatchEncoderArgs} from '../producer/studio/native_short_batched_render.mjs';
import {runNativeShortCapture,nativeCaptureQcPoints} from '../producer/studio/native_short_capture.mjs';
import {nativeCaptureBatches,nativeSourceCacheEntry,nativeCaptureBatchPlan} from '../producer/studio/native_short_capture_context.mjs';
import {capturePoints} from '../producer/studio/native_short_capture_checks.mjs';
import {batchFixture} from './native_short_batched_render_fixture.mjs';

async function withFixture(run,totalFrames=100) {
  const fixture=batchFixture(totalFrames);try{await run(fixture);}finally{fixture.cleanup();}
}

test('complete native picture captures every frame across48-frame sessions then encodes exactly once',()=>withFixture(async f=>{
  const receipt=await runNativeBatchedRender(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(receipt.status,'picture-encoded-awaiting-parent-qc',receipt.error);
  assert.deepEqual(receipt.batches.map(row=>[row.startFrame,row.endFrameExclusive]),[[0,48],[48,96],[96,100]]);
  assert.deepEqual(f.calls.frames,Array.from({length:100},(_,frame)=>frame));assert.equal(f.calls.encodes.length,1);
  assert.equal(f.calls.compiles.length,1);assert.equal(f.calls.sessions.length,3);
  assert.deepEqual(f.calls.cacheEntries,[[f.entry],[f.entry],[f.entry]]);
  assert.equal(f.calls.sessionCloses,3);assert.equal(f.calls.poolDrains,3);assert.equal(f.calls.serverCloses,3);
  assert.ok(receipt.frames.every(row=>/^[a-f0-9]{64}$/.test(row.sha256)&&row.payload.length===1));
  for(const session of f.calls.sessions){assert.equal(session.options.quality,95);assert.equal(session.options.format,'jpeg');
    assert.equal(session.options.videoMetadataHints[0].width,3840);assert.equal(session.options.videoMetadataHints[0].height,2160);}
  assert.equal(f.calls.config.enableBrowserPool,false);assert.equal(f.calls.config.staticFrameDedup,false);
  assert.ok(f.calls.injectors.every(row=>row.strictFrameDecode===true));
  assert.equal(receipt.encoder.crf,15);assert.equal(receipt.encoder.preset,'slow');assert.equal(receipt.encodedPictureQc,'not-performed-here');
}));

test('cache miss fails before browser or encode and never selects a nearby cache entry',()=>withFixture(async f=>{
  fs.rmSync(path.join(f.entry,'.hf-complete'));
  const receipt=await runNativeBatchedRender(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(receipt.status,'failed');assert.match(receipt.error,/Exact native source frame cache missing/);
  assert.equal(f.calls.sessions.length,0);assert.equal(f.calls.encodes.length,0);assert.equal(fs.existsSync(path.join(f.request.output,'picture.mp4')),false);
}));

test('failure midway through a new session retains partial inventory and disposes without encoding',()=>withFixture(async f=>{
  f.failFrame=49;const receipt=await runNativeBatchedRender(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(receipt.status,'failed');assert.match(receipt.error,/decode failure at frame49|decode failure at frame 49/);
  assert.equal(receipt.frames.length,49);assert.equal(f.calls.sessions.length,2);assert.equal(f.calls.encodes.length,0);
  assert.equal(f.calls.sessionCloses,2);assert.equal(f.calls.poolDrains,2);assert.equal(f.calls.serverCloses,2);
}));

test('experimental entry requires opt-in and preserves any existing picture',()=>withFixture(async f=>{
  delete f.request.captureMode;
  const receipt=await runNativeBatchedRender(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(receipt.status,'failed');assert.match(receipt.error,/explicit opt-in/);assert.equal(f.calls.sessions.length,0);
  fs.rmSync(path.join(f.request.output,'batched-picture.json'));f.request.captureMode='cached-native-batches';
  fs.writeFileSync(path.join(f.request.output,'picture.mp4'),'TEST preexisting');
  const second=await runNativeBatchedRender(f.request,{sdk:f.sdk,encode:f.encode});assert.equal(second.status,'failed');
  assert.equal(fs.readFileSync(path.join(f.request.output,'picture.mp4'),'utf8'),'TEST preexisting');
}));

test('QC default uses its original points/session while opt-in keeps all repeats and fresh render boundaries',async()=>{
  await withFixture(async f=>{
    delete f.request.captureMode;const receipt=await runNativeShortCapture(f.request,{sdk:f.sdk,encode:f.encode});
    assert.equal(receipt.status,'native-references-and-seek-states-pass',receipt.error);
    assert.deepEqual(f.calls.frames,capturePoints(f.plan));assert.equal(f.calls.sessions.length,1);
  });
  await withFixture(async f=>{
    f.plan.canvas.occurrences=Array.from({length:50},(_,frame)=>[frame,0,frame,frame*2,frame*2+1,'TEST',0]);
    fs.writeFileSync(path.join(f.request.project,'SHORT-PROJECT.json'),JSON.stringify(f.plan));
    const receipt=await runNativeShortCapture(f.request,{sdk:f.sdk,encode:f.encode});
    assert.equal(receipt.status,'native-references-and-seek-states-pass',receipt.error);
    assert.deepEqual(f.calls.frames,nativeCaptureQcPoints(f.plan,true));assert.ok(f.calls.sessions.length>1);
    for(const frame of [47,48,95,96])assert.ok(receipt.frames.filter(row=>row.frame===frame).length>=2);
    assert.ok(receipt.sessions.every(row=>row.frames.length<=48&&row.sessionClosed&&row.browserPoolDrained&&row.serverClosed));
  });
});

test('batch partition and missing source frame checks preserve exact indices',()=>withFixture(async f=>{
  const sequence=[0,47,48,99,48,47,0];assert.deepEqual(nativeCaptureBatches(sequence,3).flat(),sequence);
  assert.throws(()=>nativeCaptureBatches(sequence,49),/session bound/);
  fs.rmSync(path.join(f.entry,'frame_00002.png'));
  assert.throws(()=>nativeSourceCacheEntry({project:f.request.project,request:f.request,fps:{num:25,den:1},rate:25},f.video),/Incomplete native source cache/);
}));

test('original source dimensions select conservative batch bounds without changing pixels',()=>{
  const entries=count=>Array.from({length:count},(_,index)=>({video:{id:`source-${index}`},width:3840,height:2160}));
  assert.equal(nativeCaptureBatchPlan(entries(1)).maximumFrames,48);
  assert.equal(nativeCaptureBatchPlan(entries(2)).maximumFrames,24);
  assert.equal(nativeCaptureBatchPlan(entries(4)).maximumFrames,12);
  const project=nativeCaptureBatchPlan([...entries(4),{video:{id:'page'},width:1080,height:1920}]);
  assert.equal(project.maximumFrames,8);assert.equal(project.sources.length,5);
  assert.equal(project.decodedBytesPerFrame,4*3840*2160*4+1080*1920*4);
  assert.ok(project.sources.every(row=>row.width===3840||row.width===1080));
  assert.match(project.scope,/not observed memory/);
  assert.throws(()=>nativeCaptureBatchPlan([{video:{id:'bad'},width:NaN,height:2160}]),/original integer/);
  assert.deepEqual(nativeCaptureBatchPlan(entries(1),1),nativeCaptureBatchPlan(entries(1)));
  assert.throws(()=>nativeCaptureBatchPlan([]),/compiled zero-video evidence/);
  assert.throws(()=>nativeCaptureBatchPlan([],1),/compiled zero-video evidence/);
  assert.throws(()=>nativeCaptureBatchPlan(entries(1),0),/compiled video count/);
  assert.throws(()=>nativeCaptureBatchPlan([{video:{id:'missing'}}],1),/original integer/);
  const graphics=nativeCaptureBatchPlan([],0);
  assert.equal(graphics.maximumFrames,48);assert.equal(graphics.decodedBytesPerFrame,0);
  assert.deepEqual(graphics.sources,[]);assert.equal(graphics.singleFrameExceedsPlanningBudget,false);
  assert.match(graphics.scope,/zero-video source workload only/);assert.match(graphics.scope,/graphics, images and browser memory/);
});

/** A compiled graphics stage still carries original dialogue; no source PNGs or decoder are needed. */
function graphicsOnly(f,dialogue=true) {
  f.plan.canvas.pictureViews=[];
  fs.writeFileSync(path.join(f.request.project,'SHORT-PROJECT.json'),JSON.stringify(f.plan));
  const compile=f.sdk.runCompileStage,session=f.sdk.createCaptureSession;
  f.sdk.runCompileStage=async options=>{
    const result=await compile(options);result.composition.videos=[];
    result.composition.audios=dialogue?[{id:'dialogue-0',src:f.video.src,start:0,end:f.video.end}]:[];return result;
  };
  f.sdk.extractMediaMetadata=async()=>{throw new Error('Graphics-only capture must not probe source-video dimensions');};
  f.sdk.createFrameLookupTable=(videos,extracted)=>{
    assert.deepEqual(videos,[]);assert.deepEqual(extracted,[]);return {getActiveFramePayloads:()=>new Map()};
  };
  f.sdk.createCaptureSession=async(...args)=>{
    const current=await session(...args),evaluate=current.page.evaluate;
    current.page.evaluate=async fn=>String(fn).includes('document.fonts')
      ?{fonts:[{family:'Inter',status:'loaded'}],images:[],texts:[]}:evaluate(fn);return current;
  };
}

test('graphics-only picture keeps exact48-frame sessions and dialogue guard without decoded video payloads',()=>withFixture(async f=>{
  graphicsOnly(f);
  f.sdk.initializeSession=async()=>{
    const transport=f.calls.transports.at(-1);assert.equal(transport.roots,null);
    assert.throws(()=>f.calls.injectors.at(-1).frameSrcResolver(path.join(f.entry,'frame_00001.png')),/Unconfigured or invalid/);
    const response=transport.handle(new Request('http://localhost:39999/__sniper_native_frame/'+'a'.repeat(64)));
    assert.equal(response.status,404);assert.equal(transport.stats().registrations,0);
  };
  const receipt=await runNativeBatchedRender(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(receipt.status,'picture-encoded-awaiting-parent-qc',receipt.error);
  assert.equal(receipt.batchPlan.maximumFrames,48);assert.equal(receipt.batchPlan.decodedBytesPerFrame,0);
  assert.deepEqual(receipt.batches.map(row=>[row.startFrame,row.endFrameExclusive]),[[0,48],[48,96],[96,100]]);
  assert.deepEqual(f.calls.frames,Array.from({length:100},(_,frame)=>frame));assert.equal(f.calls.encodes.length,1);
  assert.ok(receipt.frames.every(row=>row.payload.length===0&&row.observed.images.length===0));
  assert.equal(f.calls.cacheEntries.length,0);assert.equal(receipt.audio,'parent-dialogue-delivery');
  assert.ok(f.calls.transports.every(transport=>transport.roots===null&&transport.closed));
  for(const batch of receipt.batches){
    assert.ok(batch.sessionClosed&&batch.browserPoolDrained&&batch.serverClosed&&batch.mediaGuardDisposed);
    assert.equal(batch.originalMedia.disposed,true);assert.equal(batch.originalMedia.status,'original-payloads-suppressed');
    assert.deepEqual(batch.originalMedia.contract.map(row=>({videoIds:row.videoIds,audioIds:row.audioIds})),[{videoIds:[],audioIds:['dialogue-0']}]);
  }
  for(const session of f.calls.sessions){assert.deepEqual(session.options.skipReadinessVideoIds,[]);assert.deepEqual(session.options.videoMetadataHints,[]);}
}));

test('fixture transport enforces the actual single nonempty root configuration contract',()=>withFixture(async f=>{
  const server=await f.sdk.createFileServer2();
  try {
    assert.throws(()=>server.frameTransport.configure([]),/one explicit nonempty root configuration/);
    server.frameTransport.configure([f.entry]);
    assert.throws(()=>server.frameTransport.configure([f.entry]),/one explicit nonempty root configuration/);
  }finally {await server.close();}
}));

test('graphics-only reverse QC keeps repeated indices and disposes each bounded session',()=>withFixture(async f=>{
  graphicsOnly(f);const receipt=await runNativeShortCapture(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(receipt.status,'native-references-and-seek-states-pass',receipt.error);
  assert.deepEqual(f.calls.frames,nativeCaptureQcPoints(f.plan,true,48));
  for(const frame of [47,48,95,96])assert.ok(receipt.frames.filter(row=>row.frame===frame).length>=2);
  assert.ok(receipt.frames.every(row=>row.payload.length===0));
  assert.equal(f.calls.cacheEntries.length,0);assert.ok(f.calls.transports.every(transport=>transport.roots===null&&transport.closed));
  assert.ok(receipt.sessions.every(row=>row.frames.length<=48&&row.sessionClosed&&row.mediaGuardDisposed&&row.browserPoolDrained&&row.serverClosed));
}));

test('graphics-only capture failure preserves partial inventory and closes its original-dialogue guard',()=>withFixture(async f=>{
  graphicsOnly(f);f.failFrame=49;const receipt=await runNativeBatchedRender(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(receipt.status,'failed');assert.match(receipt.error,/decode failure at frame 49/);
  assert.equal(receipt.frames.length,49);assert.equal(f.calls.encodes.length,0);assert.equal(f.calls.sessionCloses,2);
  assert.equal(f.calls.poolDrains,2);assert.equal(f.calls.serverCloses,2);
  assert.ok(receipt.batches.every(row=>row.originalMedia.disposed&&row.mediaGuardDisposed));
}));

test('zero-video admission does not bypass the existing original-audio contract',()=>withFixture(async f=>{
  graphicsOnly(f,false);const receipt=await runNativeBatchedRender(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(receipt.status,'failed');assert.match(receipt.error,/Native original media contract is empty/);
  assert.equal(f.calls.frames.length,0);assert.equal(f.calls.encodes.length,0);
  assert.equal(f.calls.sessionCloses,1);assert.equal(f.calls.poolDrains,1);assert.equal(f.calls.serverCloses,1);
}));

/** The fake SDK exposes five source elements; payload bytes remain synthetic and unreviewed. */
function multipleSourceViews(f) {
  const compile=f.sdk.runCompileStage;
  f.sdk.runCompileStage=async options=>{
    const result=await compile(options);
    result.composition.videos=Array.from({length:5},(_,index)=>({...f.video,id:index===0?f.video.id:`view-${index}`}));
    return result;
  };
}

test('picture and reverse QC share the smaller bound and preserve both sides of actual session boundaries',async()=>{
  await withFixture(async f=>{
    multipleSourceViews(f);const receipt=await runNativeBatchedRender(f.request,{sdk:f.sdk,encode:f.encode});
    assert.equal(receipt.status,'picture-encoded-awaiting-parent-qc',receipt.error);assert.equal(receipt.batchPlan.maximumFrames,8);
    assert.ok(receipt.batches.every(row=>row.frames.length<=8));assert.equal(receipt.batches.length,13);
    assert.deepEqual(receipt.frames.map(row=>row.frame),Array.from({length:100},(_,index)=>index));
    assert.equal(f.calls.encodes.length,1);assert.equal(f.calls.sessions[0].options.videoMetadataHints[0].width,3840);
  });
  await withFixture(async f=>{
    multipleSourceViews(f);const receipt=await runNativeShortCapture(f.request,{sdk:f.sdk,encode:f.encode});
    assert.equal(receipt.status,'native-references-and-seek-states-pass',receipt.error);assert.equal(receipt.batchPlan.maximumFrames,8);
    assert.ok(receipt.sessions.every(row=>row.frames.length<=8&&row.sessionClosed&&row.serverClosed&&row.browserPoolDrained));
    for(const frame of [7,8,15,16,95,96])assert.ok(receipt.frames.filter(row=>row.frame===frame).length>=2);
    assert.deepEqual(f.calls.frames,nativeCaptureQcPoints(f.plan,true,8));
  });
});

function sdkEncoder() {
  const file=path.resolve('templates/motion/node_modules/hyperframes/dist/cli.js'),source=fs.readFileSync(file,'utf8');
  const names=['fpsToFfmpegArg','requiresEvenDimensions','withEvenDimensionPad','isMovFamilyContainer','renderProvenanceArgs','appendRenderProvenanceArgs','getEncoderPreset','buildEncoderArgs'];
  const bodies=names.map(name=>{
    const start=source.indexOf(`function ${name}(`);assert.ok(start>=0,`SDK dependency missing: ${name}`);
    const tail=source.slice(start),end=/\n(?:async )?function |\nvar /.exec(tail);
    assert.ok(end,`SDK dependency boundary missing: ${name}`);return tail.slice(0,end.index);
  });
  const presets=/ENCODER_PRESETS = (\{[\s\S]*?\n    \});/.exec(source);assert.ok(presets);
  const context={PROVENANCE_RENDERER_TAG:'hyperframes_renderer',PROVENANCE_RENDERER_NAME:'hyperframes',
    PROVENANCE_VERSION_TAG:'hyperframes_version',PROVENANCE_VERSION:'TEST version',EVEN_DIMENSION_PAD:'pad=ceil(iw/2)*2:ceil(ih/2)*2'};
  vm.runInNewContext(`var ENCODER_PRESETS=${presets[1]};${bodies.join('\n')};this.build=buildEncoderArgs;this.preset=getEncoderPreset;`,context,{timeout:1000});
  return context;
}

test('software picture arguments match actual installed SDK high/crf15; only explicit inventory/no-overwrite guards differ',()=>{
  const sdk=sdkEncoder();
  for(const fps of [{num:25,den:1},{num:30000,den:1001}]){
    const options={fps,framesDir:'/TEST frames',output:'/TEST output.mp4',totalFrames:272,version:'TEST version'};
    const args=nativeBatchEncoderArgs(options),rate=fps.den===1?String(fps.num):`${fps.num}/${fps.den}`;
    assert.equal(args[args.indexOf('-start_number')+1],'0');assert.equal(args[args.indexOf('-frames:v')+1],'272');assert.ok(args.includes('-n'));
    const comparable=[...args];for(const flag of ['-start_number','-frames:v'])comparable.splice(comparable.indexOf(flag),2);
    comparable[comparable.indexOf('-n')]='-y';
    const expected=sdk.build({...sdk.preset('high','mp4'),fps,width:1080,height:1920,useGpu:false},
      ['-framerate',rate,'-i',path.join(options.framesDir,'frame_%06d.jpg')],options.output,null);
    assert.deepEqual(comparable,Array.from(expected));
  }
});
