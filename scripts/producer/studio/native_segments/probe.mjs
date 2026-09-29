/** Current-project dependency screenshots under the existing restored-window owner. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {assertNativeSegmentOwner,checkSegmentWindow} from './render.mjs';
import {prepareSparseLongContext} from './sparse_sources.mjs';
import {createNativeCaptureContext,withNativeCaptureSession,captureNativeFrame,nativeCaptureEvidence,
  nativeCaptureHash,nativeCaptureBatches} from '../native_short_capture_context.mjs';
import {checkLongScene} from '../native_long_capture.mjs';

/** Exact window endpoints and bounded interior states are evaluated in both seek directions. */
export function dependencyFrames(window) {
  const {startFrame:start,endFrame:end}=window;
  const values=new Set([start,end-1,Math.floor((start+end-1)/2)]);
  for(let frame=start;frame<end;frame+=Math.max(1,Math.ceil((end-start)/8)))values.add(frame);
  assert.ok(values.size<=12,'Dependency screenshot inventory exceeds window bound');
  return [...values].sort((a,b)=>a-b);
}

/** Every repeat must reproduce both original-source payloads and exact screenshot bytes. */
async function captureBatch(context,session,points,state) {
  for(const frame of points){
    const row=await captureNativeFrame(context,session,frame);
    await checkLongScene(session.page,frame,context.plan);
    if(state.prior.has(frame)){
      assert.equal(row.sha256,state.prior.get(frame).sha256,'Dependency reverse seek changed current pixels');
      assert.deepEqual(row.payload,state.prior.get(frame).payload,'Dependency reverse seek changed source frame');
    }else{
      const target=path.join(state.directory,`probe-${frame}.jpg`);
      fs.copyFileSync(row.path,target,fs.constants.COPYFILE_EXCL);state.prior.set(frame,{...row,path:target});
    }
    console.log(`SNIPER_PROGRESS dependency-probe ${++state.completed}`);
  }
}

/** Session cleanup remains the existing native lifecycle for every bounded group. */
async function capturePoints(context, points, directory) {
  const state={prior:new Map(),completed:0,directory},sessions=[];
  const sequence=[...points,...points.slice().reverse()];
  for(const batch of nativeCaptureBatches(sequence,context.batchPlan.maximumFrames)){
    const receipt={frames:batch};sessions.push(receipt);
    await withNativeCaptureSession(context,{framesDir:path.join(directory,`session-${sessions.length}`),receipt},
      session=>captureBatch(context,session,batch,state));
  }
  return {probes:points.map(frame=>state.prior.get(frame)),sessions};
}

/** Compile current immutable project bytes, never the donor's saved HTML. */
export async function captureDependencyProbes(request,index,directory,dependencies={}) {
  assert.ok(path.dirname(path.dirname(directory))===request.output&&!fs.existsSync(directory),'Invalid new dependency capture directory');
  const window=request.revision.renderWindows[index];
  checkSegmentWindow(window,request.revision.canvas.totalFrames);
  const context=await createNativeCaptureContext(request,directory,dependencies.sdk);
  const points=dependencies.points??dependencyFrames(window);
  assert.ok(Array.isArray(points)&&points.length>0&&points.length<=64
    &&points.every((frame,i)=>Number.isSafeInteger(frame)&&window.startFrame<=frame&&frame<window.endFrame
      &&(i===0||points[i-1]<frame)),'Invalid current dependency state inventory');
  await prepareSparseLongContext(context,points);
  const captured=await capturePoints(context,points,directory);
  assert.equal(nativeCaptureHash(path.join(request.project,'index.html')),context.sourceHtmlSha256,'Current project changed during probes');
  return {schemaVersion:1,kind:'native-long-current-dependency-capture',planIdentity:request.revision.identity,
    window,...captured,...nativeCaptureEvidence(context),sparseSources:context.sparseSources,
    runtimeQualification:'not-established',editorialApproval:false};
}

if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url){
  const [file,indexText,directory,pointsText]=process.argv.slice(2),index=Number(indexText);
  assert.ok(Number.isSafeInteger(index)&&index>=0&&index<768);
  const request=assertNativeSegmentOwner(file,index);
  assert.ok(request.revision.windowDonors?.[`segment-picture-${index}`],'Dependency capture requires its admitted donor window');
  const result=await captureDependencyProbes(request,index,directory,{points:JSON.parse(pointsText)});
  fs.writeFileSync(path.join(directory,'capture.json'),JSON.stringify(result,null,2),{flag:'wx'});
}
