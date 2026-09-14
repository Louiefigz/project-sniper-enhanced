/** Experimental opt-in: disposable native screenshot sessions, one full-quality picture encode. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {createRequire} from 'node:module';
import {pathToFileURL} from 'node:url';
import {createNativeCaptureContext,prepareNativeCaptureContext,withNativeCaptureSession,captureNativeFrame,
  nativeCaptureHash,nativeCaptureBatches,nativeCaptureEvidence,nativeCaptureFailure} from './native_short_capture_context.mjs';
import {nativeCaptureQcPoints} from './native_short_capture.mjs';
import {nativeForwardQcIdentity,observeNativeForwardQc,writeNativePictureReceipt} from './native_forward_qc.mjs';

/** SDK high/crf15 encoding; explicit frame0/cap and no-overwrite flags change ownership, not picture quality. */
export function nativeBatchEncoderArgs(options) {
  const {fps,framesDir,output,totalFrames,version}=options,rate=fps.den===1?String(fps.num):`${fps.num}/${fps.den}`;
  assert.ok(Number.isSafeInteger(totalFrames)&&totalFrames>0,'Invalid complete picture frame inventory');
  return ['-framerate',rate,'-start_number','0','-i',path.join(framesDir,'frame_%06d.jpg'),'-frames:v',String(totalFrames),'-r',rate,
    '-c:v','libx264','-preset','slow','-crf','15','-bf','0','-x264-params',
    'aq-mode=3:aq-strength=0.8:deblock=1,1:colorprim=bt709:transfer=bt709:colormatrix=bt709',
    '-colorspace:v','bt709','-color_primaries:v','bt709','-color_trc:v','bt709','-color_range','tv',
    '-vf','scale=in_range=pc:out_range=tv','-video_track_timescale','90000','-pix_fmt','yuv420p',
    '-avoid_negative_ts','make_zero','-metadata','hyperframes_renderer=hyperframes',
    '-metadata',`hyperframes_version=${version}`,'-movflags','+use_metadata_tags','-n',output];
}

/** Match SDK renderProvenance.readEngineVersion at the actual CLI module location. */
function encoderVersion(runtime) {
  try { const version=createRequire(path.join(runtime,'dist/cli.js'))('../../package.json').version;
    return typeof version==='string'&&version.length?version:'0.0.0-dev'; }
  catch { return '0.0.0-dev'; }
}

/** Encode once, with bounded lifetime and inherited supervisor-visible child output. */
export function encodeNativeBatchPicture(command, args) {
  return new Promise((resolve,reject)=>{
    const child=spawn(command,args,{stdio:['ignore','inherit','inherit']}),started=Date.now();
    let timedOut=false,forced;
    const deadline=setTimeout(()=>{timedOut=true;child.kill('SIGTERM');forced=setTimeout(()=>child.kill('SIGKILL'),2000);},480000);
    child.once('error',error=>{clearTimeout(deadline);clearTimeout(forced);reject(error);});
    child.once('close',(code,signal)=>{
      clearTimeout(deadline);clearTimeout(forced);
      if(code!==0||timedOut)reject(new Error(`Native batch picture encode failed: code=${code} signal=${signal} deadline=${timedOut}`));
      else resolve({exitCode:code,elapsedMs:Date.now()-started});
    });
  });
}

/** Confirm every declared screenshot is still present and unchanged before the single encode. */
export function verifyNativeBatchFrames(context, receipt, framesDir) {
  const count=context.plan.canvas.totalFrames;
  assert.deepEqual(receipt.frames.map(row=>row.frame),Array.from({length:count},(_,frame)=>frame),'Incomplete native batch frame inventory');
  assert.deepEqual(fs.readdirSync(framesDir).sort(),Array.from({length:count},(_,frame)=>`frame_${String(frame).padStart(6,'0')}.jpg`),
    'Native batch picture directory has missing or unexpected frames');
  for(const row of receipt.frames)assert.equal(nativeCaptureHash(row.path),row.sha256,'Native screenshot changed before encode');
}

async function captureAllFrames(context, receipt, framesDir) {
  const frames=Array.from({length:context.plan.canvas.totalFrames},(_,frame)=>frame);
  const points=nativeCaptureQcPoints(context.plan,true,context.batchPlan.maximumFrames);
  const forward=points.slice(0,points.indexOf(context.plan.canvas.totalFrames-1)+1),checks=new Set(forward);
  receipt.forwardQc=nativeForwardQcIdentity(context,forward);
  for(const [index,points] of nativeCaptureBatches(frames,context.batchPlan.maximumFrames).entries()){
    const batch={index,startFrame:points[0],endFrameExclusive:points.at(-1)+1,frames:points,startedAt:new Date().toISOString()};
    receipt.batches.push(batch);
    await withNativeCaptureSession(context,{framesDir,receipt:batch},async session=>{
      for(const frame of points){
        const row=await captureNativeFrame(context,session,frame);
        assert.equal(row.path,path.join(framesDir,`frame_${String(frame).padStart(6,'0')}.jpg`),'Unexpected SDK screenshot filename');
        if(checks.has(frame))row.forwardQc=await observeNativeForwardQc(context,session,frame);
        receipt.frames.push(row);
      }
    });
    batch.status='captured-and-disposed';batch.finishedAt=new Date().toISOString();
  }
}

/** Parent wrapper retains source authority, resource ownership, audio/color delivery and final QC. */
export async function runNativeBatchedRender(request, dependencies={}) {
  const receiptPath=path.join(request.output,'batched-picture.json'),work=path.join(request.output,'batched-native-render');
  const framesDir=path.join(work,'frames'),output=path.join(request.output,'picture.mp4');
  const receipt={schemaVersion:1,scope:'experimental-cached-native-batch-picture',status:'failed',
    pictureMode:'cached-native-batches',referenceEncoding:'jpeg95-matching-opaque-render',project:request.project,
    output,batches:[],frames:[],cacheEntries:[],audio:'parent-dialogue-delivery',encodedPictureQc:'not-performed-here'};
  let context;
  try {
    assert.equal(request.captureMode,'cached-native-batches','Batch capture requires the explicit opt-in request');
    assert.ok(!fs.existsSync(output),'Native batch output already exists');
    context=await createNativeCaptureContext(request,work,dependencies.sdk);
    await prepareNativeCaptureContext(context);Object.assign(receipt,nativeCaptureEvidence(context));
    receipt.totalFrames=context.plan.canvas.totalFrames;
    await captureAllFrames(context,receipt,framesDir);verifyNativeBatchFrames(context,receipt,framesDir);
    assert.equal(context.sourceHtmlSha256,nativeCaptureHash(path.join(request.project,'index.html')));
    const args=nativeBatchEncoderArgs({fps:context.fps,framesDir,output,totalFrames:receipt.totalFrames,version:encoderVersion(request.runtime)});
    receipt.encoder={command:request.tools.ffmpeg,args,sdkCliSha256:nativeCaptureHash(path.join(request.runtime,'dist/cli.js')),
      quality:'high',crf:15,codec:'h264',preset:'slow',pixelFormat:'yuv420p',width:1080,height:1920,passes:1};
    assert.ok(!fs.existsSync(output),'Native batch output appeared before encode');
    receipt.encodeResult=await (dependencies.encode??encodeNativeBatchPicture)(request.tools.ffmpeg,args);
    assert.ok(fs.statSync(output).size>0,'Native batch encoder produced no picture');
    verifyNativeBatchFrames(context,receipt,framesDir);
    receipt.sha256=nativeCaptureHash(output);receipt.status='picture-encoded-awaiting-parent-qc';
  }catch(error){receipt.error=nativeCaptureFailure(error);}
  finally{
    if(context)Object.assign(receipt,nativeCaptureEvidence(context));
    writeNativePictureReceipt(receiptPath,receipt);
  }
  return receipt;
}

if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url){
  const result=await runNativeBatchedRender(JSON.parse(fs.readFileSync(process.argv[2],'utf8')));
  if(result.status!=='picture-encoded-awaiting-parent-qc')process.exitCode=1;
}
