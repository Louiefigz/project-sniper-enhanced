/** Reuse checks observed during actual picture capture; independently replay every reverse occurrence. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {nativeCaptureHash,nativeCaptureBatches} from './native_short_capture_context.mjs';
import {checkTypography,visualState} from './native_short_capture_checks.mjs';

const HERE=path.dirname(fileURLToPath(import.meta.url));
const MAX_RECEIPT_BYTES=32*1024*1024;
const jsonHash=value=>createHash('sha256').update(JSON.stringify(value)).digest('hex');

/** Bind measured forward coverage to the current authored plan and actual checking code. */
export function nativeForwardQcIdentity(context, points) {
  return {schemaVersion:1,kind:'render-observed-forward-qc',points,
    projectSha256:nativeCaptureHash(path.join(context.project,'SHORT-PROJECT.json')),
    checksSha256:nativeCaptureHash(path.join(HERE,'native_short_capture_checks.mjs')),
    helperSha256:nativeCaptureHash(fileURLToPath(import.meta.url))};
}

/** Run the existing assertions on the real page; bound the repeated typography evidence. */
export async function observeNativeForwardQc(context, session, frame) {
  const typography=await checkTypography(session.page,frame,context.plan);
  return {typography:{status:'passed',observedSha256:jsonHash(typography)},
    visualState:await visualState(session.page)};
}

function readReceipt(file) {
  const before=fs.lstatSync(file,{bigint:true}),identity=s=>[s.dev,s.ino,s.size,s.mtimeNs,s.ctimeNs];
  assert.ok(before.isFile()&&!before.isSymbolicLink()&&before.size<=BigInt(MAX_RECEIPT_BYTES),'Invalid bounded picture QC receipt');
  const fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK);
  let bytes;
  try {
    const stat=fs.fstatSync(fd,{bigint:true});assert.deepEqual(identity(stat),identity(before),'Receipt changed before reading');
    const buffer=Buffer.alloc(Number(stat.size)+1);let count=0,read;
    while(count<buffer.length&&(read=fs.readSync(fd,buffer,count,buffer.length-count,null))>0)count+=read;
    assert.equal(count,Number(stat.size),'Receipt size changed while reading');
    assert.deepEqual(identity(fs.fstatSync(fd,{bigint:true})),identity(stat),'Receipt changed while reading');
    assert.deepEqual(identity(fs.lstatSync(file,{bigint:true})),identity(stat),'Receipt path changed while reading');
    bytes=buffer.subarray(0,count);
  }finally{fs.closeSync(fd);}
  return {value:JSON.parse(bytes.toString('utf8')),sha256:createHash('sha256').update(bytes).digest('hex')};
}

function verifyPicture(context, picture, root, points) {
  assert.deepEqual(picture.forwardQc,nativeForwardQcIdentity(context,points),'Forward QC authority differs');
  assert.equal(picture.status,'picture-encoded-awaiting-parent-qc');
  assert.equal(picture.pictureMode,'cached-native-batches');
  assert.equal(picture.referenceEncoding,'jpeg95-matching-opaque-render');
  assert.equal(picture.project,context.project);
  for(const key of ['sourceHtmlSha256','compiledSha256','runtimeLibrarySha256','batchPlan']){
    assert.deepEqual(picture[key],context[key],`Forward QC ${key} differs`);
  }
  assert.equal(picture.encoder.sdkCliSha256,nativeCaptureHash(path.join(context.runtime,'dist/cli.js')));
  assert.equal(picture.encoder.command,context.request.tools.ffmpeg);
  for(const [key,value] of Object.entries({quality:'high',crf:15,preset:'slow',codec:'h264',passes:1,
    pixelFormat:'yuv420p',width:1080,height:1920}))assert.equal(picture.encoder[key],value);
  assert.equal(picture.frameRate,context.plan.canvas.frameRate);
  assert.equal(picture.totalFrames,context.plan.canvas.totalFrames);
  assert.equal(picture.encodeResult.exitCode,0);
  assert.equal(picture.output,path.join(root,'picture.mp4'));
  assert.equal(picture.sha256,nativeCaptureHash(picture.output),'Retained picture changed');
  assert.equal(picture.sha256,nativeCaptureHash(path.join(context.request.output,'picture.mp4')),'Current picture differs');
  const frames=Array.from({length:context.plan.canvas.totalFrames},(_,i)=>i);
  assert.deepEqual(picture.frames.map(row=>row.frame),frames,'Incomplete original picture inventory');
  const groups=nativeCaptureBatches(frames,context.batchPlan.maximumFrames);
  assert.equal(picture.batches.length,groups.length);
  picture.batches.forEach((batch,index)=>verifyBatch(batch,groups[index],index));
}

function verifyBatch(batch, frames, index) {
  assert.equal(batch.index,index);assert.deepEqual(batch.frames,frames);
  assert.equal(batch.status,'captured-and-disposed');assert.equal(batch.transport.errors,0);
  for(const key of ['sessionClosed','browserPoolDrained','serverClosed','mediaGuardDisposed'])assert.equal(batch[key],true);
  assert.equal(batch.originalMedia?.status,'original-payloads-suppressed');
  assert.equal(batch.originalMedia?.disposed,true);
  assert.deepEqual(batch.originalMedia?.unexpectedMedia,[]);
  assert.deepEqual(batch.originalMedia?.requestErrors,[]);
  assert.ok(batch.originalMedia?.contract?.length>0,'Original media contract is absent');
  for(const row of batch.originalMedia.contract){
    assert.equal(row.receivedDataBytes,0);assert.equal(row.receivedEncodedBytes,0);
  }
}

function verifyRow(context, row, root) {
  const expected=path.join(root,'batched-native-render/frames',`frame_${String(row.frame).padStart(6,'0')}.jpg`);
  assert.equal(row.path,expected);
  assert.equal(fs.realpathSync(row.path),expected,'Forward screenshot path escaped its recorded directory');
  assert.equal(row.sha256,nativeCaptureHash(row.path),'Retained forward screenshot changed');
  assert.equal(row.time,row.frame/context.rate);
  assert.equal(row.forwardQc?.typography?.status,'passed','Required forward frame was not checked');
  assert.match(row.forwardQc.typography.observedSha256,/^[a-f0-9]{64}$/);
  assert.ok(Array.isArray(row.forwardQc.visualState),'Forward visual state is missing');
  const active=context.lookup.getActiveFramePayloads(row.time);
  const payload=[...active].map(([id,value])=>({id,frameIndex:value.frameIndex,
    sha256:nativeCaptureHash(value.framePath),path:value.framePath}));
  assert.deepEqual(row.payload,payload,'Current source frames differ from retained forward capture');
}

/** Absence selects legacy replay; present but invalid evidence always fails. */
export function reuseNativeForwardQc(context, points) {
  const root=context.request.pictureDonor??context.request.output;
  const file=path.join(root,'batched-picture.json');
  if(!fs.existsSync(file)){
    assert.ok(!context.request.pictureDonor,'Validated picture donor receipt is missing');
    return null;
  }
  const {sha256,value:picture}=readReceipt(file);
  if(!Object.hasOwn(picture,'forwardQc'))return null;
  if(context.request.pictureDonor)assert.equal(context.request.pins[file],sha256,'Donor forward receipt is not pinned');
  verifyPicture(context,picture,root,points);
  const selected=points.map(frame=>picture.frames[frame]);
  for(const row of selected)verifyRow(context,row,root);
  assert.equal(readReceipt(file).sha256,sha256,'Forward receipt changed during verification');
  if(context.batchPlan.maximumFrames===1)return {frames:null,
    evidence:{receipt:file,sha256,reason:'Single-frame sessions cannot fit a captured reverse seed; use full replay.'}};
  const frames=selected.map((row,index)=>{
    const {forwardQc,...captured}=row,destination=path.join(context.work,`pose-${index}.jpg`);
    fs.copyFileSync(row.path,destination,fs.constants.COPYFILE_EXCL);
    assert.equal(nativeCaptureHash(destination),row.sha256,'Copied forward image changed');
    return {...captured,path:destination,sourcePath:row.path,repeat:false,byteIdentical:null,
      ...forwardQc,origin:'retained-picture-forward-check'};
  });
  return {frames,evidence:{receipt:file,sha256,frameCount:frames.length,
    scope:'Render-observed forward checks; independent reverse replay. No second forward replay.'}};
}

/** Keep generated receipts compatible with the existing bounded cold reader. */
export function writeNativePictureReceipt(file, receipt) {
  const bytes=JSON.stringify(receipt,null,2);
  assert.ok(Buffer.byteLength(bytes)<=MAX_RECEIPT_BYTES,'Native picture receipt exceeds its 32 MiB read bound');
  fs.writeFileSync(file,bytes,{flag:'wx'});
}
