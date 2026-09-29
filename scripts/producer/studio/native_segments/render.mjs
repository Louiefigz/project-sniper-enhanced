/**
 * One owner-gated absolute-frame window of the FINAL picture for a revision.
 *
 * Reuses the verified range primitive (nativeWindowBatchPlan, withNativeCaptureSession,
 * captureNativeFrame) and the SDK-equivalent batch encoder arguments, with exactly two changes:
 * -start_number is the window's first absolute frame, and the container timescale is the delivered
 * picture's, so the segment is packet-compatible with the closed GOPs it sits between. No preview
 * transfer=13 bitstream edit is applied: the segment keeps the bt709 tags that the final delivery
 * route requires before its single verified sRGB correction. Each window is its own x264 run, so it
 * opens with an IDR and nothing references a frame outside it (bframes=0, closed GOP).
 */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import crypto from 'node:crypto';
import {pathToFileURL} from 'node:url';
import {createNativeCaptureContext,prepareNativeCaptureContext,withNativeCaptureSession,captureNativeFrame,
  nativeCaptureBatches,nativeCaptureHash,nativeCaptureEvidence} from '../native_short_capture_context.mjs';
import {nativeBatchEncoderArgs,encodeNativeBatchPicture,encoderVersion} from '../native_short_batched_render.mjs';
import {nativeWindowBatchPlan} from '../native_window_batch_plan.mjs';
import {prepareSparseLongContext} from './sparse_sources.mjs';
import {retainedCaptureSelection,mergeRetainedCapture,saveRetainedCapture} from './retained_capture.mjs';
import {importNativeCaptureLibrary,nativeTimingLedger,nativeTimingSummary,timedNativeSdk,timedStep}
  from '../native_capture_timing.mjs';

export const SEGMENT_COLOR_CONTRACT='bt709-sdk-tags-before-single-final-srgb-correction';
export const MAX_WINDOW_FRAMES=600;
const ACTIVE=['preparing','waiting-for-capacity','running'];

function must(value, message) {
  if(!value)throw new Error(`Native segment admission: ${message}`);
}

function readRecord(file) {
  must(typeof file==='string'&&path.isAbsolute(file),'missing absolute owner/request path');
  const stat=fs.lstatSync(file);
  must(stat.isFile()&&!stat.isSymbolicLink()&&stat.size<=64*1024**2&&fs.realpathSync(file)===file,'unsafe owner/request file');
  const bytes=fs.readFileSync(file);
  return {value:JSON.parse(bytes),sha:crypto.createHash('sha256').update(bytes).digest('hex')};
}

/**
 * Typed window gate: only the live export owner that launched native_short_worker.py with this
 * exact request and phase segment-picture-<index> may render it. A preview, capture, draft or
 * render owner cannot authorize a final window.
 * @param {string} file Absolute export request path.
 * @param {number} index Window index in the request's revision plan.
 * @param {object} environment Process environment carrying the owner binding.
 * @returns {object} The admitted export request.
 */
export function assertNativeSegmentOwner(file, index, environment=process.env) {
  must(file===environment.SNIPER_NATIVE_EXPORT_REQUEST,'segment render requires its export owner');
  const request=readRecord(file),owner=readRecord(environment.SNIPER_NATIVE_EXPORT_OWNER).value;
  const pid=Number(environment.SNIPER_NATIVE_EXPORT_PID);
  must(Number.isSafeInteger(pid)&&pid>1,'segment render has no live supervisor');
  process.kill(pid,0);
  must(owner.project===request.value.project&&ACTIVE.includes(owner.status)&&!owner.completedAt&&!owner.abortReason
    &&owner.additionalFilePinsBefore?.[file]===request.sha,'segment owner/request differs');
  const phase=`segment-picture-${index}`,args=owner.args;
  const worker=request.value.adapter==='native-long'?'native_long_worker.py':'native_short_worker.py';
  must(Array.isArray(args)&&args.length===7&&args[0]==='/usr/bin/sandbox-exec'&&path.basename(args[4])===worker
    &&args[5]===file&&args[6]===phase&&owner.output===path.join(request.value.output,`${phase}.json`),
  'segment render did not originate from its window owner');
  must(['segments','full-render','initial-long'].includes(request.value.revision?.mode)&&request.value.revision.renderWindows[index]?.index===index,
    'request is not a segment revision with this window');
  return request.value;
}

/**
 * A window is an integer half-open frame range inside the canvas and bounded in length.
 * @param {{startFrame:number,endFrame:number}} window Absolute half-open frame range.
 * @param {number} totalFrames Canvas frame count.
 */
export function checkSegmentWindow(window, totalFrames) {
  const {startFrame,endFrame}=window;
  assert.ok(Number.isSafeInteger(startFrame)&&Number.isSafeInteger(endFrame)&&startFrame>=0&&endFrame>startFrame
    &&endFrame<=totalFrames&&endFrame-startFrame<=MAX_WINDOW_FRAMES,'Segment window must be a bounded range inside the canvas');
}

/**
 * Segment encoder arguments: the SDK-equivalent batch contract with absolute frame names and the
 * delivered picture's container timescale; no preview color postprocessing.
 * @param {object} options fps, framesDir, output, startFrame, frames, version and timescale.
 * @returns {string[]} FFmpeg arguments.
 */
export function nativeSegmentEncoderArgs(options) {
  const {fps,framesDir,output,startFrame,frames,version,timescale}=options;
  assert.ok(Number.isSafeInteger(timescale)&&timescale>0,'Invalid segment timescale');
  const args=nativeBatchEncoderArgs({fps,framesDir,output,totalFrames:frames,version});
  const start=args.indexOf('-start_number'),scale=args.indexOf('-video_track_timescale');
  assert.ok(start>=0&&args[start+1]==='0'&&scale>=0&&!args.includes('-bsf:v'),'Unexpected native batch encoder contract');
  args[start+1]=String(startFrame);args[scale+1]=String(timescale);
  return args;
}

/** Hash the encoder arguments with the per-window paths, start and count removed. */
export function segmentEncoderContract(args) {
  const variable=new Set(['-i','-start_number','-frames:v']);
  const kept=args.slice(0,-1).map((value,index)=>index&&variable.has(args[index-1])?'<per-window>':value);
  return crypto.createHash('sha256').update(JSON.stringify(kept)).digest('hex');
}

async function captureFrames(context, points, framesDir) {
  const sessions=[],rows=[];
  fs.mkdirSync(framesDir,{recursive:true});
  for(const batch of points){
    const receipt={frames:[...batch]};sessions.push(receipt);
    rows.push(...await withNativeCaptureSession(context,{framesDir,receipt},async session=>{
      const captured=[];
      for(const frame of batch){
        const row=await captureNativeFrame(context,session,frame);
        assert.equal(row.path,path.join(framesDir,`frame_${String(frame).padStart(6,'0')}.jpg`),'Unexpected SDK screenshot filename');
        captured.push({frame,path:row.path,sha256:row.sha256});
        console.log(`SNIPER_PROGRESS final-segment ${frame}`);
      }
      return captured;
    }));
  }
  return {rows,sessions};
}

function reverify(rows) {
  for(const row of rows)assert.equal(nativeCaptureHash(row.path),row.sha256,'Native segment screenshot changed before encode');
}

function sourceCacheSummary(context) {
  const file=path.join(context.work,'source-cache.json');
  if(!fs.existsSync(file))return null;
  const receipt=JSON.parse(fs.readFileSync(file,'utf8')),outcomes={};
  for(const row of receipt.entries??[])outcomes[row.outcome]=(outcomes[row.outcome]??0)+1;
  return {status:receipt.status,entries:(receipt.entries??[]).length,outcomes};
}

async function encodeWindow(context, job, captured) {
  const {request,window,ledger,version}=job,framesDir=path.join(context.work,'frames');
  const output=path.join(context.work,'picture.mp4');
  const args=nativeSegmentEncoderArgs({fps:context.fps,framesDir,output,startFrame:window.startFrame,
    frames:window.endFrame-window.startFrame,version,timescale:request.revision.grid.timescale});
  reverify(captured.rows);
  const encoded=await timedStep(ledger,'encode',()=>(job.encode??encodeNativeBatchPicture)(request.tools.ffmpeg,args));
  reverify(captured.rows);
  if(request.revision.mode!=='initial-long')fs.rmSync(framesDir,{recursive:true});
  return {output,args,encodeMs:encoded.elapsedMs};
}

/**
 * Render one admitted window (and, for window 0, the plan's dependency probes).
 * @param {object} request The admitted export request carrying the revision plan.
 * @param {number} index Window index.
 * @param {string} work New absolute capture directory inside the attempt.
 * @param {object} dependencies Optional synthetic sdk/encode/version for tests.
 * @returns {Promise<object>} Window receipt: bytes, frame hashes, probes, encoder and timings.
 */
export async function renderFinalSegment(request, index, work, dependencies={}) {
  must(path.dirname(work)===request.output&&!fs.existsSync(work),'segment capture directory must be new inside the attempt');
  const window=request.revision.renderWindows[index],ledger=nativeTimingLedger();
  const sdk=timedNativeSdk(dependencies.sdk??await importNativeCaptureLibrary(request),ledger);
  const context=await createNativeCaptureContext(request,work,sdk);
  checkSegmentWindow(window,context.plan.canvas.totalFrames);
  const selection=retainedCaptureSelection(request,index),frames=selection.frames;
  const required=index===0?[...frames,...request.revision.probes]:frames;
  await timedStep(ledger,'prepare',()=>request.adapter==='native-long'
    ?prepareSparseLongContext(context,required):prepareNativeCaptureContext(context));
  const plan=nativeWindowBatchPlan(context,window.startFrame,window.endFrame);
  const fresh=await timedStep(ledger,'segmentCapture',()=>captureFrames(context,nativeCaptureBatches(frames,plan.maximumFrames),path.join(work,'frames')));
  assert.deepEqual(fresh.rows.map(row=>row.frame),frames,'Incomplete native segment capture inventory');
  const captured=mergeRetainedCapture(request,selection,fresh,path.join(work,'frames'));
  assert.deepEqual(captured.rows.map(row=>row.frame),Array.from({length:window.endFrame-window.startFrame},
    (_,offset)=>window.startFrame+offset),'Incomplete native segment encoder inventory');
  const job={request,window,ledger,version:dependencies.version??encoderVersion(request.runtime),encode:dependencies.encode};
  const encoded=await encodeWindow(context,job,captured);
  const retainedFrames=saveRetainedCapture(request,window,captured,work);
  const probes=index===0&&request.revision.probes.length
    ?(await timedStep(ledger,'probes',()=>captureFrames(context,nativeCaptureBatches(request.revision.probes,context.batchPlan.maximumFrames),path.join(work,'probes')))).rows:[];
  assert.equal(nativeCaptureHash(path.join(request.project,'index.html')),context.sourceHtmlSha256,'Project changed during segment render');
  return {schemaVersion:1,planIdentity:request.revision.identity,window,colorContract:SEGMENT_COLOR_CONTRACT,
    path:encoded.output,sha256:nativeCaptureHash(encoded.output),frameSha256:captured.rows.map(row=>row.sha256),probes,
    encoder:{args:encoded.args,colorContract:SEGMENT_COLOR_CONTRACT,contractSha256:segmentEncoderContract(encoded.args),encodeMs:encoded.encodeMs},
    sessions:captured.sessions.length,batchPlan:{maximumFrames:plan.maximumFrames,activeVideoIds:plan.activeVideoIds},
    sourceCache:sourceCacheSummary(context),timings:nativeTimingSummary(ledger),...nativeCaptureEvidence(context),
    ...(retainedFrames?{retainedFrames}:{})};
}

if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url){
  const [file,indexText,work]=process.argv.slice(2),index=Number(indexText);
  must(Number.isSafeInteger(index)&&index>=0&&index<768,'Invalid segment window index');
  const request=assertNativeSegmentOwner(file,index);
  const receipt=await renderFinalSegment(request,index,work);
  fs.writeFileSync(path.join(work,'window.json'),JSON.stringify(receipt,null,2),{flag:'wx'});
}
