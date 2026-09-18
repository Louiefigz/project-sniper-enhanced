/** Full-project absolute-time seam/end/reverse samples before a long master. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {assertNativeCaptureOwner} from './runtime/native-export-guard.mjs';
import {createNativeCaptureContext,prepareNativeCaptureContext,withNativeCaptureSession,
  captureNativeFrame,nativeCaptureEvidence,nativeCaptureFailure,nativeCaptureHash} from './native_short_capture_context.mjs';
import {visualState} from './native_short_capture_checks.mjs';
import {nativeBatchEncoderArgs,encodeNativeBatchPicture} from './native_short_batched_render.mjs';

/** Include a five-frame neighborhood around every cut, both endpoints and periodic interiors. */
export function longCapturePoints(plan) {
  const total=plan.canvas.totalFrames,[num,den]=plan.canvas.frameRate.split('/').map(Number),rate=num/den;
  const values=new Set([0,total-1]);
  for(const scene of plan.scenes)for(const boundary of [scene.startFrame,scene.endFrame]){
    for(let delta=-2;delta<=2;delta++)if(boundary+delta>=0&&boundary+delta<total)values.add(boundary+delta);
  }
  for(let frame=0;frame<total;frame+=Math.max(1,Math.floor(rate*2)))values.add(frame);
  const forward=[...values].sort((a,b)=>a-b);
  assert.ok(forward.length<=3000,'Long sample inventory exceeds its bound');
  return [...forward,...forward.slice().reverse()];
}

/** Visible timed layers outside their active window reveal stale cut state before export. */
export async function checkLongScene(page, frame, plan) {
  const scene=plan.scenes.find(row=>row.startFrame<=frame&&frame<row.endFrame);
  assert.ok(scene,'Long frame lacks scene ownership');
  const observed=await page.evaluate(()=>{
    const visible=el=>{
      for(let node=el;node;node=node.parentElement){
        const css=getComputedStyle(node);
        if(css.display==='none'||css.visibility==='hidden'||Number(css.opacity)===0||css.clipPath==='inset(100%)')return false;
      }
      const box=el.getBoundingClientRect();return box.width>0&&box.height>0;
    };
    return [...document.querySelectorAll('video')].filter(video=>{
      const image=video.nextElementSibling;
      return image?.classList.contains('__render_frame__')?visible(image):visible(video);
    }).map(video=>video.id).sort();
  });
  assert.deepEqual(observed,[...scene.mediaIds].sort(),`Stale or missing picture layer at frame ${frame}`);
  return {frame,mediaIds:observed};
}

async function captureReferences(context, receipt) {
  const frames=longCapturePoints(context.plan),work=context.work,prior=new Map();
  receipt.expectedCapturePoints=frames;
  const sessionReceipt={frames,startedAt:new Date().toISOString()};receipt.sessions=[sessionReceipt];
  await withNativeCaptureSession(context,{framesDir:path.join(work,'frames'),receipt:sessionReceipt},async session=>{
    for(const [index,frame] of frames.entries()){
      const captured=await captureNativeFrame(context,session,frame);
      const destination=path.join(work,`pose-${index}.jpg`);
      fs.copyFileSync(captured.path,destination,fs.constants.COPYFILE_EXCL);
      const state=await visualState(session.page),scene=await checkLongScene(session.page,frame,context.plan);
      const previous=prior.get(frame);
      if(previous){
        assert.deepEqual(state,previous.visualState,`Reverse scene mismatch at ${frame}`);
        assert.deepEqual(captured.payload,previous.payload,`Reverse source mismatch at ${frame}`);
      }
      const row={...captured,path:destination,repeat:!!previous,visualState:state,scene};
      receipt.frames.push(row);prior.set(frame,row);
      console.log(`SNIPER_PROGRESS samples ${index+1}`);
    }
  });
}

async function encodeSamples(context, receipt) {
  const directory=path.join(context.work,'reel');fs.mkdirSync(directory);
  const forward=receipt.frames.filter(row=>!row.repeat);
  for(const [index,row] of forward.entries())fs.copyFileSync(row.path,
    path.join(directory,`frame_${String(index).padStart(6,'0')}.jpg`),fs.constants.COPYFILE_EXCL);
  const output=path.join(context.request.output,'seam-samples.mp4');
  const args=nativeBatchEncoderArgs({fps:context.fps,framesDir:directory,output,totalFrames:forward.length,version:'0.8.31'});
  // Same metadata-only sRGB correction as the shared final delivery path.
  args.splice(-2,0,'-bsf:v','h264_metadata=colour_primaries=1:transfer_characteristics=13:matrix_coefficients=1:video_full_range_flag=0');
  await encodeNativeBatchPicture(context.request.tools.ffmpeg,args);
  receipt.sampleReel={path:output,sha256:nativeCaptureHash(output),frames:forward.map(row=>row.frame),
    scope:'Selected full-context frame neighborhoods; not a continuous full-program preview'};
}

/** Never mutate authored HTML, shorten its timeline or claim final encoded delivery here. */
export async function captureLong(request) {
  const receipt={status:'failed',project:request.project,fromEncodedOutput:false,frames:[],failedSceneStates:[]};
  let context;
  try{
    context=await createNativeCaptureContext(request,path.join(request.output,'native-capture'));
    await prepareNativeCaptureContext(context);
    await captureReferences(context,receipt);await encodeSamples(context,receipt);
    receipt.status='native-references-and-seek-states-pass';
  }catch(error){receipt.error=nativeCaptureFailure(error);}
  finally{
    if(context)Object.assign(receipt,nativeCaptureEvidence(context));
    fs.writeFileSync(path.join(request.output,'native-frames.json'),JSON.stringify(receipt,null,2),{flag:'wx'});
  }
  return receipt;
}

if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url){
  assertNativeCaptureOwner(process.argv[2]);
  const result=await captureLong(JSON.parse(fs.readFileSync(process.argv[2],'utf8')));
  if(result.status!=='native-references-and-seek-states-pass')process.exitCode=1;
}
