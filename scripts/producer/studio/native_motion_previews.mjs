/** Continuous absolute-time windows through the same native capture and picture encoder. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {assertNativePreviewOwner} from './runtime/native-export-guard.mjs';
import {createNativeCaptureContext,prepareNativeCaptureContext,withNativeCaptureSession,captureNativeFrame,
  nativeCaptureBatches,nativeCaptureHash} from './native_short_capture_context.mjs';
import {nativeBatchEncoderArgs,encodeNativeBatchPicture} from './native_short_batched_render.mjs';

/** The original composition, clock, source lookup and full-quality encoder remain unchanged. */
export async function renderMotionWindows(request, windows, dependencies={}) {
  const work=path.join(request.output,`motion-preview-capture-${windows[0]?.startFrame??'empty'}`);
  const context=await createNativeCaptureContext(request,work,dependencies.sdk);
  await prepareNativeCaptureContext(context);
  const results=[];
  for(const [index,window] of windows.entries()){
    const {startFrame,endFrame}=window;
    assert.ok(Number.isSafeInteger(startFrame)&&Number.isSafeInteger(endFrame)&&startFrame>=0
      &&endFrame<=context.plan.canvas.totalFrames&&endFrame>startFrame&&(endFrame-startFrame)/context.rate<=12,
    'Motion preview window exceeds its explicit clock or duration');
    const directory=path.join(work,`window-${index}`);fs.mkdirSync(directory);
    const framesDir=path.join(directory,'frames');fs.mkdirSync(framesDir);
    const frames=Array.from({length:endFrame-startFrame},(_,offset)=>startFrame+offset),sessions=[],pins=[];
    for(const points of nativeCaptureBatches(frames,context.batchPlan.maximumFrames)){
      const receipt={frames:points};sessions.push(receipt);
      await withNativeCaptureSession(context,{framesDir:path.join(directory,`source-${sessions.length}`),receipt},async session=>{
        for(const frame of points){
          const row=await captureNativeFrame(context,session,frame);
          const target=path.join(framesDir,`frame_${String(frame-startFrame).padStart(6,'0')}.jpg`);
          fs.copyFileSync(row.path,target,fs.constants.COPYFILE_EXCL);pins.push({path:target,sha256:row.sha256});
          console.log(`SNIPER_PROGRESS motion-preview ${results.reduce((sum,row)=>sum+row.frames,0)+pins.length}`);
        }
      });
    }
    for(const row of pins)assert.equal(nativeCaptureHash(row.path),row.sha256,'Preview screenshot changed');
    const output=path.join(directory,'picture.mp4');
    const args=nativeBatchEncoderArgs({fps:context.fps,framesDir,output,totalFrames:frames.length,version:'0.8.31'});
    args.splice(-2,0,'-bsf:v','h264_metadata=colour_primaries=1:transfer_characteristics=13:matrix_coefficients=1:video_full_range_flag=0');
    await (dependencies.encode??encodeNativeBatchPicture)(request.tools.ffmpeg,args);
    results.push({...window,frames:frames.length,path:output,sha256:nativeCaptureHash(output),sessions});
  }
  assert.equal(nativeCaptureHash(path.join(request.project,'index.html')),context.sourceHtmlSha256);
  return results;
}

if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url){
  assertNativePreviewOwner(process.argv[2]);
  const request=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
  const index=Number(process.argv[3]);
  assert.ok(Number.isSafeInteger(index)&&index>=0&&index<768,'Invalid preview section');
  const input=JSON.parse(fs.readFileSync(path.join(request.output,`preview-picture-${index}-input.json`),'utf8'));
  const results=await renderMotionWindows(request,[input.window]);
  fs.writeFileSync(path.join(request.output,`preview-picture-${index}-picture.json`),JSON.stringify(results[0],null,2),{flag:'wx'});
}
