/** Exercise qualified SDK command construction with fake probes/output, without media processes. */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {test} from 'node:test';
import {NATIVE_SOURCE_FRAME_CLOCK,nativeSourceFrameCount} from '../producer/studio/runtime/frame-source-transport.mjs';
import {nativeSourceCacheEntry,nativeSourceCacheIdentity} from '../producer/studio/native_source_cache.mjs';
import {batchFixture} from './native_short_batched_render_fixture.mjs';

function adaptedSdk() {
  const manifest=JSON.parse(fs.readFileSync('scripts/producer/studio/runtime/patches.json'));
  const row=manifest.files.find(item=>item.file==='cli.js');
  let bytes=fs.readFileSync('templates/motion/node_modules/hyperframes/dist/cli.js');
  const hash=value=>createHash('sha256').update(value).digest('hex');
  assert.equal(hash(bytes),row.baseSha256);
  for(const patch of [...row.patches].reverse()){
    bytes=Buffer.concat([bytes.subarray(0,patch.offset),Buffer.from(patch.text),bytes.subarray(patch.offset+patch.remove)]);
  }
  assert.equal(hash(bytes),row.sha256);
  assert.equal(hash(fs.readFileSync('scripts/producer/studio/runtime/frame-source-transport.mjs')),manifest.transportSha256);
  return bytes.toString();
}

const SDK=adaptedSdk();

test('SDK source work is bounded while complete metadata still precedes color negotiation',async()=>{
  const start=SDK.indexOf('async function nativeSourceTaskMap('),end=SDK.indexOf('async function extractAllVideoFrames(',start);
  assert.ok(start>0&&end>start);
  const sandbox={};vm.runInNewContext(SDK.slice(start,end)+';this.map=nativeSourceTaskMap;',sandbox,{timeout:1000});
  let active=0,maximum=0;
  const results=await sandbox.map(Array.from({length:256},(_,index)=>index),async(value,index)=>{
    active++;maximum=Math.max(maximum,active);await Promise.resolve();active--;return value+index;
  });
  assert.equal(maximum,1);assert.deepEqual(Array.from(results),Array.from({length:256},(_,i)=>i*2));
  const seen=[];
  await assert.rejects(sandbox.map([0,1,2],async value=>{
    seen.push(value);if(value===1)throw new Error('TEST probe failed');return value;
  }),/probe failed/);
  assert.deepEqual(seen,[0,1]);
  const extraction=SDK.slice(end,SDK.indexOf('\nfunction getFrameIndexAtTime(',end));
  assert.equal((extraction.match(/await nativeSourceTaskMap\(/g)??[]).length,3);
  assert.ok(extraction.indexOf('const metadataResults = await nativeSourceTaskMap(')<extraction.indexOf('const hdrInfo = analyzeCompositionHdr('));
  assert.match(extraction,/nativeSourceTaskMap\(\s+supersetPlan.direct,/);
  assert.match(extraction,/nativeSourceTaskMap\(\s+supersetPlan.groups,/);
});

test('native source windows have exclusive ends in forward, fresh and reverse seeks',()=>{
  const start=SDK.indexOf('FrameLookupTable = class'),end=SDK.indexOf('\n    };',start)+7;
  assert.ok(start>0&&end>start);
  const sandbox={normalizePlaybackRate:value=>value,getFrameIndexAtTime:()=>0};
  vm.runInNewContext('var '+SDK.slice(start,end)+';this.Table=FrameLookupTable;',sandbox,{timeout:1000});
  for(const cut of [2,1001/30000*57,30,50.8,91,123]){
    const table=new sandbox.Table();
    for(const [id,left,right] of [['outgoing',0,cut],['incoming',cut,cut+2]]){
      table.addVideo({videoId:id,framePaths:new Map([[0,id+'.png']])},left,right,0);
    }
    for(const time of [cut,cut+.1,cut-.001,cut,0,cut+2,cut]){
      const expected=time<cut?['outgoing']:time<cut+2?['incoming']:[];
      assert.deepEqual([...table.getActiveFramePayloads(time).keys()],expected);
    }
    assert.equal(table.getFrame('outgoing',cut),null);
    assert.equal(table.getFrame('incoming',cut),'incoming.png');
  }
});

function sdkFunction(name, next) {
  const start=SDK.indexOf(`function ${name}(`),end=SDK.indexOf(`\nfunction ${next}(`,start);
  assert.ok(start>0&&end>start);
  return SDK.slice(start,end);
}

class ExtractionError extends Error {
  constructor(kind,retryable,message,diagnostic){super(message);Object.assign(this,{kind,retryable,diagnostic});}
}

function extractionFixture(settings={}) {
  const calls=[],metadata={durationSeconds:60,videoCodec:'h264',isVFR:false,...settings.metadata};
  const sandbox={nativeSourceFrameCount,DEFAULT_CONFIG2:{ffmpegProcessTimeout:1234},
    toFps:value=>typeof value==='number'?{num:value,den:1}:value,
    fpsToNumber:value=>value.num/value.den,fpsToFfmpegArg:value=>`${value.num}/${value.den}`,
    join13:path.join,existsSync14:()=>true,mkdirSync7:()=>{},extractMediaMetadata:async()=>metadata,
    resolvePlayableVideoDuration:value=>value.durationSeconds,resolveFrameFormat:()=>settings.format??'png',
    FRAME_FILENAME_PREFIX:'frame_',isHdrColorSpace:()=>!!settings.hdr,process:{platform:settings.platform??'linux'},
    codecMayHaveAlpha:()=>false,SDR_TO_HDR_COLORSPACE_FILTER:'qualified-existing-color-filter',
    VideoSourceExtractionError:ExtractionError,
    runFfmpeg:async(args,options)=>{calls.push({args,options});return {success:true};},
    framePathsFromDirectory:()=>{
      const args=calls.at(-1).args,count=settings.actualFrames??Number(args[args.indexOf('-frames:v')+1]);
      return new Map(Array.from({length:count},(_,index)=>[index,`frame_${index+1}.png`]));
    }};
  const source='async '+sdkFunction('extractVideoFramesRange','classifyFfmpegSpawnError');
  vm.runInNewContext(source+';this.extract=extractVideoFramesRange;',sandbox,{timeout:1000});
  return {calls,run:(span,options={})=>sandbox.extract('source.mp4','video',span.start,span.duration,
    {outputDir:'/test',fps:25,...options},undefined,{ffmpegProcessTimeout:5678})};
}

function argument(call, flag) {
  const index=call.args.indexOf(flag);return index<0?undefined:call.args[index+1];
}

test('exact frame clock admits rational, tiny and fractional spans without float boundary frames',()=>{
  for(const [duration,fps,count] of [[2.2800000000000002,25,57],[10.560000000000002,25,264],
    [10.800000000000004,25,270],[.04,25,1],[.041,25,2],[1e-12,25,1],
    [1001/30000*57,30000/1001,57],[1,30000/1001,30]]){
    assert.equal(nativeSourceFrameCount(duration,fps),count);
  }
  for(const [duration,fps] of [[0,25],[-1,25],[NaN,25],[Infinity,25],[1,0],[1,NaN],[1,Infinity],[1e20,25]]){
    assert.throws(()=>nativeSourceFrameCount(duration,fps),/finite positive frame clock/);
  }
});

test('fractional seek regressions request exactly the bounded count on the zero-based CFR grid',async()=>{
  for(const [start,duration,count] of [[7.043333333333,2.2800000000000002,57],
    [1.671666666667,10.560000000000002,264],[1.275,10.800000000000004,270]]){
    const fixture=extractionFixture(),result=await fixture.run({start,duration}),call=fixture.calls[0];
    assert.equal(argument(call,'-ss'),String(start));assert.equal(argument(call,'-frames:v'),String(count));
    assert.equal(argument(call,'-vf'),'fps=25/1:start_time=0');assert.equal(argument(call,'-t'),undefined);
    assert.equal(argument(call,'-compression_level'),'1');assert.equal(result.totalFrames,count);
    assert.equal(call.options.timeout,5678);
  }
});

test('rational rates and subframe spans retain their exact output clock',async()=>{
  const rational=extractionFixture();await rational.run({start:1.2,duration:1001/30000*57},{fps:{num:30000,den:1001}});
  assert.equal(argument(rational.calls[0],'-vf'),'fps=30000/1001:start_time=0');
  assert.equal(argument(rational.calls[0],'-frames:v'),'57');
  const tiny=extractionFixture();await tiny.run({start:1.2,duration:.001});
  assert.equal(argument(tiny.calls[0],'-frames:v'),'1');
});

test('genuinely short decoded output fails before cache publication and cannot turn into a hold',async()=>{
  for(const count of [0,56,58]){
    const fixture=extractionFixture({actualFrames:count});
    await assert.rejects(()=>fixture.run({start:7.043333333333,duration:2.28}),error=>
      error.kind===(count===0?'zero_output':'incomplete_output')&&!error.retryable&&error.diagnostic.includes(`decoded ${count}`));
  }
  const eof=extractionFixture({metadata:{durationSeconds:1}});
  await assert.rejects(()=>eof.run({start:1,duration:.04}),error=>error.kind==='media_start_out_of_range');
  assert.equal(eof.calls.length,0);
});

test('invalid start/count cannot launch FFmpeg, and its final-frame-only route stays intact',async()=>{
  for(const span of [{start:NaN,duration:1},{start:-1,duration:1},{start:0,duration:Infinity}]){
    const fixture=extractionFixture();await assert.rejects(()=>fixture.run(span));assert.equal(fixture.calls.length,0);
  }
  const final=extractionFixture();await final.run({start:59.98,duration:.02},{finalFrameOnly:true});
  assert.equal(argument(final.calls[0],'-frames:v'),'1');assert.equal(argument(final.calls[0],'-vf'),undefined);
  assert.ok(final.calls[0].args.indexOf('-i')<final.calls[0].args.indexOf('-ss'));
});

test('VFR conversion and HDR color filters keep existing policy with an explicit frame bound',async()=>{
  const vfr=extractionFixture({metadata:{isVFR:true}});await vfr.run({start:1.2,duration:1.01});
  assert.equal(argument(vfr.calls[0],'-fps_mode'),'cfr');assert.equal(argument(vfr.calls[0],'-r'),'25/1');
  assert.equal(argument(vfr.calls[0],'-vf'),undefined);assert.equal(argument(vfr.calls[0],'-frames:v'),'26');
  const hdr=extractionFixture({hdr:true,platform:'darwin'});
  await hdr.run({start:1.2,duration:1},{sdrToHdrTransfer:'smpte2084'});
  assert.equal(argument(hdr.calls[0],'-vf'),'format=nv12,fps=25/1:start_time=0,qualified-existing-color-filter');
  assert.equal(argument(hdr.calls[0],'-hwaccel'),'videotoolbox');
});

test('new clock identity cannot admit an old complete cache under an explicitly reused root',()=>{
  const fixture=batchFixture(10);
  try{
    const context={project:fixture.request.project,request:fixture.request,fps:{num:25,den:1},rate:25};
    const current=nativeSourceCacheIdentity(context,fixture.video),oldBlob={...current.keyBlob};delete oldBlob.t;
    const key=createHash('sha256').update(JSON.stringify(oldBlob)).digest('hex');
    const oldEntry=path.join(fixture.request.cache,'hfcache-v4-'+key.slice(0,16));
    fs.renameSync(current.entry,oldEntry);
    assert.equal(current.keyBlob.t,NATIVE_SOURCE_FRAME_CLOCK);assert.notEqual(current.entry,oldEntry);
    assert.throws(()=>nativeSourceCacheEntry(context,fixture.video),/Exact native source frame cache missing/);
    assert.ok(fs.existsSync(path.join(oldEntry,'.hf-complete')));
  }finally{fixture.cleanup();}
});

test('SDK superset slices retain fractional terminal samples and reject unavailable or missing frames',()=>{
  const copied=[],sandbox={nativeSourceFrameCount,fpsToNumber:value=>value.num/value.den,
    rmSync4:()=>{},mkdirSync7:()=>{},VideoSourceExtractionError:ExtractionError,join13:path.join,
    frameFileName:index=>`frame_${index}.png`,linkOrCopyFrame:(source,destination)=>copied.push({source,destination}),
    extractedFramesFromDirectory:()=>({totalFrames:copied.length})};
  vm.runInNewContext(sdkFunction('sliceSupersetMember','resolveProjectRelativeSrc')+
    ';this.slice=sliceSupersetMember;',sandbox,{timeout:1000});
  const member={offsetFrames:1,miss:{work:{videoDuration:.040000005,metadata:{isVFR:false},format:'png',videoPath:'source'}}};
  const superset={totalFrames:3,framePaths:new Map([[0,'zero'],[1,'one'],[2,'two']])};
  const result=sandbox.slice(member,superset,'/test',25,{num:25,den:1});
  assert.equal(result.totalFrames,2);assert.deepEqual(copied.map(row=>row.source),['one','two']);
  copied.length=0;
  assert.throws(()=>sandbox.slice(member,{...superset,totalFrames:2},'/test',25,{num:25,den:1}),
    error=>error.kind==='incomplete_output');
  assert.equal(copied.length,0);
  assert.throws(()=>sandbox.slice(member,{...superset,framePaths:new Map([[1,'one']])},'/test',25,{num:25,den:1}),
    /superset frame 2 missing/);
  assert.match(SDK,/const transformParts = \[\n\s+NATIVE_SOURCE_FRAME_CLOCK,/);
});
