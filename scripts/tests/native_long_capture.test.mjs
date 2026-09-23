import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {longCapturePoints,checkLongScene} from '../producer/studio/native_long_capture.mjs';
import {longStoragePlan,longSourceProbes,probeLongSourceSizes,sourceFrameInventory,withSourceProgress} from '../producer/studio/native_long_sources.mjs';

test('fifteen minute seam checks include last frame, exact cuts and reverse visits',()=>{
  const plan={canvas:{frameRate:'30/1',totalFrames:27000},scenes:[
    {startFrame:0,endFrame:18000},{startFrame:18000,endFrame:26999},{startFrame:26999,endFrame:27000}]};
  const points=longCapturePoints(plan),forward=points.slice(0,points.length/2);
  for(const frame of [0,17999,18000,18001,26998,26999])assert.ok(forward.includes(frame));
  assert.deepEqual(points.slice(points.length/2),forward.slice().reverse());
});

test('future allocation deduplicates identical ranges and retains free-space reserve',()=>{
  const row={key:'same',width:1920,height:1080,frames:27000,bytesPerFrame:100000,cached:false};
  const canvas={width:1920,height:1080,totalFrames:27000};
  const once=longStoragePlan([row],canvas,900),twice=longStoragePlan([row,row],canvas,900);
  assert.equal(once.plannedBytes,twice.plannedBytes);
  assert.equal(once.requiredFreeBytes,once.plannedBytes+10*1024**3);
  assert.equal(longStoragePlan([{...row,cached:true}],canvas,900).sourceBytes,0);
  assert.equal(longStoragePlan([row,{...row,cached:true}],canvas,900).sourceBytes,once.sourceBytes);
  assert.equal(longStoragePlan([{...row,cached:true,hdr:true}],canvas,900).sourceBytes,once.sourceBytes);
  assert.throws(()=>longStoragePlan([{...row,frames:NaN}],canvas,900));
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
