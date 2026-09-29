/** Test actual render orchestration with fictional SDK pixels; no real-media performance claim. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import {retainedCaptureSelection} from '../producer/studio/native_segments/retained_capture.mjs';
import {retainedFrameHash} from '../producer/studio/native_retained_frames.mjs';
import {retainedFixture,retainedPlan,publishPlan} from './native_long_retained_capture_fixture.mjs';

/** Cold-open the actual newly published retained inventory and verify its content pin. */
function inventory(receipt) {
  assert.equal(retainedFrameHash(receipt.retainedFrames.path,1024*1024),receipt.retainedFrames.sha256);
  return JSON.parse(fs.readFileSync(receipt.retainedFrames.path,'utf8'));
}

/** Assert the real encoder argument builder retained the complete absolute codec window. */
function exactEncode(f) {
  assert.equal(f.calls.encodes.length,1);
  const args=f.calls.encodes[0];
  assert.equal(args[args.indexOf('-start_number')+1],'50');
  assert.equal(args[args.indexOf('-frames:v')+1],'60');
  assert.equal(args[args.indexOf('-video_track_timescale')+1],'25');
  assert.equal(fs.readdirSync(path.dirname(args[args.indexOf('-i')+1])).filter(name=>name.endsWith('.jpg')).length,60);
}

test('initial Long retains every absolute JPEG and disposed capture session after full encode',async t=>{
  const f=retainedFixture(t),receipt=await f.run(),value=inventory(receipt);
  assert.deepEqual(f.calls.frames,Array.from({length:60},(_,offset)=>50+offset));
  assert.deepEqual(value.frameRange,[50,110]);assert.equal(value.encoding,'jpeg95-matching-opaque-render');
  assert.equal(value.frames.length,60);assert.equal(value.sessions.length,2);
  assert.deepEqual(value.sessions.map(row=>row.frames.length),[48,12]);
  assert.ok(value.sessions.every(row=>row.sessionClosed&&row.browserPoolDrained&&row.serverClosed&&row.mediaGuardDisposed));
  assert.ok(value.frames.every(row=>row.origin==='captured'&&row.bytes===fs.statSync(row.path).size
    &&retainedFrameHash(row.path,1920*1080*4)===row.sha256));
  assert.equal(f.calls.sessionCloses,2);assert.equal(f.calls.poolDrains,2);exactEncode(f);
});

test('local repair captures dirty frames plus frozen checks, copies the remainder and encodes full window',async t=>{
  const f=retainedFixture(t),plan=retainedPlan(f),receipt=await f.run(),value=inventory(receipt);
  assert.deepEqual(f.calls.frames,plan.captureFrames);assert.equal(value.sessions.length,1);
  assert.deepEqual(value.frames.filter(row=>row.origin==='captured').map(row=>row.frame),plan.captureFrames);
  assert.deepEqual(value.frames.filter(row=>row.origin==='retained').map(row=>row.frame),plan.copyFrames);
  for(const row of value.frames.filter(row=>row.origin==='retained')){
    const original=plan.baseline.frames.find(prior=>prior.frame===row.frame);
    assert.equal(row.sha256,original.sha256);assert.notEqual(row.path,original.path);
    assert.equal(retainedFrameHash(original.path,4096),original.sha256);
  }
  exactEncode(f);
});

test('all-copy request without mandatory current recapture checks fails closed',async t=>{
  const f=retainedFixture(t);retainedPlan(f,[],[]);
  await assert.rejects(f.run(),/Invalid bounded source frame inventory/);
  assert.deepEqual(f.calls.frames,[]);assert.equal(f.calls.encodes.length,0);
});

test('bad disk projection and missing repair capture plan refuse before SDK capture',async t=>{
  const f=retainedFixture(t);
  f.request.diskProjection.retainedFrameBytes--;
  await assert.rejects(f.run('disk'),/disk projection/);
  f.request.diskProjection.retainedFrameBytes++;
  f.request.sectionRepair={parentAttempt:'TEST absent plan'};
  await assert.rejects(f.run('plan'),/published capture plan/);
  assert.deepEqual(f.calls.frames,[]);assert.equal(f.calls.encodes.length,0);
});

test('changed plan identity, duplicate partition and omitted frame are rejected',t=>{
  const f=retainedFixture(t),plan=retainedPlan(f);
  plan.planIdentity='c'.repeat(64);publishPlan(f,plan);assert.throws(()=>retainedCaptureSelection(f.request,0));
  plan.planIdentity=f.request.revision.identity;
  plan.copyFrames.push(72);publishPlan(f,plan);assert.throws(()=>retainedCaptureSelection(f.request,0),/partition/);
  plan.copyFrames.pop();plan.copyFrames.pop();publishPlan(f,plan);assert.throws(()=>retainedCaptureSelection(f.request,0),/partition/);
});

test('unavailable donor row cannot silently produce an incomplete codec-window inventory',async t=>{
  const f=retainedFixture(t),plan=retainedPlan(f);
  plan.baseline.frames=plan.baseline.frames.filter(row=>row.frame!==51);publishPlan(f,plan);
  await assert.rejects(f.run(),/Incomplete native segment encoder inventory/);
  assert.equal(f.calls.encodes.length,0);
});

test('unpinned or changed copied bytes fail before encode',async t=>{
  const f=retainedFixture(t),plan=retainedPlan(f),donor=plan.baseline.frames[1];
  delete f.request.pins[donor.path];
  await assert.rejects(f.run('unpinned'),/not pinned/);
  f.request.pins[donor.path]=donor.sha256;fs.writeFileSync(donor.path,'X'.repeat(donor.bytes));
  await assert.rejects(f.run('changed'),/changed/);
  assert.equal(f.calls.encodes.length,0);
});

test('admitted sidecar pin and recaptured unchanged pixels are checked before encode',async t=>{
  const f=retainedFixture(t),plan=retainedPlan(f),pin=f.request.sectionFrameReuse['segment-picture-0'];
  delete f.request.pins[pin.path];assert.throws(()=>retainedCaptureSelection(f.request,0),/not admitted/);
  f.request.pins[pin.path]=pin.sha256;fs.appendFileSync(pin.path,' ');
  assert.throws(()=>retainedCaptureSelection(f.request,0));
  const check=plan.baseline.frames[0];fs.writeFileSync(check.path,'TEST differently approved prior check');
  check.bytes=fs.statSync(check.path).size;check.sha256=retainedFrameHash(check.path,4096);
  f.request.pins[check.path]=check.sha256;publishPlan(f,plan);
  await assert.rejects(f.run(),/Current unchanged capture differs/);
  assert.equal(f.calls.encodes.length,0);
});

test('post-encode captured or copied byte mutation refuses publication and retains diagnosis bytes',async t=>{
  const f=retainedFixture(t);retainedPlan(f);
  for(const frame of [50,51]){
    const name=`mutation-${frame}`,encode=async(command,args)=>{
      const result=await f.encode(command,args),directory=path.dirname(args[args.indexOf('-i')+1]);
      fs.writeFileSync(path.join(directory,`frame_${String(frame).padStart(6,'0')}.jpg`),'TEST encoder mutated frame');return result;
    };
    await assert.rejects(f.run(name,encode),/screenshot changed/);
    assert.equal(fs.existsSync(path.join(f.request.output,name,'retained-frames.json')),false);
    assert.equal(fs.existsSync(path.join(f.request.output,name,'picture.mp4')),true);
  }
});

test('failed fresh recapture still disposes its owner session and never encodes',async t=>{
  const f=retainedFixture(t);retainedPlan(f);f.failFrame=72;
  await assert.rejects(f.run(),/Native capture session failed/);
  assert.equal(f.calls.encodes.length,0);assert.equal(f.calls.sessionCloses,1);
  assert.equal(f.calls.poolDrains,1);assert.equal(f.calls.serverCloses,1);
  assert.equal(fs.existsSync(path.join(f.request.output,'work/retained-frames.json')),false);
});

test('Short segment keeps its existing capture-all behavior and deletes transient JPEGs',async t=>{
  const f=retainedFixture(t,{long:false});retainedPlan(f,[72]);
  delete f.request.diskProjection;
  const receipt=await f.run();
  assert.deepEqual(f.calls.frames,Array.from({length:60},(_,offset)=>50+offset));
  assert.equal(receipt.retainedFrames,undefined);
  assert.equal(fs.existsSync(path.join(f.request.output,'work/frames')),false);
  assert.equal(fs.existsSync(path.join(f.request.output,'work/retained-frames.json')),false);
  assert.equal(f.calls.encodes.length,1);
});
