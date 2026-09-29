/** Version-2 shared source-frame entries: admitted only by a digest of their actual frame bytes.
 *
 * A v2 entry is `entries-v2/<key>/`: the SDK completion marker, the publication record and the exact
 * consecutive `frame_NNNNN.png` files, every one a regular file with a single link, so the entry alone
 * owns its bytes and its recorded size is exact. The record binds the content key, the frame count,
 * the byte totals and a SHA-256 over every frame's name, size and bytes in order. Admission rehashes
 * every frame through a no-follow descriptor, or, later in the same attempt, accepts that attempt's
 * own record of such a hash while every identity it covered holds; a symlinked, hard-linked,
 * truncated, replaced, unreadable or otherwise inconsistent entry is refused and never served.
 *
 * Version-1 entries (`entries/<key>/`) never bound their frame bytes, so they are untrusted: this route
 * never reads, adopts, rewrites or upgrades one. The next publisher regenerates the content as v2
 * beside it; collection removes the v1 directory only while no live lease names its key. A refused v2
 * entry leaves the served path only into quarantine, kept with its reason
 * (`native_source_store_publisher.mjs` decides when that is safe).
 */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash,randomUUID} from 'node:crypto';
import {STORE_INTERNALS,SourceStoreEntryRefused,storeKey} from './native_source_store.mjs';

/** Record version of trusted entries; a record of any other version is refused. */
export const ENTRY_SCHEMA_VERSION=2;
/** SHA-256 over `name\nsize\n` followed by the bytes of every frame, in frame order. */
export const FRAME_DIGEST_SCHEME='sniper-frame-sequence-v1';
/** The reason and time kept beside each quarantined entry. */
export const QUARANTINE_NOTE='refusal.json';
const {RECORD,MARKER,FRAME,KEY,writeAtomic,readRecord,realDirectory}=STORE_INTERNALS;
const HASH_CHUNK_BYTES=4*1024*1024,RACY_MARGIN_NS=2_000_000_000n,UNREADABLE=new Set(['EACCES','EPERM','EIO']);

const frameName=index=>`frame_${String(index).padStart(5,'0')}.png`;
const identityOf=stat=>`${stat.dev}:${stat.ino}:${stat.size}:${stat.mtimeNs}:${stat.ctimeNs}:${stat.nlink}`;
/** Replacing the entry directory, or adding, removing or renaming anything inside it, changes this. */
const directoryIdentityOf=stat=>`${stat.dev}:${stat.ino}:${stat.birthtimeNs}:${stat.mtimeNs}:${stat.ctimeNs}`;
const refuse=(key, reason)=>{throw new SourceStoreEntryRefused(key,reason);};

/** A permission or I/O failure refuses the entry (so it can be quarantined) instead of wedging its key. */
function unreadable(key, name, error) {
  if(UNREADABLE.has(error?.code))refuse(key,`${name} is unreadable (${error.code})`);
  throw error;
}

/** The entry directory's current identity, or null when no entry is published at the key. */
export function entryDirectoryIdentity(store, key) {
  const stat=fs.lstatSync(path.join(store.entriesV2,key),{bigint:true,throwIfNoEntry:false});
  return stat?directoryIdentityOf(stat):null;
}

/** Every file must be the marker, the record or one exact consecutive frame. */
function frameInventory(directory, frames, allowRecord) {
  const names=fs.readdirSync(directory),frameNames=names.filter(name=>FRAME.test(name)).sort();
  assert.ok(names.every(name=>FRAME.test(name)||name===MARKER||(allowRecord&&name===RECORD)),
    `Unexpected artifact in native source frames: ${directory}`);
  assert.ok(names.includes(MARKER),'Native source frames lack the SDK completion marker');
  assert.equal(frameNames.length,frames,'Incomplete native source cache');
  frameNames.forEach((name,index)=>assert.equal(name,frameName(index+1),'Native source cache has a frame gap'));
  return frameNames;
}

/** Lstat without following links: a regular file this entry alone links. */
function ownedFile(key, file) {
  const name=path.basename(file);let stat;
  try{stat=fs.lstatSync(file,{bigint:true,throwIfNoEntry:false});}catch(error){unreadable(key,name,error);}
  if(!stat)refuse(key,`${name} is missing`);
  if(stat.isSymbolicLink())refuse(key,`${name} is a symbolic link`);
  if(!stat.isFile())refuse(key,`${name} is not a regular file`);
  if(stat.nlink!==1n)refuse(key,`${name} is hard-linked (${stat.nlink} links)`);
  return stat;
}

function recordOf(key, dir, frames) {
  const file=path.join(dir,RECORD);
  if(!fs.lstatSync(file,{throwIfNoEntry:false}))refuse(key,'it has no publication record; it is preserved, never adopted or overwritten');
  ownedFile(key,file);
  let record;
  try{record=readRecord(file);}catch(error){refuse(key,`its publication record is unreadable: ${error.message}`);}
  if(record.schemaVersion!==ENTRY_SCHEMA_VERSION)refuse(key,`record schemaVersion ${record.schemaVersion} is not ${ENTRY_SCHEMA_VERSION}`);
  if(record.key!==key||storeKey(record.blob)!==key)refuse(key,'Source store entry record differs from its key');
  if(record.frames!==frames)refuse(key,`record has ${record.frames} frames where ${frames} are wanted`);
  const digest=record.frameDigest;
  if(digest?.algorithm!=='sha256'||digest.scheme!==FRAME_DIGEST_SCHEME||!KEY.test(digest.value??''))refuse(key,'record lacks a valid frame digest');
  if(![record.markerBytes,record.frameBytes].every(Number.isSafeInteger)||record.bytes!==record.markerBytes+record.frameBytes)
    refuse(key,'record byte totals are malformed');
  return record;
}

function inventory(key, dir, frames) {
  try{return frameInventory(dir,frames,true);}
  catch(error){if(error instanceof assert.AssertionError)refuse(key,error.message);unreadable(key,'the entry directory',error);}
}

/** Structure only (no hashing): record, inventory, single-link regular files, sizes equal the record. */
function presentEntry(store, key, frames) {
  const dir=path.join(store.entriesV2,key),stat=fs.lstatSync(dir,{bigint:true,throwIfNoEntry:false});
  if(!stat)return null;
  if(stat.isSymbolicLink()||!stat.isDirectory())refuse(key,'Source store entry is not a real directory');
  const record=recordOf(key,dir,frames),names=inventory(key,dir,frames),marker=ownedFile(key,path.join(dir,MARKER));
  const stats=names.map(name=>ownedFile(key,path.join(dir,name)));
  const frameBytes=stats.reduce((sum,row)=>sum+row.size,0n);
  if(marker.size!==BigInt(record.markerBytes)||frameBytes!==BigInt(record.frameBytes))
    refuse(key,`entry holds ${frameBytes} frame bytes where the record has ${record.frameBytes} (truncated or replaced frames)`);
  return {dir,names,record,stats,directory:stat,directoryIdentity:directoryIdentityOf(stat)};
}

/** Hash one frame through a no-follow descriptor; its identity must hold for the whole read. */
function hashFrame(key, file, sink) {
  const name=path.basename(file);let fd;
  try{fd=fs.openSync(file,fs.constants.O_RDONLY|fs.constants.O_NOFOLLOW);}
  catch(error){if(['ELOOP','ENOENT'].includes(error.code))refuse(key,`${name} is a symbolic link or missing`);unreadable(key,name,error);}
  try{
    const before=fs.fstatSync(fd,{bigint:true});let read=0n,count;
    if(!before.isFile()||before.nlink!==1n)refuse(key,`${name} is not a regular file with one link`);
    sink.digest.update(`${name}\n${before.size}\n`);
    while((count=fs.readSync(fd,sink.buffer,0,sink.buffer.length,null))>0){sink.digest.update(sink.buffer.subarray(0,count));read+=BigInt(count);}
    const after=fs.fstatSync(fd,{bigint:true}),current=fs.lstatSync(file,{bigint:true,throwIfNoEntry:false});
    if(read!==before.size||identityOf(after)!==identityOf(before)||!current||identityOf(current)!==identityOf(before))
      refuse(key,`${name} changed while it was hashed`);
    return {identity:identityOf(before),size:before.size};
  }catch(error){
    if(error instanceof SourceStoreEntryRefused)throw error;
    return unreadable(key,name,error);
  }finally{fs.closeSync(fd);}
}

/** The frame digest: SHA-256 over `name\nsize\n` and the bytes of every frame, in frame order. */
function hashFrames(key, dir, names) {
  const sink={digest:createHash('sha256'),buffer:Buffer.allocUnsafe(HASH_CHUNK_BYTES)};
  const rows=names.map(name=>hashFrame(key,path.join(dir,name),sink));
  return {value:sink.digest.digest('hex'),identities:rows.map(row=>row.identity),
    frameBytes:Number(rows.reduce((sum,row)=>sum+row.size,0n))};
}

function admitted(present, identities, proof) {
  return {dir:present.dir,names:present.names,record:present.record,frameDigest:present.record.frameDigest.value,identities,
    directoryIdentity:present.directoryIdentity,...proof,
    framePaths:new Map(present.names.map((name,index)=>[index,path.join(present.dir,name)]))};
}

/** A full hash earlier in this attempt still speaks for the entry only when nothing it hashed can have
 * changed since: the same frame digest, directory identity and every frame identity (with link count),
 * and every file last changed at least the racy margin before that hash began (the rule of
 * `native_digest_memo.py`), so a rewrite inside one timestamp tick cannot hide. */
function priorStillHolds(present, identities, prior) {
  if(prior?.frameDigest!==present.record.frameDigest.value||prior.directoryIdentity!==present.directoryIdentity)return false;
  if(!Array.isArray(prior.identities)||prior.identities.length!==identities.length)return false;
  if(identities.some((value,index)=>value!==prior.identities[index])||!Number.isSafeInteger(prior.hashStartedMs))return false;
  const newest=[present.directory,...present.stats].reduce((max,stat)=>[stat.mtimeNs,stat.ctimeNs,max].reduce((a,b)=>a>b?a:b),0n);
  return newest+RACY_MARGIN_NS<=BigInt(prior.hashStartedMs)*1_000_000n;
}

function sameIdentities(key, present, identities) {
  present.stats.forEach((stat,index)=>{
    if(identityOf(stat)!==identities[index])refuse(key,`${present.names[index]} changed after it was hashed`);
  });
}

/** Admission: the exact structure plus every frame's bytes equal to the published frame digest.
 *
 * `prior` is this attempt's own record of an earlier full hash (`native_source_store_publisher.mjs`);
 * the hash is skipped only when `priorStillHolds`. An entry removed while a caller reads it is simply
 * missing: collection removes only unleased entries, and quarantine can remove one a leased reader
 * admitted but has not yet linked, which that reader detects at its final re-check and re-admits.
 * Any other inconsistency is a SourceStoreEntryRefused.
 */
export function readStoreEntry(store, key, frames, prior=null) {
  assert.match(key,KEY,'Invalid source store key');
  try{
    const present=presentEntry(store,key,frames);
    if(!present)return null;
    const identities=present.stats.map(identityOf);
    if(priorStillHolds(present,identities,prior))return admitted(present,identities,{admittedBy:'attempt-ledger',hashStartedMs:prior.hashStartedMs});
    const hashStartedMs=Date.now(),hashed=hashFrames(key,present.dir,present.names);
    if(hashed.value!==present.record.frameDigest.value)refuse(key,'frame bytes differ from the published frame digest');
    sameIdentities(key,present,hashed.identities);
    return admitted(present,hashed.identities,{admittedBy:'full-hash',hashStartedMs});
  }catch(error){
    if(!fs.lstatSync(path.join(store.entriesV2,key),{throwIfNoEntry:false}))return null;
    throw error;
  }
}

/** Structure without hashing, for projections that never serve frames (Long disk budgeting). */
export function inspectStoreEntry(store, key, frames) {
  try{return {state:presentEntry(store,key,frames)?'present':'missing'};}
  catch(error){
    if(!(error instanceof SourceStoreEntryRefused))throw error;
    return fs.lstatSync(path.join(store.entriesV2,key),{throwIfNoEntry:false})?{state:'refused',reason:error.reason}:{state:'missing'};
  }
}

function recordedFrames(store, key) {
  try{return readRecord(path.join(store.entriesV2,key,RECORD)).frames;}
  catch(error){if(error.code==='ENOENT'||error instanceof SyntaxError||error instanceof assert.AssertionError)return -1;throw error;}
}

/** Collection's structural view (no hashing): a valid entry's exact bytes, every file and the record
 * included, all single-link regular files; otherwise the specific refusal. */
export function measureStoreEntry(store, key) {
  try{
    if(!KEY.test(key))refuse(key,'the entry name is not a content key');
    const present=presentEntry(store,key,recordedFrames(store,key));
    if(!present)return {state:'missing'};
    const record=fs.lstatSync(path.join(present.dir,RECORD));
    return {state:'present',dir:present.dir,bytes:present.record.bytes+record.size,lastUsedMs:record.mtimeMs};
  }catch(error){
    if(!(error instanceof SourceStoreEntryRefused))throw error;
    return fs.lstatSync(path.join(store.entriesV2,key),{throwIfNoEntry:false})?{state:'refused',reason:error.reason}:{state:'missing'};
  }
}

/** Cheap re-check before use: the entry directory and every admitted frame keep the identity they had
 * when hashed, so an added, removed, renamed, replaced or rewritten file is caught. */
export function recheckStoreEntry(key, entry) {
  const directory=fs.lstatSync(entry.dir,{bigint:true,throwIfNoEntry:false});
  if(!directory||directoryIdentityOf(directory)!==entry.directoryIdentity)refuse(key,'the entry directory changed after admission');
  entry.names.forEach((name,index)=>{
    const stat=fs.lstatSync(path.join(entry.dir,name),{bigint:true,throwIfNoEntry:false});
    if(!stat||identityOf(stat)!==entry.identities[index])refuse(key,`${name} changed after admission`);
  });
}

/** SDK superset slicing hard-links member frames; copy those so the entry owns its bytes. Frames
 * become read-only; a symbolic link or other non-file in SDK output refuses publication. */
function ownOutput(key, directory, names) {
  let materialized=0;
  for(const name of [MARKER,...names]){
    const file=path.join(directory,name),stat=fs.lstatSync(file);
    if(stat.isSymbolicLink()||!stat.isFile())refuse(key,`SDK output ${name} is not a regular file; publication refused`);
    if(stat.nlink>1){
      const copy=`${file}.${randomUUID()}.materializing`;
      fs.copyFileSync(file,copy,fs.constants.COPYFILE_EXCL);fs.renameSync(copy,file);materialized++;
    }
    if(name!==MARKER)fs.chmodSync(file,0o444);
  }
  return materialized;
}

/** Bind one verified SDK directory to its frame digest and move it into place under the held lock. */
export function publishStoreEntry(store, publication) {
  const {key,blob,frames,directory,publisher}=publication;
  assert.equal(storeKey(blob),key,'Source store publication key differs from its identity');
  const stat=fs.lstatSync(directory);
  assert.ok(stat.isDirectory()&&!stat.isSymbolicLink(),'SDK did not publish a real directory into this job view');
  const names=frameInventory(directory,frames,false),materializedLinks=ownOutput(key,directory,names);
  const hashStartedMs=Date.now(),hashed=hashFrames(key,directory,names),markerBytes=Number(fs.lstatSync(path.join(directory,MARKER)).size);
  fs.writeFileSync(path.join(directory,RECORD),JSON.stringify({schemaVersion:ENTRY_SCHEMA_VERSION,key,blob,frames,markerBytes,
    frameBytes:hashed.frameBytes,bytes:markerBytes+hashed.frameBytes,frameDigest:{algorithm:'sha256',scheme:FRAME_DIGEST_SCHEME,
      value:hashed.value},materializedLinks,publisher,publishedAt:new Date().toISOString()},null,2),{flag:'wx',mode:0o600});
  const target=path.join(store.entriesV2,key);
  assert.ok(!fs.lstatSync(target,{throwIfNoEntry:false}),'Source store entry appeared while its publication lock was held');
  fs.renameSync(directory,target);
  const present=presentEntry(store,key,frames);
  sameIdentities(key,present,hashed.identities);
  return admitted(present,hashed.identities,{admittedBy:'publication',hashStartedMs});
}

/** Move a refused v2 entry out of the served path, kept with its reason. The caller holds the
 * maintenance lock exclusively and has proved that no other live reader uses the entry. */
export function moveToQuarantine(store, refusal, by) {
  const dir=path.join(store.entriesV2,refusal.key);
  if(!fs.lstatSync(dir,{throwIfNoEntry:false}))return null;
  const holder=realDirectory(path.join(store.quarantine,`${refusal.key}.${randomUUID()}`));
  writeAtomic(path.join(holder,QUARANTINE_NOTE),{schemaVersion:1,key:refusal.key,reason:refusal.reason,by,
    quarantinedAt:new Date().toISOString()});
  fs.renameSync(dir,path.join(holder,'entry'));
  return holder;
}
