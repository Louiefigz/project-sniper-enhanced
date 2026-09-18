/** Tiny local bytes and fake probes exercise hash/reaping scheduling, not media quality. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {test,mock} from 'node:test';
import {batchFixture} from './native_short_batched_render_fixture.mjs';
import {createNativeCaptureContext,prepareNativeCaptureContext,nativeCaptureSourceHash} from '../producer/studio/native_short_capture_context.mjs';
import {nativeSourceMetadata} from '../producer/studio/native_source_cache.mjs';

async function withFixture(run) {
  const f=batchFixture(10);
  try { await run(f,path.join(f.request.project,f.video.src)); }
  finally { mock.restoreAll();f.cleanup(); }
}

test('source checksum yields to the event loop and hashes every original byte',()=>withFixture(async(f,source)=>{
  const bytes=Buffer.alloc(3*1024*1024+17,71);fs.writeFileSync(source,bytes);
  let yielded=false;setImmediate(()=>{yielded=true;});
  const actual=await nativeCaptureSourceHash({},source);
  assert.ok(yielded,'Source hashing must let child-exit callbacks run');
  assert.equal(actual,createHash('sha256').update(bytes).digest('hex'));
}));

test('multiple views share one actual source hash and one SDK metadata result',()=>withFixture(async(f,source)=>{
  const compile=f.sdk.runCompileStage;
  f.sdk.runCompileStage=async options=>{
    const result=await compile(options);
    result.composition.videos=Array.from({length:5},(_,index)=>({...f.video,id:`view-${index}`}));return result;
  };
  let probes=0,reads=0;const probe=f.sdk.extractMediaMetadata,stream=fs.createReadStream;
  f.sdk.extractMediaMetadata=async file=>{probes++;return probe(file);};
  mock.method(fs,'createReadStream',function(file,options){
    if(file===source){reads++;assert.equal(options.highWaterMark,1024*1024);}
    return stream.call(this,file,options);
  });
  const context=await createNativeCaptureContext(f.request,path.join(f.request.output,'work'),f.sdk);
  await prepareNativeCaptureContext(context);
  assert.equal(probes,1);assert.equal(reads,1);assert.equal(context.cacheEntries.length,5);
  const expected=createHash('sha256').update(fs.readFileSync(source)).digest('hex');
  assert.ok(context.cacheEntries.every(row=>row.sourceSha256===expected));
  assert.equal(context.batchPlan.maximumFrames,8);assert.equal(f.calls.sessions.length,0);
}));

test('source mutation during async hashing rejects instead of publishing a memoized digest',()=>withFixture(async(f,source)=>{
  const context={},stream=fs.createReadStream;
  mock.method(fs,'createReadStream',function(file,options){
    const result=stream.call(this,file,options);
    result.once('data',()=>fs.appendFileSync(source,' mutation'));return result;
  });
  await assert.rejects(()=>nativeCaptureSourceHash(context,source),/changed during hashing/);
  assert.equal(context.sourceHashes.size,0);
}));

test('metadata and hash memoization reject replacement or subsequent mutation',()=>withFixture(async(f,source)=>{
  const context={sdk:f.sdk};
  await nativeSourceMetadata(context,source);await nativeCaptureSourceHash(context,source);
  fs.appendFileSync(source,' mutation');
  await assert.rejects(()=>nativeSourceMetadata(context,source),/changed after metadata/);
  await assert.rejects(()=>nativeCaptureSourceHash(context,source),/changed after metadata/);
  const hashContext={};await nativeCaptureSourceHash(hashContext,source);
  const replacement=source+'.replacement';fs.writeFileSync(replacement,fs.readFileSync(source));fs.renameSync(replacement,source);
  await assert.rejects(()=>nativeCaptureSourceHash(hashContext,source),/changed after hashing/);
}));

test('metadata probes reject source changes and a later preparation performs a fresh hash',()=>withFixture(async(f,source)=>{
  const changed={sdk:{extractMediaMetadata:async()=>{fs.appendFileSync(source,' changed');return {width:1,height:1};}}};
  await assert.rejects(()=>nativeSourceMetadata(changed,source),/changed during metadata/);
  assert.equal(changed.sourceMetadata.size,0);
  const first=await nativeCaptureSourceHash({},source);fs.appendFileSync(source,' newer');
  const second=await nativeCaptureSourceHash({},source);assert.notEqual(second,first);
}));
