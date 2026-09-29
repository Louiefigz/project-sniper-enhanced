/** One live publisher per shared source entry: kernel-lock ownership, takeover and refused-entry replacement.
 *
 * Each wanted entry is admitted by its frame digest (`native_source_store_entry.mjs`). Missing entries
 * are locked all-or-nothing, extracted and published by the job holding every lock; a dead holder's
 * kernel lock is released, so a waiting job takes over. A refused entry is replaced only by a job that
 * holds its lock and may extract, after moving it to quarantine under the maintenance lock, and never
 * while another live reader's view links it: that job releases every lock and waits, within its own
 * deadline, for those readers to exit (SourceStoreEntryHeld when they do not).
 *
 * Attempt ledger: after a full hash, the admission is recorded in this attempt's private view
 * (`views/<attempt>/.sniper-admissions/<key>.json`), which the attempt's live lease keeps from
 * collection. A later acquisition in the same attempt skips the hash only when every identity still
 * matches and the files settled before that hash (`readStoreEntry`). Trust gap: a change that bypasses
 * the filesystem (a raw device write, media or firmware corruption, a forged ledger record or a clock
 * rolled back onto the exact prior timestamps) after the first full hash of an attempt is not seen by
 * that attempt's later acquisitions; every new attempt hashes in full first.
 */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {setTimeout as sleep} from 'node:timers/promises';
import {STORE_INTERNALS,SourceStoreEntryRefused,SourceStoreEntryHeld,tryStoreLock,probeStoreOwner,readStoreHolder}
  from './native_source_store.mjs';
import {readStoreEntry,recheckStoreEntry,moveToQuarantine,entryDirectoryIdentity} from './native_source_store_entry.mjs';

const {readRecord,lockFile,holderFile,writeAtomic,lockUntil,listed,remaining,realDirectory,POLL_MS}=STORE_INTERNALS;
const LEDGER='.sniper-admissions',MAX_LEDGER_BYTES=16*1024*1024;
const refuse=(key, reason)=>{throw new SourceStoreEntryRefused(key,reason);};

/** This attempt's own record of an earlier full hash, or null (then the entry is hashed in full). */
function priorAdmission(view, key) {
  const file=path.join(view,LEDGER,`${key}.json`),stat=fs.lstatSync(file,{throwIfNoEntry:false});
  if(!stat?.isFile()||stat.size>MAX_LEDGER_BYTES)return null;
  let row;
  try{row=JSON.parse(fs.readFileSync(file,'utf8'));}catch(error){if(error instanceof SyntaxError)return null;throw error;}
  return row?.schemaVersion===1&&row.key===key?row:null;
}

function recordAdmission(view, key, entry) {
  if(entry.admittedBy==='attempt-ledger')return;
  writeAtomic(path.join(realDirectory(path.join(view,LEDGER)),`${key}.json`),{schemaVersion:1,key,frameDigest:entry.frameDigest,
    directoryIdentity:entry.directoryIdentity,identities:entry.identities,hashStartedMs:entry.hashStartedMs,
    admittedBy:entry.admittedBy,recordedAt:new Date().toISOString()});
}

function resolvesTo(link, dir) {
  try{return fs.realpathSync(link)===dir;}
  catch(error){if(['ENOENT','ELOOP','ENOTDIR'].includes(error.code))return false;throw error;}
}

/** Live leases, other than this attempt's own view, whose private view links the entry directory. A
 * reader that has leased and admitted the entry but not linked it yet is not visible here; if the entry
 * is replaced, that reader's final re-check sees the new directory and re-admits it. */
function linkingReaders(store, dir, ownView) {
  const readers=[];
  for(const name of listed(store.leases).filter(value=>value.endsWith('.json'))){
    const lease=readRecord(path.join(store.leases,name));
    if(typeof lease.view!=='string'||typeof lease.owner!=='string'){readers.push(`malformed lease ${name}`);continue;}
    const view=path.join(store.views,path.basename(lease.view));
    if(path.basename(lease.view)===path.basename(ownView)||probeStoreOwner(lease.owner)!=='live')continue;
    if(listed(view,true).some(row=>row.isSymbolicLink()&&resolvesTo(path.join(view,row.name),dir)))readers.push(lease.id);
  }
  return readers;
}

/** The caller holds the entry's publication lock and will regenerate it. Under the maintenance lock no
 * lease is being published and collection is idle. Returns the quarantine, or the live readers that
 * link the entry (then nothing moves). */
export async function quarantineStoreEntry(store, refusal, holder, deadline) {
  const fd=await lockUntil(store.maintenance,'ex',deadline);
  if(fd===null)refuse(refusal.key,`${refusal.reason}; the maintenance lock was busy until the caller deadline, so it was not replaced`);
  try{
    const readers=linkingReaders(store,path.join(store.entriesV2,refusal.key),holder.view);
    if(readers.length)return {held:readers};
    return {quarantine:moveToQuarantine(store,refusal,{pid:holder.pid,attempt:holder.attempt})};
  }finally{fs.closeSync(fd);}
}

function tryLockAll(store, rows) {
  const fds=[];
  for(const row of [...rows].sort((a,b)=>a.key.localeCompare(b.key))){
    const fd=tryStoreLock(lockFile(store,row.key),'ex');
    if(fd===null){fds.forEach(held=>fs.closeSync(held));return null;}
    fds.push(fd);
  }
  return fds;
}

/** Admit a present entry once per acquisition (by ledger or full hash); a refused directory is
 * re-verified only once its identity changes. */
function observe(store, row, state) {
  const identity=entryDirectoryIdentity(store,row.key);
  if(!identity){state.refused.delete(row.key);state.held.delete(row.key);return;}
  if(state.refused.get(row.key)?.identity===identity)return;
  try{
    const entry=readStoreEntry(store,row.key,row.frames,priorAdmission(state.view,row.key));
    if(!entry)return;
    recordAdmission(state.view,row.key,entry);
    state.admitted.set(row.key,entry);state.refused.delete(row.key);state.held.delete(row.key);
    const started=state.waiting.get(row.key);
    if(!state.outcomes.has(row.key))state.outcomes.set(row.key,started===undefined?{outcome:'store-hit',waitedMs:0}
      :{outcome:'published-by-another-live-job',waitedMs:Math.round(performance.now()-started)});
  }catch(error){
    if(!(error instanceof SourceStoreEntryRefused))throw error;
    state.refused.set(row.key,{identity,reason:error.reason});
  }
}

/** Say once why this job waits: the refused entry stays in place for readers that link it. */
function noteHeld(state, key, held) {
  if(!state.held.has(key))console.log(`Source entry ${key} is refused (${held.reason}) and linked by live reader lease(s) `
    +`${held.readers.join(', ')}; waiting for them within the caller deadline`);
  state.held.set(key,held);
}

/** Quarantine refused entries this job owns; a job that may not extract fails closed and moves nothing.
 * An entry another live reader links is left in place and marked held. */
async function replaceRefused(store, owned, state, options) {
  for(const row of owned.filter(value=>state.refused.has(value.key))){
    const {reason}=state.refused.get(row.key);
    if(!options.extract)refuse(row.key,reason);
    const result=await quarantineStoreEntry(store,{key:row.key,reason},options.holder,options.deadline);
    if(result.held){noteHeld(state,row.key,{reason,readers:result.held});continue;}
    state.replaced.set(row.key,{reason,quarantine:result.quarantine});state.refused.delete(row.key);state.held.delete(row.key);
  }
}

async function publishOwned(store, owned, state, options) {
  if(!options.extract)throw new Error(`Exact native source frame cache missing: ${owned.map(row=>row.key).join(', ')}`);
  for(const row of owned)writeAtomic(holderFile(store,row.key),{...options.holder,key:row.key,startedAt:new Date().toISOString()});
  await options.extract(owned);
  for(const row of owned){
    const entry=await options.publish(row);
    recordAdmission(state.view,row.key,entry);state.admitted.set(row.key,entry);
    const untrusted=path.join(store.entries,row.key),replaced=state.replaced.get(row.key);
    state.outcomes.set(row.key,{outcome:'published-by-this-job',waitedMs:0,...(replaced?{replaced}:{}),
      ...(fs.lstatSync(untrusted,{throwIfNoEntry:false})?{untrustedVersion1Kept:untrusted}:{})});
  }
}

/** Lock every missing entry or none; under the locks a finished neighbour is admitted, refused entries
 * are quarantined and the rest are extracted and published. Returns 'locked-out', 'held' or 'published'. */
async function publishIfOwned(store, missing, state, options) {
  const fds=tryLockAll(store,missing);
  if(!fds)return 'locked-out';
  try{
    for(const row of missing)observe(store,row,state);
    const owned=missing.filter(row=>!state.admitted.has(row.key));
    await replaceRefused(store,owned,state,options);
    const ready=owned.filter(row=>!state.held.has(row.key));
    if(ready.length)await publishOwned(store,ready,state,options);
    return ready.length===owned.length?'published':'held';
  }finally{for(const fd of fds)fs.closeSync(fd);}
}

/** Nobody waits while holding an entry lock. At the caller deadline a held entry raises its own class. */
async function waitForHolders(store, missing, state, options) {
  for(const row of missing)if(!state.waiting.has(row.key))state.waiting.set(row.key,performance.now());
  const holders=missing.map(row=>readStoreHolder(store,row.key));
  const [heldKey,held]=[...state.held][0]??[];
  if(remaining(options.deadline)<=0&&held)throw new SourceStoreEntryHeld(heldKey,`${held.reason}; live reader lease(s) `
    +`${held.readers.join(', ')} link it, so it was neither served nor replaced before the caller deadline`);
  if(remaining(options.deadline)<=0)throw new Error('Another live job did not publish source frames before the caller deadline: '
    +JSON.stringify(holders));
  await options.onWait?.(holders);
  await sleep(Math.min(POLL_MS,Math.max(1,remaining(options.deadline))));
}

/** An entry replaced after this job admitted it (quarantined and republished for a refused copy) is
 * dropped and admitted again; returns whether any was dropped. */
function dropReplaced(store, wanted, state, deadline) {
  const replaced=wanted.filter(row=>entryDirectoryIdentity(store,row.key)!==state.admitted.get(row.key).directoryIdentity);
  if(replaced.length&&remaining(deadline)<=0)refuse(replaced[0].key,'it was replaced after admission and the caller deadline passed');
  for(const row of replaced){state.admitted.delete(row.key);state.outcomes.delete(row.key);}
  return replaced.length>0;
}

/** Every wanted entry is admitted by digest; each missing or refused one is published by exactly one
 * live job. Missing entries are locked all-or-nothing and nobody waits while holding an entry lock,
 * so two jobs never deadlock; a dead publisher's kernel lock is released, so the next job takes over.
 * `options.publish` returns the entry it published, already bound to its digest.
 */
export async function acquireStoreEntries(store, wanted, options) {
  assert.ok(Number.isFinite(options.deadline),'Source store acquisition requires an explicit monotonic deadline');
  const state={view:options.holder.view,admitted:new Map(),refused:new Map(),held:new Map(),replaced:new Map(),
    outcomes:new Map(),waiting:new Map()};
  for(;;){
    for(const row of wanted.filter(item=>!state.admitted.has(item.key)))observe(store,row,state);
    const missing=wanted.filter(row=>!state.admitted.has(row.key));
    if(!missing.length&&!dropReplaced(store,wanted,state,options.deadline))break;
    if(missing.length&&await publishIfOwned(store,missing,state,options)!=='published')await waitForHolders(store,missing,state,options);
  }
  for(const row of wanted)recheckStoreEntry(row.key,state.admitted.get(row.key));
  return new Map(wanted.map(row=>[row.key,{...state.admitted.get(row.key),...state.outcomes.get(row.key)}]));
}
