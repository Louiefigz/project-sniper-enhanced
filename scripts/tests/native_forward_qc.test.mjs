/** Synthetic SDK tests for retained-forward authority; no browser or media process is launched. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {batchFixture} from './native_short_batched_render_fixture.mjs';
import {runNativeBatchedRender} from '../producer/studio/native_short_batched_render.mjs';
import {runNativeShortCapture,nativeCaptureQcPoints} from '../producer/studio/native_short_capture.mjs';
import {nativeCaptureHash} from '../producer/studio/native_short_capture_context.mjs';
import {writeNativePictureReceipt} from '../producer/studio/native_forward_qc.mjs';

async function withPicture(action) {
  const f=batchFixture(100);
  try {
    const picture=await runNativeBatchedRender(f.request,{sdk:f.sdk,encode:f.encode});
    assert.equal(picture.status,'picture-encoded-awaiting-parent-qc',picture.error);
    await action(f,picture);
  }finally{f.cleanup();}
}

function rewrite(f, picture) {
  fs.writeFileSync(path.join(f.request.output,'batched-picture.json'),JSON.stringify(picture));
}

test('actual picture checks supply every forward baseline; fresh seeded sessions replay every reverse occurrence',()=>withPicture(async(f,picture)=>{
  const points=nativeCaptureQcPoints(f.plan,true),count=points.indexOf(99)+1;
  assert.deepEqual(picture.forwardQc.points,points.slice(0,count));
  assert.ok(picture.frames.filter(row=>row.forwardQc).every(row=>row.forwardQc.typography.status==='passed'));
  const originalCalls=f.calls.frames.length;
  const result=await runNativeShortCapture(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(result.status,'native-references-and-seek-states-pass',result.error);
  assert.deepEqual(result.frames.map(row=>row.frame),points);
  assert.equal(result.forwardReuse.frameCount,count);
  assert.ok(result.frames.slice(0,count).every(row=>!row.repeat&&row.origin==='retained-picture-forward-check'));
  assert.ok(result.frames.slice(count).every(row=>row.repeat&&row.byteIdentical));
  const expected=result.sessions.flatMap(row=>[99,...row.frames]);
  assert.deepEqual(f.calls.frames.slice(originalCalls),expected);
  assert.ok(result.sessions.every(row=>row.reverseSeed.frame===99&&row.sessionClosed));
  assert.ok(result.sessions.every(row=>row.frames.length+1<=result.batchPlan.maximumFrames));
  assert.equal(new Set(result.sessions.map(row=>row.reverseSeed.path)).size,result.sessions.length);
  assert.ok(result.sessions.every(row=>nativeCaptureHash(row.reverseSeed.path)===row.reverseSeed.sha256));
  assert.ok(result.sessions.every(row=>row.frames.every(frame=>frame<=row.reverseSeed.frame)));
  assert.ok(fs.statSync(path.join(f.request.output,'batched-picture.json')).size<32*1024*1024);
}));

for(const [name,edit,message] of [
  ['unknown contract',p=>{p.forwardQc.schemaVersion=2;},/authority differs/],
  ['omitted forward point',p=>{p.forwardQc.points.pop();},/authority differs/],
  ['missing measured row',p=>{delete p.frames[0].forwardQc;},/not checked/],
  ['changed source payload',p=>{p.frames[0].payload[0].frameIndex=9;},/source frames differ/],
  ['incomplete disposal',p=>{p.batches[0].sessionClosed=false;},/AssertionError/],
  ['unexpected original bytes',p=>{p.batches[0].originalMedia.contract[0].receivedDataBytes=1;},/AssertionError/],
  ['changed checker identity',p=>{p.forwardQc.checksSha256='f'.repeat(64);},/authority differs/],
  ['changed encoder',p=>{p.encoder.crf=30;},/AssertionError/],
])test(`present ${name} fails closed without silently recapturing`,()=>withPicture(async(f,picture)=>{
  edit(picture);rewrite(f,picture);const sessions=f.calls.sessions.length;
  const result=await runNativeShortCapture(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(result.status,'failed');assert.match(result.error,message);
  assert.equal(f.calls.sessions.length,sessions);
}));

for(const [name,target] of [
  ['JPEG',f=>path.join(f.request.output,'batched-native-render/frames/frame_000000.jpg')],
  ['PNG',f=>path.join(f.entry,'frame_00001.png')],
  ['picture',f=>path.join(f.request.output,'picture.mp4')],
])test(`changed actual ${name} bytes reject the retained baseline`,()=>withPicture(async f=>{
  fs.appendFileSync(target(f),' changed');const sessions=f.calls.sessions.length;
  const result=await runNativeShortCapture(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(result.status,'failed');assert.equal(f.calls.sessions.length,sessions);
}));

test('only a genuinely absent new contract selects historical full replay',()=>withPicture(async(f,picture)=>{
  delete picture.forwardQc;rewrite(f,picture);const before=f.calls.frames.length;
  const result=await runNativeShortCapture(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(result.status,'native-references-and-seek-states-pass',result.error);
  assert.equal(result.forwardReuse,undefined);
  assert.deepEqual(f.calls.frames.slice(before),nativeCaptureQcPoints(f.plan,true));
}));

test('explicit donor reuse requires the exact pinned receipt and retains its source image paths',()=>withPicture(async f=>{
  const donor=f.request.output,output=path.join(f.root,'retry');fs.mkdirSync(output);
  fs.copyFileSync(path.join(donor,'picture.mp4'),path.join(output,'picture.mp4'));
  const receipt=path.join(donor,'batched-picture.json');
  const request={...f.request,output,pictureDonor:donor,pins:{[receipt]:nativeCaptureHash(receipt)}};
  const result=await runNativeShortCapture(request,{sdk:f.sdk,encode:f.encode});
  assert.equal(result.status,'native-references-and-seek-states-pass',result.error);
  assert.equal(result.forwardReuse.receipt,receipt);
  assert.ok(result.frames.filter(row=>!row.repeat).every(row=>row.sourcePath.startsWith(donor)));
}));

test('receipt size is bounded before publishing a new file',()=>{
  const f=batchFixture();try{
    const target=path.join(f.root,'oversized.json');
    assert.throws(()=>writeNativePictureReceipt(target,{text:'x'.repeat(32*1024*1024)}),/32 MiB/);
    assert.equal(fs.existsSync(target),false);
  }finally{f.cleanup();}
});

for(const kind of ['oversized','directory','symlink'])test(`a ${kind} receipt is rejected before reading picture evidence`,()=>withPicture(async f=>{
  const file=path.join(f.request.output,'batched-picture.json');
  if(kind==='oversized')fs.truncateSync(file,33*1024*1024);
  else {fs.unlinkSync(file);if(kind==='directory')fs.mkdirSync(file);else fs.symlinkSync(path.join(f.request.project,'index.html'),file);}
  const before=f.calls.sessions.length,result=await runNativeShortCapture(f.request,{sdk:f.sdk,encode:f.encode});
  assert.equal(result.status,'failed');assert.match(result.error,/bounded picture QC receipt/);
  assert.equal(f.calls.sessions.length,before);
}));

test('a one-frame bound validates new evidence but retains full replay without an extra seed',async()=>{
  const f=batchFixture(30);try{
    f.sdk.extractMediaMetadata=async()=>({width:20000,height:20000});
    const picture=await runNativeBatchedRender(f.request,{sdk:f.sdk,encode:f.encode});
    assert.equal(picture.status,'picture-encoded-awaiting-parent-qc',picture.error);
    assert.equal(picture.batchPlan.maximumFrames,1);
    const result=await runNativeShortCapture(f.request,{sdk:f.sdk,encode:f.encode});
    assert.equal(result.status,'native-references-and-seek-states-pass',result.error);
    assert.equal(result.forwardReuse,undefined);assert.match(result.forwardReuseUnavailable.reason,/Single-frame/);
    assert.ok(result.sessions.every(row=>row.frames.length===1&&!row.reverseSeed));
    assert.deepEqual(result.frames.map(row=>row.frame),nativeCaptureQcPoints(f.plan,true,1));
  }finally{f.cleanup();}
});
