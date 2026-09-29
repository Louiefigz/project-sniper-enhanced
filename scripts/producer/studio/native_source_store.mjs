/** Content-addressed native source frames shared safely by concurrent jobs.
 *
 * Layout under the admitted cache root (every directory canonical, private and real):
 *   sniper-source-store-v1/entries-v2/<key>/  trusted entries bound to a digest of their frame bytes
 *                                              (`native_source_store_entry.mjs`); one atomic rename each
 *   sniper-source-store-v1/entries/<key>/  version-1 entries: untrusted, never read, adopted or rewritten
 *   sniper-source-store-v1/quarantine/<id>/  refused entries moved out of the served path with the reason
 *   sniper-source-store-v1/locks/<key>.lock  kernel lock: exactly one live publisher per entry
 *   sniper-source-store-v1/owners/<id>.lock  kernel lock held by a live supervisor or process
 *   sniper-source-store-v1/leases/<id>.json  reader leases naming an owner lock, entries and a view
 *   sniper-source-store-v1/views/<attempt>/  private SDK cache roots: symlinks and SDK partials
 *   sniper-source-store-v1/maintenance.lock  shared while a lease is published, exclusive for collection
 * Locks use Darwin's flock-compatible open(2) flags, so a dead holder's lock is released by the
 * kernel; a recycled PID can never impersonate an owner. The SDK never publishes into, or collects,
 * the shared entries: it sees only a job's private view.
 */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash,randomUUID} from 'node:crypto';
import {setTimeout as sleep} from 'node:timers/promises';

export const SOURCE_STORE_NAME='sniper-source-store-v1';
/** Unleased entries are evicted only after this idle time, the SDK collector's existing floor. */
export const STORE_ENTRY_MIN_AGE_MS=60*60*1000;
export const STORE_COLLECTION_INTERVAL_MS=24*60*60*1000;
const O_SHLOCK=0x10,O_EXLOCK=0x20,POLL_MS=200,MAX_RECORD_BYTES=1024*1024;
const RECORD='.sniper-entry.json',MARKER='.hf-complete',FRAME=/^frame_\d{5}\.png$/;
const LEGACY=/^hfcache-v\d+-[0-9a-f]+$/,KEY=/^[a-f0-9]{64}$/;
/** Directory of the current trusted entry version; version-1 entries stay in `entries/`. */
export const STORE_ENTRY_DIRECTORY='entries-v2';

const lockFile=(store,key)=>path.join(store.locks,`${key}.lock`);
const holderFile=(store,key)=>path.join(store.locks,`${key}.holder.json`);

/** Sorted-key JSON: an identity never depends on object construction order. */
export function canonicalJson(value) {
  if(Array.isArray(value))return `[${value.map(canonicalJson).join(',')}]`;
  if(value&&typeof value==='object')return `{${Object.keys(value).sort()
    .map(key=>`${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(',')}}`;
  assert.ok(value!==undefined&&(typeof value!=='number'||Number.isFinite(value)),'Store identities need finite JSON values');
  return JSON.stringify(value);
}

/** A shared entry that must never be served: the key and a specific reason travel with the error. */
export class SourceStoreEntryRefused extends Error {
  constructor(key, reason) {
    super(`Source store entry ${key} is refused and never served: ${reason}`);
    Object.assign(this,{name:'SourceStoreEntryRefused',code:'SOURCE_STORE_ENTRY_REFUSED',key,reason});
  }
}

/** A refused entry that another live reader still links, so it could not be replaced before the caller
 * deadline. Distinct from a corrupt-entry failure: the entry stays in place for that reader. */
export class SourceStoreEntryHeld extends SourceStoreEntryRefused {
  constructor(key, reason) {
    super(key,reason);
    Object.assign(this,{name:'SourceStoreEntryHeld',code:'SOURCE_STORE_ENTRY_HELD'});
  }
}

export function storeKey(blob) {
  return createHash('sha256').update(canonicalJson(blob)).digest('hex');
}

function openFlags(mode, create) {
  assert.equal(process.platform,'darwin','The shared source store requires Darwin flock-compatible open locks');
  return fs.constants.O_RDWR|fs.constants.O_NOFOLLOW|fs.constants.O_NONBLOCK
    |(create?fs.constants.O_CREAT:0)|(mode==='ex'?O_EXLOCK:O_SHLOCK);
}

/** Take a kernel lock without blocking; a lock file replaced after open is never treated as held. */
export function tryStoreLock(file, mode, create=true) {
  let fd;
  try{fd=fs.openSync(file,openFlags(mode,create),0o600);}
  catch(error){if(['EAGAIN','EWOULDBLOCK'].includes(error.code))return null;throw error;}
  const held=fs.fstatSync(fd),current=fs.lstatSync(file,{throwIfNoEntry:false});
  if(current?.isFile()&&current.ino===held.ino&&current.dev===held.dev)return fd;
  fs.closeSync(fd);
  return null;
}

/** Convert the caller's absolute bound once; later checks use the monotonic clock. */
export function storeDeadline(untilMs) {
  assert.ok(Number.isFinite(untilMs),'Source store waits require an explicit caller deadline');
  return performance.now()+Math.max(0,untilMs-Date.now());
}

const remaining=deadline=>deadline-performance.now();

async function lockUntil(file, mode, deadline) {
  for(;;){
    const fd=tryStoreLock(file,mode);
    if(fd!==null||remaining(deadline)<=0)return fd;
    await sleep(Math.min(POLL_MS,Math.max(1,remaining(deadline))));
  }
}

function realDirectory(directory) {
  fs.mkdirSync(directory,{recursive:true,mode:0o700});
  const stat=fs.lstatSync(directory);
  assert.ok(stat.isDirectory()&&!stat.isSymbolicLink()&&fs.realpathSync(directory)===directory,
    `Source store directory must be canonical and real: ${directory}`);
  return directory;
}

/** Open (creating when absent) the store inside an admitted canonical cache root. */
export function openSourceStore(cacheRoot) {
  assert.ok(typeof cacheRoot==='string'&&path.isAbsolute(cacheRoot)&&fs.realpathSync(cacheRoot)===cacheRoot,
    'Source store cache root must be canonical');
  const root=realDirectory(path.join(cacheRoot,SOURCE_STORE_NAME)),store={cache:cacheRoot,root};
  for(const name of ['entries','locks','owners','leases','views','trash','quarantine'])store[name]=realDirectory(path.join(root,name));
  return {...store,entriesV2:realDirectory(path.join(root,STORE_ENTRY_DIRECTORY)),
    maintenance:path.join(root,'maintenance.lock'),collection:path.join(root,'collection.json')};
}

function writeAtomic(file, value) {
  const pending=`${file}.${process.pid}.${randomUUID()}.pending`;
  fs.writeFileSync(pending,JSON.stringify(value,null,2),{flag:'wx',mode:0o600});
  fs.renameSync(pending,file);
}

function readRecord(file) {
  const stat=fs.lstatSync(file);
  assert.ok(stat.isFile()&&stat.size<=MAX_RECORD_BYTES,`Source store record is not a bounded regular file: ${file}`);
  return JSON.parse(fs.readFileSync(file,'utf8'));
}

/** A process-lifetime owner; its kernel lock disappears with the process. */
export function holdStoreOwner(store) {
  const file=path.join(store.owners,`${randomUUID()}.lock`),fd=tryStoreLock(file,'ex');
  assert.ok(fd!==null,'Could not take a fresh source store owner lock');
  return {file,fd};
}

/** Live means another live descriptor holds the owner lock; an acquirable lock proves exit. */
export function probeStoreOwner(file) {
  let fd;
  try{fd=fs.openSync(file,openFlags('ex',false));}
  catch(error){
    if(['EAGAIN','EWOULDBLOCK'].includes(error.code))return 'live';
    if(error.code==='ENOENT')return 'missing';
    throw error;
  }
  fs.closeSync(fd);
  return 'exited';
}

/** The private SDK root for one attempt; views are published only with a lease naming them. */
export function storeViewPath(store, attempt) {
  assert.ok(typeof attempt==='string'&&path.isAbsolute(attempt),'Source store views need an absolute attempt');
  return path.join(store.views,createHash('sha256').update(attempt).digest('hex').slice(0,32));
}

/** Publish the view and reader lease together before any entry is validated or used. */
export async function createStoreLease(store, lease, deadline) {
  const {owner,view,keys}=lease;
  assert.ok(path.dirname(view)===store.views&&Array.isArray(keys)&&keys.length<=4096,'Invalid source store lease');
  assert.ok(path.dirname(owner)===store.owners,'Source store lease owner must be a store owner lock');
  // `entryVersion` says this reader reads only v2 entries: it never keeps a version-1 copy alive.
  const record={schemaVersion:1,entryVersion:2,id:randomUUID(),owner,holderPid:process.pid,view,keys:[...new Set(keys)].sort(),
    createdAt:new Date().toISOString()};
  const fd=await lockUntil(store.maintenance,'sh',deadline);
  assert.ok(fd!==null,'Source store collection did not release its lock before the caller deadline');
  try{
    assert.equal(probeStoreOwner(owner),'live','Source store lease owner is not a live process');
    realDirectory(view);
    writeAtomic(path.join(store.leases,`${record.id}.json`),record);
  }finally{fs.closeSync(fd);}
  const now=new Date();
  for(const key of record.keys)touchEntry(path.join(store.entriesV2,key,RECORD),now);
  return record;
}

function touchEntry(file, now) {
  try{fs.utimesSync(file,now,now);}
  catch(error){if(error.code!=='ENOENT')throw error;}
}

/** Name a store entry at the SDK's path-keyed location inside this job's private view. */
export function linkStoreView(view, pathName, target) {
  assert.ok(/^hfcache-v4-[0-9a-f]{16}$/.test(pathName),'Invalid SDK source cache name');
  const link=path.join(view,pathName),stat=fs.lstatSync(link,{throwIfNoEntry:false});
  if(!stat){fs.symlinkSync(target,link,'dir');return 'linked';}
  assert.ok(stat.isSymbolicLink()&&fs.readlinkSync(link)===target,`View entry is not the exact store link: ${link}`);
  return 'already-linked';
}

export function readStoreHolder(store, key) {
  try{return readRecord(holderFile(store,key));}
  catch(error){if(error.code==='ENOENT')return null;throw error;}
}

/** A directory may vanish when its owner publishes or collection removes it. */
function listed(directory, withFileTypes=false) {
  try{return fs.readdirSync(directory,{withFileTypes});}
  catch(error){if(error.code==='ENOENT')return [];throw error;}
}

/** Observe a live holder's own view: extraction progress, never another job's entries. */
export function holderProgressFrames(holders) {
  let frames=0;
  for(const view of new Set(holders.filter(Boolean).map(row=>row.view)))for(const entry of listed(view,true).filter(row=>row.isDirectory())){
    frames+=listed(path.join(view,entry.name)).filter(name=>FRAME.test(name)).length;
  }
  return frames;
}

export const STORE_INTERNALS={RECORD,MARKER,FRAME,LEGACY,KEY,writeAtomic,readRecord,realDirectory,lockFile,holderFile,lockUntil,
  listed,remaining,POLL_MS};
