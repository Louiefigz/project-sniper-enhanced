/** Fake requests and CDP events verify suppression scope; pixels/memory require the owned live experiment. */
import path from 'node:path';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {test} from 'node:test';
import {batchFixture} from './native_short_batched_render_fixture.mjs';
import {createNativeCaptureContext,prepareNativeCaptureContext} from '../producer/studio/native_short_capture_context.mjs';
import {nativeOriginalMediaContract,nativeOriginalMediaGuard} from '../producer/studio/native_original_media.mjs';
import {runNativeBatchedRender} from '../producer/studio/native_short_batched_render.mjs';

function fakePage() {
  const page=new EventEmitter(),client=new EventEmitter(),events=[];client.detached=false;
  client.send=async command=>events.push(command);client.detach=async()=>{client.detached=true;events.push('detach');};
  page.createCDPSession=async()=>client;page.setRequestInterception=async enabled=>events.push(['interception',enabled]);
  return {page,client,events};
}

function request(url,type='media') {
  const calls=[];return {calls,url:()=>url,resourceType:()=>type,method:()=> 'GET',isInterceptResolutionHandled:()=>false,
    abort:async reason=>calls.push(['abort',reason]),continue:async()=>calls.push(['continue'])};
}

async function withFixture(run) {
  const f=batchFixture(10),wire=fakePage(),receipt={};let guard;
  try {
    const context=await createNativeCaptureContext(f.request,path.join(f.request.output,'work'),f.sdk);
    await prepareNativeCaptureContext(context);
    context.result.composition.audios=[{...f.video,id:'dialogue'}];
    guard=nativeOriginalMediaGuard(context,'http://localhost:4020',receipt);await guard.attach(wire.page);
    await run({...f,...wire,context,guard,receipt,url:receipt.contract[0].url});
  }finally{
    if(guard&&!receipt.disposed)await guard.dispose().catch(()=>{});
    f.cleanup();
  }
}

test('exact URL contract combines admitted video and parent-delivered audio without modifying source timing',()=>withFixture(async f=>{
  assert.equal(f.url,'http://localhost:4020/assets/source.mp4');
  assert.deepEqual(f.receipt.contract[0].videoIds,[f.video.id]);assert.deepEqual(f.receipt.contract[0].audioIds,['dialogue']);
  assert.equal(f.receipt.contract[0].sourceBytes,17);assert.equal(f.video.mediaStart,0);
  assert.deepEqual(f.events,['Network.enable',['interception',true]]);
  assert.equal(f.receipt.sourceDelivery,'Admitted PNG transport supplies video; parent FFmpeg supplies audio');
}));

test('only exact originals are suppressed; PNG transport, fonts, scripts and other image URLs continue',()=>withFixture(async f=>{
  const inputs=[request(f.url),request(f.url,'fetch'),request('http://localhost:4020/__sniper_native_frame/abc','image'),
    request('http://localhost:4020/assets/Inter.ttf','font'),request('http://localhost:4020/runtime.js','script'),
    request('http://localhost:4020/unrelated.mp4','image')];
  for(const item of inputs)f.page.emit('request',item);
  await f.guard.assertHealthy();
  assert.ok(inputs.slice(0,2).every(item=>item.calls[0][0]==='abort'));
  assert.ok(inputs.slice(2).every(item=>item.calls[0][0]==='continue'));
  assert.equal(f.receipt.contract[0].suppressedRequests,2);
  assert.equal(f.receipt.contract[0].receivedDataBytes,0);
}));

test('an unplanned media URL fails closed and remains visible in the receipt',()=>withFixture(async f=>{
  const unexpected=request(f.url+'?unplanned=1');f.page.emit('request',unexpected);
  await assert.rejects(()=>f.guard.assertHealthy(),/Unexpected native browser media URL/);
  assert.deepEqual(unexpected.calls,[['abort','blockedbyclient']]);
  assert.deepEqual(f.receipt.unexpectedMedia,[{url:f.url+'?unplanned=1',method:'GET'}]);
  await assert.rejects(()=>f.guard.dispose(),/Unexpected native browser media URL/);assert.equal(f.receipt.disposed,true);
}));

test('actual original payload byte delivery is recorded and rejected even when interception claims success',()=>withFixture(async f=>{
  f.client.emit('Network.requestWillBeSent',{requestId:'original',request:{url:f.url}});
  f.client.emit('Network.dataReceived',{requestId:'original',dataLength:1024,encodedDataLength:768});
  f.client.emit('Network.loadingFinished',{requestId:'original'});
  await assert.rejects(()=>f.guard.assertHealthy(),/Original media bytes reached/);
  assert.equal(f.receipt.contract[0].receivedDataBytes,1024);assert.equal(f.receipt.contract[0].receivedEncodedBytes,768);
}));

test('request errors cannot disappear and all owned page/CDP listeners detach',()=>withFixture(async f=>{
  const broken=request(f.url);broken.abort=async()=>{throw new Error('TEST abort failure');};
  f.page.emit('request',broken);await assert.rejects(()=>f.guard.assertHealthy(),/TEST abort failure/);
  await assert.rejects(()=>f.guard.dispose(),/TEST abort failure/);
  assert.equal(f.page.listenerCount('request'),0);assert.equal(f.client.eventNames().length,0);assert.equal(f.client.detached,true);
}));

test('missing admitted video caches and non-local origins cannot arm source suppression',()=>withFixture(async f=>{
  assert.throws(()=>nativeOriginalMediaContract(f.context,'https://example.com'));
  f.context.cacheEntries=[];assert.throws(()=>nativeOriginalMediaContract(f.context,'http://localhost:4020'),/lacks an admitted/);
  f.context.request.captureMode='sdk-streaming';
  assert.throws(()=>nativeOriginalMediaGuard(f.context,'http://localhost:4020',{}),/requires exact cached/);
}));

test('guard is armed before SDK navigation and disposed after ordinary capture or initialization failure',async()=>{
  for(const fail of [false,true]){
    const f=batchFixture(10);let sawGuard=false;
    try {
      f.sdk.initializeSession=async session=>{
        sawGuard=session.page.listenerCount('request')===1;
        assert.ok(sawGuard,'Original requests must be guarded before navigation');
        if(fail)throw new Error('TEST navigation failure');
      };
      const result=await runNativeBatchedRender(f.request,{sdk:f.sdk,encode:f.encode});assert.ok(sawGuard);
      assert.equal(result.status,fail?'failed':'picture-encoded-awaiting-parent-qc');
      assert.ok(result.batches.every(row=>row.originalMedia.disposed&&row.mediaGuardDisposed&&row.sessionClosed&&row.serverClosed));
      assert.ok(f.calls.sessions.every(session=>session.page.listenerCount('request')===0));
    }finally{f.cleanup();}
  }
});
