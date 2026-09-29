/** Common exact-byte retained screenshot primitives; adapters retain their own authority and limits. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';

/** Hash one bounded canonical single-link regular frame and detect mutation while reading. */
export function retainedFrameHash(file, maximumBytes) {
  assert.ok(path.isAbsolute(file)&&fs.realpathSync(file)===file,'Retained frame path is not canonical');
  assert.ok(Number.isSafeInteger(maximumBytes)&&maximumBytes>0,'Invalid retained frame byte ceiling');
  const descriptor=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
  try {
    const before=fs.fstatSync(descriptor);
    assert.ok(before.isFile()&&before.nlink===1&&before.size>0&&before.size<=maximumBytes,'Retained frame exceeds file contract');
    const hash=createHash('sha256'),buffer=Buffer.allocUnsafe(Math.min(maximumBytes,1024*1024));
    let count,total=0;
    while((count=fs.readSync(descriptor,buffer,0,buffer.length,null))>0){
      total+=count;assert.ok(total<=maximumBytes,'Retained frame grew beyond its byte ceiling');
      hash.update(buffer.subarray(0,count));
    }
    const after=fs.fstatSync(descriptor),visible=fs.lstatSync(file);
    for(const key of ['dev','ino','mtimeMs','size','nlink']){
      assert.equal(after[key],before[key],'Retained frame changed during reading');
      assert.equal(visible[key],before[key],'Retained frame path changed during reading');
    }
    assert.equal(total,before.size);return hash.digest('hex');
  }finally{fs.closeSync(descriptor);}
}

/** Intersect explicit ordered dirty intervals with a bounded absolute encoder frame range. */
export function retainedFramePartition(bounds, dirty, maximumFrames) {
  assert.ok(Array.isArray(bounds)&&bounds.length===2&&bounds.every(Number.isSafeInteger));
  const [start,end]=bounds;
  assert.ok(start>=0&&end>start&&Number.isSafeInteger(maximumFrames)&&end-start<=maximumFrames);
  assert.ok(Array.isArray(dirty)&&dirty.length<=4096);
  let cursor=0;const changed=new Set();
  for(const row of dirty){
    assert.ok(Array.isArray(row)&&row.length===2&&row.every(Number.isSafeInteger)&&cursor<=row[0]&&row[0]<row[1]);
    for(let frame=Math.max(start,row[0]);frame<Math.min(end,row[1]);frame++)changed.add(frame);
    cursor=row[1];
  }
  const frames=Array.from({length:end-start},(_,index)=>start+index);
  return {captured:frames.filter(frame=>changed.has(frame)),retained:frames.filter(frame=>!changed.has(frame))};
}

/** Verify exact pin, filename, frame range and byte size without granting revision compatibility. */
export function verifyRetainedFrame(row, contract) {
  assert.ok(Number.isSafeInteger(row.frame)&&contract.frameRange[0]<=row.frame&&row.frame<contract.frameRange[1]);
  assert.equal(row.path,path.join(contract.root,`frame_${String(row.frame).padStart(6,'0')}.jpg`));
  assert.match(row.sha256,/^[a-f0-9]{64}$/);assert.equal(contract.pins[row.path],row.sha256,'Retained frame is not pinned');
  assert.ok(Number.isSafeInteger(row.bytes)&&row.bytes>0&&row.bytes<=contract.maximumBytes);
  assert.equal(fs.lstatSync(row.path).size,row.bytes);
  assert.equal(retainedFrameHash(row.path,contract.maximumBytes),row.sha256,'Retained frame changed');
}

/** Copy exclusively with source and destination rechecks; the caller admits the unchanged frame. */
export function copyRetainedFrame(row, directory, contract) {
  verifyRetainedFrame(row,contract);
  assert.ok(path.isAbsolute(directory)&&fs.realpathSync(directory)===directory&&directory!==contract.root);
  const target=path.join(directory,`frame_${String(row.frame).padStart(6,'0')}.jpg`);
  fs.copyFileSync(row.path,target,fs.constants.COPYFILE_EXCL);
  assert.equal(retainedFrameHash(target,contract.maximumBytes),row.sha256,'Copied retained frame differs');
  verifyRetainedFrame(row,contract);
  return {...row,path:target,origin:'retained'};
}
