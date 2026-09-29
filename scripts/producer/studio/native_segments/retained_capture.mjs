/** Long window capture retention; source admission and dependency proof stay with the Python owner. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {retainedFrameHash,copyRetainedFrame} from '../native_retained_frames.mjs';

/** Validate private future disk and choose the already published exact capture partition. */
export function retainedCaptureSelection(request,index) {
  const window=request.revision.renderWindows[index];
  const all=Array.from({length:window.endFrame-window.startFrame},(_,offset)=>window.startFrame+offset);
  if(request.revision.mode!=='initial-long')return {frames:all,plan:null,retain:false};
  const canvas=request.revision.canvas,projection=request.diskProjection;
  const scope=request.sectionScope?.frameRange??[0,canvas.totalFrames];
  const selected=request.revision.renderWindows.filter(row=>row.startFrame>=scope[0]&&row.endFrame<=scope[1]);
  const count=selected.reduce((total,row)=>total+row.endFrame-row.startFrame,0);
  const bytes=count*canvas.width*canvas.height*4;
  assert.ok(all.length<=250&&count>0&&Number.isSafeInteger(bytes)&&bytes>0,'Invalid Long retained frame bounds');
  assert.ok(Number.isSafeInteger(projection?.retainedFrameBytes)&&projection.retainedFrameBytes>=bytes
    &&Number.isSafeInteger(projection.outputBytes)&&projection.outputBytes>=bytes+Math.ceil(canvas.totalFrames*canvas.width*canvas.height/4),
  'Long retained frame inventory lacks admitted disk projection');
  const plan=readRetainedFramePlan(request,index);
  assert.ok(!request.sectionRepair||plan,'Long repair lacks its published capture plan');
  if(plan){
    assert.deepEqual(plan.window,window);assert.equal(plan.planIdentity,request.revision.identity);
    assert.deepEqual([...plan.captureFrames,...plan.copyFrames].sort((a,b)=>a-b),all,'Long capture partition changed');
  }
  return {frames:plan?.captureFrames??all,plan,retain:true};
}

/** Resolve the immutable admitted window sidecar without multiplying the whole request pin map. */
export function readRetainedFramePlan(request,index) {
  const pin=request.sectionFrameReuse?.[`segment-picture-${index}`];
  if(!pin)return null;
  assert.deepEqual(Object.keys(pin).sort(),['path','sha256']);
  assert.equal(path.basename(pin.path),`segment-picture-${index}-frame-plan.json`);
  assert.equal(request.pins[pin.path],pin.sha256,'Retained frame plan is not admitted');
  assert.equal(retainedFrameHash(pin.path,1024*1024),pin.sha256);
  const value=JSON.parse(fs.readFileSync(pin.path,'utf8'));
  assert.equal(retainedFrameHash(pin.path,1024*1024),pin.sha256);
  return value;
}

/** Merge exclusively copied prior JPEGs with freshly captured frames before the complete encode. */
export function mergeRetainedCapture(request,selection,captured,directory) {
  if(!selection.retain)return captured;
  const canvas=request.revision.canvas,maximum=canvas.width*canvas.height*4;
  const rows=captured.rows.map(row=>({...row,bytes:fs.lstatSync(row.path).size,origin:'captured'}));
  const plan=selection.plan;
  if(plan?.copyFrames.length){
    const root=path.join(path.dirname(plan.baseline.manifest.path),'frames');
    const contract={root,frameRange:plan.frameRange,maximumBytes:maximum,pins:request.pins};
    const copies=new Set(plan.copyFrames);
    for(const row of plan.baseline.frames.filter(row=>copies.has(row.frame))){
      rows.push(copyRetainedFrame(row,directory,contract));
    }
  }
  for(const row of rows)assert.equal(retainedFrameHash(row.path,maximum),row.sha256);
  if(plan?.checkFrames.length){
    const baseline=new Map(plan.baseline.frames.map(row=>[row.frame,row.sha256]));
    const checks=new Set(plan.checkFrames);
    for(const row of rows.filter(row=>checks.has(row.frame))){
      assert.equal(row.sha256,baseline.get(row.frame),'Current unchanged capture differs from retained pixels');
    }
  }
  rows.sort((a,b)=>a.frame-b.frame);
  return {...captured,rows};
}

/** Publish actual JPEG bytes and disposed native capture session records after encode. */
export function saveRetainedCapture(request,window,captured,work) {
  if(request.revision.mode!=='initial-long')return null;
  const canvas=request.revision.canvas,maximum=canvas.width*canvas.height*4;
  for(const row of captured.rows)assert.equal(retainedFrameHash(row.path,maximum),row.sha256);
  const value={schemaVersion:1,kind:'native-retained-capture-frames',canvas,
    frameRange:[window.startFrame,window.endFrame],encoding:'jpeg95-matching-opaque-render',
    frames:captured.rows,sessions:captured.sessions};
  const file=path.join(work,'retained-frames.json');
  fs.writeFileSync(file,JSON.stringify(value,null,2),{flag:'wx'});
  return {path:file,sha256:retainedFrameHash(file,1024*1024)};
}
