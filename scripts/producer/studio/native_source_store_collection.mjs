/** Collect the shared source store only under its exclusive maintenance lock; live leases always win.
 *
 * Lease publication holds the maintenance lock shared, so collection never races a reader that is
 * about to validate entries. Condemned directories are renamed into trash while the lock is held
 * and deleted afterwards. Sizes are measured, never trusted: a v2 entry is structurally checked
 * (single-link regular files whose sizes equal its record, `measureStoreEntry`) and counted with its
 * record; an unleased v2 entry that fails is quarantined, a leased one is kept and reported. Untrusted
 * version-1 entries are measured without following links and evicted like any unleased row; only a
 * lease from a reader that still reads v1 (one without `entryVersion: 2`) protects them. Quarantine is
 * reported separately (`quarantineBytes`), never counted against the byte budget it cannot yet free,
 * and removed once it passes the idle floor. Legacy path-keyed SDK entries in the
 * cache root are preserved: the maintained Short adapter still uses them without
 * these reader leases, so age alone cannot establish that they have no reader.
 */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {randomUUID} from 'node:crypto';
import {STORE_ENTRY_MIN_AGE_MS,STORE_COLLECTION_INTERVAL_MS,STORE_INTERNALS,probeStoreOwner,tryStoreLock} from './native_source_store.mjs';
import {QUARANTINE_NOTE,measureStoreEntry,moveToQuarantine} from './native_source_store_entry.mjs';

const {RECORD,writeAtomic,readRecord}=STORE_INTERNALS;
const STUB_MIN_AGE_MS=60*60*1000;

/** Collection runs after a publication, or when the previous collection is a day old. */
export function collectionDue(store, published, now=Date.now()) {
  if(published)return true;
  const stat=fs.statSync(store.collection,{throwIfNoEntry:false});
  return !stat||now-stat.mtimeMs>STORE_COLLECTION_INTERVAL_MS;
}

function toTrash(store, directory) {
  fs.renameSync(directory,path.join(store.trash,`${path.basename(directory)}.${randomUUID()}`));
}

/** No lease writer is active under the exclusive lock, so a pending file is a crashed write. */
function liveLeases(store, stats) {
  const live=[];
  for(const name of fs.readdirSync(store.leases)){
    const file=path.join(store.leases,name);
    if(name.endsWith('.pending')){fs.rmSync(file);continue;}
    assert.ok(name.endsWith('.json'),`Unexpected source store lease artifact: ${name}`);
    const lease=readRecord(file);
    assert.ok(lease.schemaVersion===1&&typeof lease.owner==='string'&&typeof lease.view==='string'
      &&Array.isArray(lease.keys),`Malformed source store lease: ${name}`);
    if(probeStoreOwner(lease.owner)==='live'){live.push(lease);continue;}
    fs.rmSync(file);stats.staleLeases++;
  }
  return live;
}

/** An acquirable owner lock proves its process exited. A supervisor locks its `.creating` stub
 * just after creating it, so an unlocked stub is removed only once it is clearly abandoned. */
function removeExitedOwners(store, stats, now) {
  for(const name of fs.readdirSync(store.owners)){
    const file=path.join(store.owners,name);
    const stat=fs.lstatSync(file,{throwIfNoEntry:false});
    if(!stat||(name.endsWith('.creating')&&now-stat.mtimeMs<STUB_MIN_AGE_MS))continue;
    if(probeStoreOwner(file)!=='exited')continue;
    fs.rmSync(file,{force:true});stats.exitedOwners++;
  }
}

function directoryBytes(directory) {
  let total=0;
  for(const entry of fs.readdirSync(directory,{withFileTypes:true})){
    const file=path.join(directory,entry.name);
    total+=entry.isDirectory()?directoryBytes(file):fs.lstatSync(file).size;
  }
  return total;
}

/** Trusted v2 entries at exact measured size; an unleased refused entry is quarantined now. */
function storeRows(store, leased, budget, stats) {
  const rows=[];
  for(const key of fs.readdirSync(store.entriesV2)){
    if(expired(budget)){Object.assign(stats,{scanIncomplete:true,stoppedAtDeadline:true});break;}
    const measured=measureStoreEntry(store,key),dir=path.join(store.entriesV2,key);
    if(measured.state==='present')rows.push({kind:'store',key,...measured});
    if(measured.state!=='refused')continue;
    stats.refused.push({key,reason:measured.reason,leased:leased.has(key)});
    if(leased.has(key))rows.push({kind:'refused-leased',key,dir,bytes:treeBytes(dir),lastUsedMs:budget.now});
    else moveToQuarantine(store,{key,reason:measured.reason},{collection:process.pid});
  }
  return rows;
}

/** Bytes of a directory or file without following any link. */
function treeBytes(file) {
  const stat=fs.lstatSync(file);
  return stat.isDirectory()?directoryBytes(file):stat.size;
}

/** Untrusted version-1 entries: never read for frames, only measured and aged by their record. */
function versionOneRows(store) {
  return fs.readdirSync(store.entries).map(key=>{
    const dir=path.join(store.entries,key),record=fs.lstatSync(path.join(dir,RECORD),{throwIfNoEntry:false});
    return {kind:'store-v1',key,dir,bytes:treeBytes(dir),lastUsedMs:(record??fs.lstatSync(dir)).mtimeMs};
  });
}

/** Quarantined entries are never served; each is kept for diagnosis until the idle floor passes. */
function quarantineRows(store) {
  return fs.readdirSync(store.quarantine).map(name=>{
    const dir=path.join(store.quarantine,name),note=fs.lstatSync(path.join(dir,QUARANTINE_NOTE),{throwIfNoEntry:false});
    return {kind:'quarantine',key:name,dir,bytes:treeBytes(dir),lastUsedMs:(note??fs.lstatSync(dir)).mtimeMs};
  });
}

const expired=budget=>performance.now()>=budget.until;

/** Views are matched by their attempt id, so a differently spelled cache root cannot orphan one. */
function removeUnleasedViews(store, leases, stats) {
  const views=new Set(leases.map(lease=>path.basename(lease.view)));
  for(const name of fs.readdirSync(store.views))if(!views.has(name)){toTrash(store,path.join(store.views,name));stats.views++;}
}

function condemn(store, row, stats, list) {
  toTrash(store,row.dir);stats[list].push({kind:row.kind,key:row.key,bytes:row.bytes});
  return row.bytes;
}

/** A v2 entry is protected by any live lease naming its key; a v1 copy only by a lease from a reader
 * that still reads v1. A leased refused entry is never condemned. */
function protectedRow(row, leased) {
  if(row.kind==='store')return leased.all.has(row.key);
  if(row.kind==='store-v1')return leased.versionOne.has(row.key);
  return row.kind==='refused-leased';
}

/** Aged quarantine goes regardless of budget; then unleased aged rows go LRU while over budget. */
function condemnRows(store, rows, context) {
  const {budget,stats,leased}=context,aged=row=>budget.now-row.lastUsedMs>=budget.minAgeMs;
  let total=rows.filter(row=>row.kind!=='quarantine').reduce((sum,row)=>sum+row.bytes,0);
  for(const row of rows.filter(value=>value.kind==='quarantine'&&aged(value))){
    if(expired(budget)){stats.stoppedAtDeadline=true;break;}
    condemn(store,row,stats,'quarantineRemoved');
  }
  const evictable=rows.filter(row=>row.kind!=='quarantine'&&!protectedRow(row,leased)&&aged(row));
  for(const row of evictable.sort((a,b)=>a.lastUsedMs-b.lastUsedMs)){
    if(total<=budget.maxBytes)break;
    if(expired(budget)){stats.stoppedAtDeadline=true;break;}
    total-=condemn(store,row,stats,'evicted');
  }
  return total;
}

function sweep(store, budget, stats) {
  const leases=liveLeases(store,stats);
  removeExitedOwners(store,stats,budget.now);
  removeUnleasedViews(store,leases,stats);
  const leased={all:new Set(leases.flatMap(lease=>lease.keys)),
    versionOne:new Set(leases.filter(lease=>lease.entryVersion!==2).flatMap(lease=>lease.keys))};
  const rows=[...storeRows(store,leased.all,budget,stats),...versionOneRows(store)];
  stats.legacyRootPreserved=true;
  const quarantine=quarantineRows(store);
  Object.assign(stats,{liveLeases:leases.length,leasedEntries:leased.all.size,bytesBefore:rows.reduce((sum,row)=>sum+row.bytes,0),
    quarantineBytes:quarantine.reduce((sum,row)=>sum+row.bytes,0)});
  const total=condemnRows(store,[...rows,...quarantine],{budget,stats,leased});
  Object.assign(stats,{bytesAfter:total,overBudget:total>budget.maxBytes});
}

/** Deleting condemned bytes is bounded too; whatever remains is removed by the next collection. */
function emptyTrash(store, stats, budget) {
  for(const name of fs.readdirSync(store.trash)){
    if(expired(budget)){stats.trashDeferred++;continue;}
    try{fs.rmSync(path.join(store.trash,name),{recursive:true,force:true});stats.trashRemoved++;}
    catch(error){stats.trashErrors.push(`${name}: ${error.code??error.message}`);}
  }
}

/** Never blocks and never outlives `until` (a monotonic performance.now() bound from the caller).
 * A busy maintenance lock means a lease is being published or another collection runs. */
export function collectStoreGarbage(store, budget) {
  const {maxBytes,minAgeMs=STORE_ENTRY_MIN_AGE_MS,now=Date.now(),until}=budget;
  assert.ok(Number.isSafeInteger(maxBytes)&&maxBytes>0,'Source store collection requires an explicit byte budget');
  assert.ok(Number.isFinite(minAgeMs)&&minAgeMs>=0,'Source store collection requires an explicit idle floor');
  assert.ok(Number.isFinite(until),'Source store collection requires an explicit caller deadline');
  const fd=tryStoreLock(store.maintenance,'ex');
  if(fd===null)return {status:'skipped-maintenance-busy'};
  const limits={maxBytes,minAgeMs,now,until};
  const stats={status:'collected',maxBytes,minAgeMs,staleLeases:0,exitedOwners:0,views:0,legacyPartials:0,
    refused:[],evicted:[],quarantineRemoved:[],trashRemoved:0,trashDeferred:0,trashErrors:[]};
  try{sweep(store,limits,stats);}
  catch(error){stats.status='failed-nothing-further-condemned';stats.error=String(error?.message??error);}
  finally{fs.closeSync(fd);}
  emptyTrash(store,stats,limits);
  writeAtomic(store.collection,{...stats,completedAt:new Date().toISOString()});
  return stats;
}
