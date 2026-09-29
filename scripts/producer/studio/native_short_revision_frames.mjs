/** Preserve exact retained screenshots outside a proven local Short revision. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {retainedFrameHash,copyRetainedFrame} from './native_retained_frames.mjs';

const SHA256=/^[a-f0-9]{64}$/;
const MAX_PINNED_FILE_BYTES=2**40; // Same ceiling as upstream native_stage_evidence.verify_pins.

function rangeFrames(ranges,total) {
  assert.ok(Array.isArray(ranges),'Revision ranges are missing');
  const frames=new Set();let end=0;
  for(const row of ranges){
    assert.ok(Array.isArray(row)&&row.length===2&&row.every(Number.isSafeInteger)
      &&row[0]>=end&&row[0]<row[1]&&row[1]<=total,'Revision ranges overlap or exceed the canvas');
    for(let frame=row[0];frame<row[1];frame++)frames.add(frame);
    end=row[1];
  }
  return frames;
}

function pinnedFile(request,file,expected) {
  assert.ok(SHA256.test(expected),'Invalid revision file digest');
  assert.equal(request.pins[file],expected,'Revision dependency is not pinned');
  assert.equal(fs.realpathSync(file),file,'Revision dependency is not canonical');
  assert.ok(fs.lstatSync(file).isFile()&&!fs.lstatSync(file).isSymbolicLink(),'Invalid revision file');
  assert.equal(retainedFrameHash(file,MAX_PINNED_FILE_BYTES),expected,'Revision dependency changed');
}

/** Python derives the dependency proof; the render child verifies its exact pinned inventory again. */
export function revisionFramePlan(context) {
  const proof=context.request.pictureRevision;
  if(!proof)return null;
  assert.equal(proof.schemaVersion,1);assert.equal(proof.policy,'scoped-short-picture-v1');
  assert.ok(SHA256.test(proof.sharedHash),'Revision shared input identity is missing');
  const total=context.plan.canvas.totalFrames;
  assert.equal(proof.totalFrames,total);assert.equal(proof.frameRate,context.plan.canvas.frameRate);
  assert.ok(total>0&&total<=10800,'Revision frame inventory exceeds the Short limit');
  const dirty=rangeFrames(proof.dirtyRanges,total),unchanged=rangeFrames(proof.unchangedRanges,total);
  assert.equal(dirty.size+unchanged.size,total,'Revision ranges omit frames');
  assert.ok([...dirty].every(frame=>!unchanged.has(frame)),'Revision ranges overlap');
  assert.ok(path.isAbsolute(proof.donor.attempt)&&proof.donor.attempt!==context.request.output);
  pinnedFile(context.request,path.join(proof.donor.attempt,'export-request.json'),proof.donor.requestSha256);
  pinnedFile(context.request,path.join(proof.donor.attempt,'batched-picture.json'),proof.donor.pictureReceiptSha256);
  assert.ok(path.isAbsolute(proof.donor.checkedAttempt),'Revision baseline authority is missing');
  pinnedFile(context.request,path.join(proof.donor.checkedAttempt,'delivery.json'),proof.donor.checkedDeliverySha256);
  assert.ok(Array.isArray(proof.donorFrames)&&proof.donorFrames.length===total,'Revision baseline is incomplete');
  for(const [frame,row] of proof.donorFrames.entries()){
    assert.equal(row.frame,frame);
    assert.equal(row.path,path.join(proof.donor.attempt,'batched-native-render/frames',`frame_${String(frame).padStart(6,'0')}.jpg`));
    pinnedFile(context.request,row.path,row.sha256);
  }
  return {proof,dirty,unchanged};
}

/** Copy exclusively, retain source evidence, and re-hash both sides after the copy. */
export function copyRevisionFrame(context,revision,frame,framesDir) {
  assert.ok(revision.unchanged.has(frame),'Cannot reuse a changed picture frame');
  const original=revision.proof.donorFrames[frame];
  const copied=copyRetainedFrame({...original,bytes:fs.lstatSync(original.path).size},framesDir,
    {root:path.join(revision.proof.donor.attempt,'batched-native-render/frames'),
      frameRange:[0,revision.proof.totalFrames],pins:context.request.pins,maximumBytes:MAX_PINNED_FILE_BYTES});
  return {frame,time:frame/context.rate,path:copied.path,sha256:original.sha256,
    origin:'unchanged-revision-frame',donor:original.path};
}

/** A current sparse QC replay outside the dirty region must match its retained picture exactly. */
export function verifyUnchangedCapture(revision,row) {
  if(!revision?.unchanged.has(row.frame))return;
  assert.equal(row.sha256,revision.proof.donorFrames[row.frame].sha256,
    'An unchanged-region QC frame differs; local revision proof cannot authorize this picture');
  row.origin='unchanged-revision-frame-rechecked';
}

/** The full batch inventory partitions into real captures and exact preserved frames. */
export function verifyRevisionBatch(batch,proof) {
  assert.ok(proof,'Reused frames require their revision proof');
  assert.ok(Array.isArray(batch.capturedFrames)&&Array.isArray(batch.reusedFrames));
  assert.deepEqual([...batch.capturedFrames,...batch.reusedFrames].sort((a,b)=>a-b),batch.frames,
    'Revision batch frame partition is incomplete');
  const unchanged=rangeFrames(proof.unchangedRanges,proof.totalFrames);
  assert.ok(batch.reusedFrames.every(frame=>unchanged.has(frame)),'Batch reuses a changed frame');
  if(batch.status==='reused-and-verified')assert.equal(batch.capturedFrames.length,0);
  else assert.ok(batch.capturedFrames.length>0,'Captured batch contains no actual captures');
}
