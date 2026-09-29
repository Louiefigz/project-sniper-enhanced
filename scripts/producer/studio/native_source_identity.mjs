/** Exact source identities: staged-file evidence, the SDK path key and the content-bound store key. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {NATIVE_SOURCE_FRAME_CLOCK,nativeSourceFrameCount,nativeSourceFrameSelection} from './runtime/frame-source-transport.mjs';
import {storeKey} from './native_source_store.mjs';

export const SOURCE_FRAMES_SCHEMA='sniper-source-frames-v1';
const OWNER_CLEANUP_RESERVE_MS=30000;

/** Bind per-run memoization to a canonical file and precise mutation/replacement evidence. */
export function nativeSourceFileIdentity(source) {
  const file=fs.realpathSync(source),stat=fs.statSync(file,{bigint:true});
  assert.ok(stat.isFile(),'Native source inspection requires a regular file');
  return {file,device:stat.dev,inode:stat.ino,size:stat.size,modified:stat.mtimeNs,changed:stat.ctimeNs};
}

/** Reuse exact SDK metadata within this preparation; never reuse a changed source. */
export async function nativeSourceMetadata(context, source) {
  const identity=nativeSourceFileIdentity(source);
  context.sourceMetadata??=new Map();
  let row=context.sourceMetadata.get(identity.file);
  if(row)assert.deepEqual(identity,row.identity,'Native source changed after metadata inspection');
  else {
    const metadata=await context.sdk.extractMediaMetadata(source);
    assert.deepEqual(nativeSourceFileIdentity(source),identity,'Native source changed during metadata inspection');
    row={identity,metadata:structuredClone(metadata)};context.sourceMetadata.set(identity.file,row);
  }
  return structuredClone(row.metadata);
}

/** Stream exact source bytes with bounded reads; one full read per unchanged file per process. */
export async function nativeSourceContentHash(context, file) {
  const identity=nativeSourceFileIdentity(file);
  const inspected=context.sourceMetadata?.get(identity.file);
  if(inspected)assert.deepEqual(identity,inspected.identity,'Native source changed after metadata inspection');
  context.sourceHashes??=new Map();
  const previous=context.sourceHashes.get(identity.file);
  if(previous){
    assert.deepEqual(identity,previous.identity,'Native source changed after hashing');
    return previous.sha256;
  }
  const digest=createHash('sha256');
  for await(const chunk of fs.createReadStream(identity.file,{highWaterMark:1024*1024}))digest.update(chunk);
  assert.deepEqual(nativeSourceFileIdentity(file),identity,'Native source changed during hashing');
  const sha256=digest.digest('hex');context.sourceHashes.set(identity.file,{identity,sha256});
  return sha256;
}

/** The SDK's own v4 path key: names this job's private view entry and legacy root entries. */
export function nativeSourceCacheIdentity(context, video, root=context.request.cache, transform=NATIVE_SOURCE_FRAME_CLOCK) {
  const source=path.resolve(context.project,video.src),stat=fs.statSync(source),{num,den}=context.fps;
  const selection=nativeSourceFrameSelection(video.nativeSourceFrameIndices);
  if(selection)transform+=`+${selection.transform}`;
  const keyBlob={p:source,m:Math.floor(stat.mtimeMs),s:stat.size,ms:video.mediaStart,
    d:video.end-video.start,f:den===1?String(num):`${num}/${den}`,fmt:'png',t:transform};
  const key=createHash('sha256').update(JSON.stringify(keyBlob)).digest('hex');
  return {source,keyBlob,entry:path.join(root,'hfcache-v4-'+key.slice(0,16))};
}

/** Legacy path-keyed SDK entries: marker plus every exact consecutive, regular (never symlinked) frame.
 *
 * These are kept out of the trusted shared-store route: acquisition never reads, adopts or verifies
 * a legacy root entry (or a version-1 store entry) and regenerates the content as a digest-bound v2
 * entry instead. The only production reader is the alias recovery tool, which hashes every frame it
 * uses itself (`source_cache_alias.mjs`); SDK-internal superset hard links are legal here.
 */
export function nativeSourceCacheEntry(context, video, root=context.request.cache) {
  const identity=nativeSourceCacheIdentity(context,video,root),{entry,keyBlob}=identity;
  assert.ok(fs.existsSync(path.join(entry,'.hf-complete')),`Exact native source frame cache missing: ${JSON.stringify(keyBlob)}`);
  const names=fs.readdirSync(entry).filter(name=>/^frame_\d{5}\.png$/.test(name)).sort();
  assert.equal(names.length,nativeSourceFrameCount(video.end-video.start,context.rate),'Incomplete native source cache');
  const framePaths=new Map(names.map((name,index)=>{
    assert.equal(name,`frame_${String(index+1).padStart(5,'0')}.png`,'Native source cache has a frame gap');
    assert.ok(fs.lstatSync(path.join(entry,name)).isFile(),`Legacy native source frame is not a regular file: ${name}`);
    return [index,path.join(entry,name)];
  }));
  return {...identity,names,framePaths};
}

/** The exact executable digest pinned at export admission, under its given or canonical path. */
function toolDigest(request, name) {
  const file=request.tools?.[name];
  assert.equal(typeof file,'string',`Content-bound source frames require the ${name} tool`);
  let digest=request.pins?.[file];
  if(digest===undefined&&path.isAbsolute(file)&&fs.existsSync(file))digest=request.pins?.[fs.realpathSync(file)];
  assert.match(digest??'',/^[a-f0-9]{64}$/,`Content-bound source frames require the admitted ${name} digest`);
  return digest;
}

/** Admitted bytes plus every setting that changes a decoded pixel; never the staged path or mtime.
 *
 * Trust boundary: `request.pins[source]` is the export's own full-read digest, re-verified by the
 * owner immediately before this child launched. Hits trust it; capture compares its existing full
 * read against it. Publication additionally requires an unchanged file identity across the SDK
 * decode and a full-read digest equal to this value before an entry becomes shared.
 */
export function nativeSourceContentIdentity(context, video, root=context.sourceView??context.request.cache,
  transform=NATIVE_SOURCE_FRAME_CLOCK) {
  const identity=nativeSourceCacheIdentity(context,video,root,transform),{keyBlob}=identity;
  const digest=context.request.pins?.[identity.source];
  assert.match(digest??'',/^[a-f0-9]{64}$/,'Content-bound source frames require the admitted source digest');
  assert.match(context.runtimeLibrarySha256??'',/^[a-f0-9]{64}$/,'Content-bound source frames require the runtime identity');
  const blob={schema:SOURCE_FRAMES_SCHEMA,source:digest,mediaStart:keyBlob.ms,duration:keyBlob.d,fps:keyBlob.f,
    format:keyBlob.fmt,transform:keyBlob.t,geometry:'original',
    extractor:{library:context.runtimeLibrarySha256,ffmpeg:toolDigest(context.request,'ffmpeg'),
      ffprobe:toolDigest(context.request,'ffprobe')}};
  return {...identity,pathName:path.basename(identity.entry),contentBlob:blob,contentKey:storeKey(blob),
    frames:nativeSourceFrameCount(video.end-video.start,context.rate)};
}

/** The SDK's composition-wide colour negotiation, reproduced exactly for its cache transform.
 *
 * Any HDR source makes every SDR source convert to the dominant transfer (PQ if any source is PQ,
 * otherwise HLG); the SDK then keys those entries `<clock>+sdr2hdr-<transfer>`. Callers still
 * require the SDK's actual output name to equal the predicted one, so a drift fails closed.
 */
export function negotiatedTransforms(sdk, colorSpaces) {
  assert.equal(typeof sdk.isHdrColorSpace,'function','Pinned SDK lacks exact HDR classification');
  const hdr=colorSpaces.map(colorSpace=>sdk.isHdrColorSpace(colorSpace));
  if(!hdr.some(Boolean))return colorSpaces.map(()=>NATIVE_SOURCE_FRAME_CLOCK);
  const dominant=colorSpaces.some((colorSpace,index)=>hdr[index]&&colorSpace?.colorTransfer==='smpte2084')?'pq':'hlg';
  return hdr.map(isHdr=>isHdr?NATIVE_SOURCE_FRAME_CLOCK:`${NATIVE_SOURCE_FRAME_CLOCK}+sdr2hdr-${dominant}`);
}

/** Hook point for the production budget: waits end at the supervising owner's own deadline. */
export function sourceCacheUntilMs(environment=process.env) {
  const file=environment.SNIPER_NATIVE_EXPORT_OWNER;
  assert.ok(typeof file==='string'&&path.isAbsolute(file),'Source frame waits require the supervising owner deadline');
  const owner=JSON.parse(fs.readFileSync(file,'utf8')),started=Date.parse(owner.startedAt);
  assert.ok(Number.isFinite(started)&&Number.isFinite(owner.runDeadlineSeconds)&&owner.runDeadlineSeconds>0,
    'Supervising owner has no finite deadline');
  return started+owner.runDeadlineSeconds*1000-OWNER_CLEANUP_RESERVE_MS;
}
