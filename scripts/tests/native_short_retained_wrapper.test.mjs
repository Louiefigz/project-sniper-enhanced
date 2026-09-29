/** Short wrapper routing and byte reuse with fictional files; no native playback qualification. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {createHash} from 'node:crypto';
import {revisionFramePlan,copyRevisionFrame,verifyUnchangedCapture,verifyRevisionBatch}
  from '../producer/studio/native_short_revision_frames.mjs';

function fixture(t) {
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'short-wrapper-')));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const donor=path.join(root,'donor'),output=path.join(root,'current'),frames=path.join(donor,'batched-native-render/frames');
  fs.mkdirSync(frames,{recursive:true});fs.mkdirSync(output);
  const pins={},save=(file,text)=>{
    fs.writeFileSync(file,text);pins[file]=createHash('sha256').update(text).digest('hex');return pins[file];
  };
  const requestSha256=save(path.join(donor,'export-request.json'),'TEST prior request');
  const pictureReceiptSha256=save(path.join(donor,'batched-picture.json'),'TEST prior picture');
  const checkedDeliverySha256=save(path.join(donor,'delivery.json'),'TEST prior checked authority');
  const donorFrames=Array.from({length:6},(_,frame)=>{
    const file=path.join(frames,`frame_${String(frame).padStart(6,'0')}.jpg`);
    return {frame,path:file,sha256:save(file,`TEST JPEG frame ${frame}`)};
  });
  const proof={schemaVersion:1,policy:'scoped-short-picture-v1',sharedHash:'a'.repeat(64),
    totalFrames:6,frameRate:'25/1',dirtyRanges:[[2,3]],unchangedRanges:[[0,2],[3,6]],donorFrames,
    donor:{attempt:donor,requestSha256,pictureReceiptSha256,checkedAttempt:donor,checkedDeliverySha256}};
  const context={rate:25,plan:{canvas:{width:1080,height:1920,totalFrames:6,frameRate:'25/1'}},
    request:{output,pins,pictureRevision:proof}};
  return {root,output,proof,context};
}

test('absence of Short revision keeps default route unchanged',t=>{
  const f=fixture(t);delete f.context.request.pictureRevision;
  assert.equal(revisionFramePlan(f.context),null);
});

test('Short wrapper keeps exact origin metadata and copies exclusively',t=>{
  const f=fixture(t),revision=revisionFramePlan(f.context),before=fs.readFileSync(f.proof.donorFrames[4].path);
  const row=copyRevisionFrame(f.context,revision,4,f.output);
  assert.deepEqual(row,{frame:4,time:4/25,path:path.join(f.output,'frame_000004.jpg'),
    sha256:f.proof.donorFrames[4].sha256,origin:'unchanged-revision-frame',donor:f.proof.donorFrames[4].path});
  assert.deepEqual(fs.readFileSync(row.path),before);assert.deepEqual(fs.readFileSync(row.donor),before);
  assert.throws(()=>copyRevisionFrame(f.context,revision,4,f.output),/EEXIST/);
  assert.throws(()=>copyRevisionFrame(f.context,revision,2,f.output),/changed picture frame/);
});

test('donor mutation or missing pin refuses before any copy',t=>{
  const f=fixture(t),revision=revisionFramePlan(f.context),row=f.proof.donorFrames[0];
  delete f.context.request.pins[row.path];assert.throws(()=>copyRevisionFrame(f.context,revision,0,f.output),/not pinned/);
  f.context.request.pins[row.path]=row.sha256;fs.writeFileSync(row.path,'TEST replaced JPEG');
  assert.throws(()=>copyRevisionFrame(f.context,revision,0,f.output),/changed/);
  assert.deepEqual(fs.readdirSync(f.output),[]);
});

test('Short interval rejection and10800 limit are not replaced by clipped Long partition',t=>{
  const f=fixture(t);f.proof.dirtyRanges=[[2,7]];
  assert.throws(()=>revisionFramePlan(f.context),/overlap or exceed/);
  f.proof.dirtyRanges=[[2,3]];f.proof.unchangedRanges=[[0,3],[3,6]];
  assert.throws(()=>revisionFramePlan(f.context),/omit frames|overlap/);
  f.proof.totalFrames=f.context.plan.canvas.totalFrames=10801;
  assert.throws(()=>revisionFramePlan(f.context),/Short limit/);
});

test('Short policy and current unchanged QC checks remain mandatory',t=>{
  const f=fixture(t),revision=revisionFramePlan(f.context);
  assert.throws(()=>verifyUnchangedCapture(revision,{frame:4,sha256:'f'.repeat(64)}),/differs/);
  const row={frame:4,sha256:f.proof.donorFrames[4].sha256};verifyUnchangedCapture(revision,row);
  assert.equal(row.origin,'unchanged-revision-frame-rechecked');
  assert.throws(()=>verifyRevisionBatch({frames:[0,1,2],capturedFrames:[0],reusedFrames:[1,2]},f.proof),/changed frame/);
  f.proof.policy='native-long-frame-repair';assert.throws(()=>revisionFramePlan(f.context));
});

test('post-admission hardlink or empty JPEG replacement fails closed',t=>{
  const f=fixture(t),revision=revisionFramePlan(f.context),row=f.proof.donorFrames[0];
  fs.linkSync(row.path,path.join(f.root,'unadmitted-link.jpg'));
  assert.throws(()=>copyRevisionFrame(f.context,revision,0,f.output));
  fs.unlinkSync(path.join(f.root,'unadmitted-link.jpg'));fs.writeFileSync(row.path,'');
  assert.throws(()=>copyRevisionFrame(f.context,revision,0,f.output));
  assert.deepEqual(fs.readdirSync(f.output),[]);
});
