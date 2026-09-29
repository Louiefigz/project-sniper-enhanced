/** One acquisition protocol for Short and Long: reader lease, exact ownership, SDK decode, publication.
 *
 * The SDK receives only this attempt's private view as its cache root: complete store entries are
 * symlinked under their SDK path-keyed names, and the SDK extracts (and publishes) only the misses
 * this job exclusively owns. Those directories are verified against the admitted source bytes, bound to
 * a digest of their own frame bytes and atomically moved into the shared store, so the SDK never
 * publishes into or collects shared state. Every entry handed to capture or render was admitted by
 * that frame digest in this acquisition (`native_source_store_entry.mjs`).
 */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {openSourceStore,storeViewPath,storeDeadline,createStoreLease,linkStoreView,holdStoreOwner,
  holderProgressFrames} from './native_source_store.mjs';
import {publishStoreEntry} from './native_source_store_entry.mjs';
import {acquireStoreEntries} from './native_source_store_publisher.mjs';
import {collectStoreGarbage,collectionDue} from './native_source_store_collection.mjs';
import {nativeSourceFileIdentity,nativeSourceContentHash,nativeSourceContentIdentity,nativeSourceMetadata,
  negotiatedTransforms,sourceCacheUntilMs} from './native_source_identity.mjs';

const processOwners=new Map();
// Collection after a publication is housekeeping: it may spend at most this long, and never the
// last reserve of the caller's deadline; leftover trash is removed by the next collection.
const COLLECTION_MAX_MS=30000,COLLECTION_RESERVE_MS=60000;

/** A reader always pins its own lifetime; an export lease also retains frames between children. */
async function acquireLeases(context, plan, deadline) {
  const {store,view,wanted}=plan,keys=wanted.map(row=>row.key);
  if(!processOwners.has(store.root))processOwners.set(store.root,holdStoreOwner(store));
  const reader=await createStoreLease(store,{owner:processOwners.get(store.root).file,view,keys},deadline);
  const owner=context.request.sourceStoreOwner;
  if(owner===undefined)return {reader,retention:reader};
  assert.ok(typeof owner==='string'&&path.dirname(owner)===store.owners,'Source store owner is outside this cache');
  const retention=await createStoreLease(store,{owner,view,keys},deadline);
  return {reader,retention};
}

/** Validate every compiled video, negotiate colour exactly as the SDK will, and deduplicate by content. */
export async function openNativeSourcePlan(context, validate) {
  const store=openSourceStore(context.request.cache),videos=context.result.composition.videos;
  context.sourceView=storeViewPath(store,context.sourceViewIdentity??context.work);
  for(const video of videos)validate(video);
  const colorSpaces=[];
  for(const video of videos)colorSpaces.push((await nativeSourceMetadata(context,path.resolve(context.project,video.src))).colorSpace??null);
  const transforms=negotiatedTransforms(context.sdk,colorSpaces);
  const rows=videos.map((video,index)=>({video,transform:transforms[index],
    ...nativeSourceContentIdentity(context,video,context.sourceView,transforms[index])}));
  const wanted=new Map();
  for(const row of rows)if(!wanted.has(row.contentKey))
    wanted.set(row.contentKey,{key:row.contentKey,blob:row.contentBlob,frames:row.frames,row});
  return {store,view:context.sourceView,rows,wanted:[...wanted.values()],sources:new Map()};
}

/** Remove only this attempt's own stale private output at one SDK name. */
function clearViewName(view, pathName) {
  const file=path.join(view,pathName),stat=fs.lstatSync(file,{throwIfNoEntry:false});
  if(!stat)return false;
  if(stat.isSymbolicLink())fs.unlinkSync(file);
  else fs.rmSync(file,{recursive:true});
  return true;
}

/** Point one SDK name at its store entry, replacing a duplicate SDK directory for the same bytes. */
function settleViewName(view, pathName, target) {
  const file=path.join(view,pathName),stat=fs.lstatSync(file,{throwIfNoEntry:false});
  if(stat&&(!stat.isSymbolicLink()||fs.readlinkSync(file)!==target))clearViewName(view,pathName);
  linkStoreView(view,pathName,target);
}

/** Before the SDK runs: every non-owned entry is a hit, every owned name starts empty. */
function prepareView(plan, owned, receipt) {
  const ownedKeys=new Set(owned.map(row=>row.key));
  for(const row of plan.rows){
    if(!ownedKeys.has(row.contentKey)){settleViewName(plan.view,row.pathName,path.join(plan.store.entriesV2,row.contentKey));continue;}
    if(clearViewName(plan.view,row.pathName))receipt.staleViewNamesRemoved++;
  }
  for(const row of plan.rows)plan.sources.set(row.source,nativeSourceFileIdentity(row.source));
}

/** Share frames only when the decoded file still has the admitted digest and never changed; returns
 * the published entry, already bound to its frame digest. */
async function publishNative(context, plan, owned) {
  const {row}=owned,before=plan.sources.get(row.source);
  assert.ok(before,'Source identity was not captured before extraction');
  assert.deepEqual(nativeSourceFileIdentity(row.source),before,'Native source changed during extraction');
  const sha256=await nativeSourceContentHash(context,row.source);
  assert.deepEqual(nativeSourceFileIdentity(row.source),before,'Native source changed during extraction');
  assert.equal(sha256,owned.blob.source,'Decoded source bytes differ from the admitted digest; publication refused');
  const entry=publishStoreEntry(plan.store,{key:owned.key,blob:owned.blob,frames:owned.frames,
    directory:path.join(plan.view,row.pathName),publisher:{pid:process.pid,attempt:context.request.output,videoId:row.video.id}});
  linkStoreView(plan.view,row.pathName,entry.dir);
  return entry;
}

/** Deadline-bounded housekeeping; it never consumes the caller's final reserve. */
function collect(store, budget, published, deadline) {
  if(!collectionDue(store,published))return {status:'not-due'};
  const until=Math.min(deadline-COLLECTION_RESERVE_MS,performance.now()+COLLECTION_MAX_MS);
  if(until<=performance.now())return {status:'skipped-caller-deadline-reserve'};
  try{return collectStoreGarbage(store,{maxBytes:typeof budget==='function'?budget():budget,until});}
  catch(error){return {status:'failed',error:String(error?.message??error)};}
}

/** Waiting reports the awaited holders' real decode progress, cumulatively, never a heartbeat.
 * A holder publishing one entry moves its frames out of its view; that drop is not progress lost. */
function waitReporter() {
  let last=0,cumulative=0;
  return holders=>{
    const frames=holderProgressFrames(holders);
    if(frames>last){cumulative+=frames-last;console.log(`SNIPER_PROGRESS source-publication-wait ${cumulative}`);}
    last=frames;
  };
}

/** Lease, acquire and link every compiled video; `extract` is null when only existing entries may be used. */
export async function acquireNativeSources(context, plan, options) {
  const {store,view,rows,wanted}=plan,{receipt}=options,deadline=storeDeadline(sourceCacheUntilMs());
  receipt.staleViewNamesRemoved=0;
  const {reader,retention:lease}=await acquireLeases(context,plan,deadline);
  Object.assign(receipt,{store:store.root,view,lease:{id:lease.id,owner:lease.owner},
    readerLease:{id:reader.id,owner:reader.owner},status:'acquiring'});
  options.persist();
  const entries=await acquireStoreEntries(store,wanted,{deadline,holder:{pid:process.pid,view,attempt:context.request.output},
    extract:options.extract&&(async owned=>{prepareView(plan,owned,receipt);await options.extract(owned);}),
    publish:owned=>publishNative(context,plan,owned),onWait:waitReporter()});
  context.sourceEntries=new Map(rows.map(row=>{
    const entry=entries.get(row.contentKey);settleViewName(view,row.pathName,entry.dir);
    return [row.video.id,{...row,entry:entry.dir,names:entry.names,framePaths:entry.framePaths,frameDigest:entry.frameDigest,
      admittedBy:entry.admittedBy,outcome:entry.outcome,waitedMs:entry.waitedMs,replaced:entry.replaced,
      untrustedVersion1Kept:entry.untrustedVersion1Kept}];
  }));
  receipt.entries=[...context.sourceEntries.values()].map(row=>({videoId:row.video.id,source:row.source,
    contentKey:row.contentKey,pathName:row.pathName,entry:row.entry,frames:row.frames,frameDigest:row.frameDigest,
    admittedBy:row.admittedBy,outcome:row.outcome,waitedMs:row.waitedMs,...(row.replaced?{replaced:row.replaced}:{}),
    ...(row.untrustedVersion1Kept?{untrustedVersion1Kept:row.untrustedVersion1Kept}:{})}));
  receipt.status='exact-source-caches-ready';
  receipt.collection=collect(store,options.collectBytes,receipt.entries.some(row=>row.outcome==='published-by-this-job'),deadline);
  options.persist();
  return context.sourceEntries;
}

/** Stable across repeated admissions of one attempt: no timings, waits, lease ids or collection; the
 * frame digest binds the evidence to the exact frame bytes admitted. */
export function stableSourceEvidence(receipt) {
  return {schemaVersion:receipt.schemaVersion,scope:receipt.scope,mode:receipt.mode,status:receipt.status,store:receipt.store,
    entries:receipt.entries.map(({videoId,source,contentKey,pathName,entry,frames,frameDigest})=>
      ({videoId,source,contentKey,pathName,entry,frames,frameDigest}))};
}
