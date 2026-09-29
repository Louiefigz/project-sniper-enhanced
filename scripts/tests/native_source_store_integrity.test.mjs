/** Frame-digest admission, refusal, quarantine, version-1 retirement and exact collection accounting.
 * Real child processes and kernel locks; TEST frames only, no media process. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {setTimeout as sleep} from 'node:timers/promises';
import {SourceStoreEntryRefused,STORE_INTERNALS,storeKey,storeViewPath,holdStoreOwner,createStoreLease,storeDeadline,tryStoreLock}
  from '../producer/studio/native_source_store.mjs';
import {readStoreEntry,inspectStoreEntry,recheckStoreEntry,publishStoreEntry}
  from '../producer/studio/native_source_store_entry.mjs';
import {collect,withStore,extractions,sha} from './native_source_store_fixture.mjs';

const RECORD='.sniper-entry.json';
const writable=file=>{fs.chmodSync(file,0o644);return file;};
const ok=result=>assert.equal(result.code,0,result.stdout+result.stderr);

/** Sum of every file's own size under a directory; no link is followed. */
function realBytes(dir) {
  return fs.readdirSync(dir,{withFileTypes:true}).reduce((sum,row)=>{
    const file=path.join(dir,row.name);return sum+(row.isDirectory()?realBytes(file):fs.lstatSync(file).size);
  },0);
}

/** Names, inodes, sizes, mtimes and byte hashes: any read-into, rewrite or upgrade changes this. */
const treeState=dir=>JSON.stringify(fs.readdirSync(dir).sort().map(name=>{
  const file=path.join(dir,name),stat=fs.lstatSync(file);return [name,stat.ino,stat.size,stat.mtimeMs,sha(fs.readFileSync(file))];
}));

/** Publish a four-frame TEST entry in-process through the real publication primitive. */
function publishTest(store, label) {
  const blob={schema:'TEST sniper-source-frames',label},key=storeKey(blob),staging=path.join(store.views,`test-${label}`);
  fs.mkdirSync(staging,{recursive:true});fs.writeFileSync(path.join(staging,'.hf-complete'),'');
  for(let index=1;index<=4;index++)fs.writeFileSync(path.join(staging,`frame_0000${index}.png`),`TEST ${label} frame ${index}`);
  return {key,entry:publishStoreEntry(store,{key,blob,frames:4,directory:staging,publisher:{test:label}})};
}

function rewriteRecord(dir, change) {
  const file=path.join(dir,RECORD);fs.writeFileSync(file,JSON.stringify(change(JSON.parse(fs.readFileSync(file,'utf8')))));
}

/** Turn a published v2 entry into an old version-1 entry: v1 place and record, frames never bound. */
function demoteToVersionOne(store, key) {
  const v1=path.join(store.entries,key);fs.renameSync(path.join(store.entriesV2,key),v1);
  rewriteRecord(v1,record=>({schemaVersion:1,key,blob:record.blob,frames:record.frames,bytes:record.bytes,publisher:{test:'TEST v1'}}));
  for(const name of fs.readdirSync(v1).filter(value=>value.startsWith('frame_')))fs.writeFileSync(writable(path.join(v1,name)),`TEST OLD ${name}`);
  return v1;
}

test('replaced frame bytes with unchanged names, count and size are refused, then quarantined and regenerated',()=>withStore(async f=>{
  const first=await f.start(f.spec('first',f.project('native-v1'))).done;ok(first);
  const store=f.store(),{contentKey:key,frameDigest}=first.result.entries[0],dir=path.join(store.entriesV2,key);
  const frame=path.join(dir,'frame_00003.png'),stat=fs.statSync(frame),corrupt=Buffer.from(fs.readFileSync(frame)).reverse();
  const replacement=path.join(f.root,'replacement.png');fs.writeFileSync(replacement,corrupt);fs.chmodSync(replacement,0o444);
  fs.renameSync(replacement,frame);fs.utimesSync(frame,stat.atime,stat.mtime);
  assert.equal(fs.statSync(frame).size,stat.size);assert.equal(inspectStoreEntry(store,key,25).state,'present','structure alone cannot see it');
  assert.throws(()=>readStoreEntry(store,key,25),/refused and never served: frame bytes differ from the published frame digest/);
  const hitOnly=await f.start(f.spec('hit-only',f.project('native-v2'),{mode:'existing-only'})).done;
  assert.equal(hitOnly.code,1);assert.match(hitOnly.result.error,/refused and never served: frame bytes differ/);
  assert.deepEqual(fs.readFileSync(frame),corrupt,'a job that may not extract moves nothing');
  const regen=await f.start(f.spec('regen',f.project('native-v3'))).done;ok(regen);
  const row=regen.result.entries[0];
  assert.equal(row.outcome,'published-by-this-job');assert.equal(extractions(f,'regen').length,1);
  assert.match(row.replaced.reason,/frame bytes differ/);
  assert.deepEqual(fs.readFileSync(path.join(row.replaced.quarantine,'entry/frame_00003.png')),corrupt,'the refused bytes are kept');
  assert.equal(row.frameDigest,frameDigest,'the regenerated frames are the bytes first published');
  assert.equal(readStoreEntry(store,key,25).frameDigest,frameDigest);
}));

test('symlinked, hard-linked, truncated, foreign and malformed entries are refused before a frame is served',()=>withStore(async f=>{
  const store=f.store(),outside=label=>path.join(f.root,`outside-${label}.png`);
  const swap=(dir,label,make)=>{const file=path.join(dir,'frame_00002.png');fs.copyFileSync(file,outside(label));fs.rmSync(file);make(outside(label),file);};
  const cases=[
    ['truncated',dir=>fs.truncateSync(writable(path.join(dir,'frame_00002.png')),3),/truncated or replaced frames/],
    ['appended',dir=>fs.appendFileSync(writable(path.join(dir,'frame_00004.png')),'X'),/truncated or replaced frames/],
    ['symlink',dir=>swap(dir,'symlink',(from,to)=>fs.symlinkSync(from,to)),/frame_00002\.png is a symbolic link/],
    ['hard-link-in',dir=>swap(dir,'in',(from,to)=>fs.linkSync(from,to)),/frame_00002\.png is hard-linked \(2 links\)/],
    ['hard-link-out',dir=>fs.linkSync(path.join(dir,'frame_00001.png'),outside('out')),/frame_00001\.png is hard-linked/],
    ['directory-link',dir=>{const copy=path.join(f.root,'copy');fs.cpSync(dir,copy,{recursive:true});fs.rmSync(dir,{recursive:true});
      fs.symlinkSync(copy,dir);},/not a real directory/],
    ['digest',dir=>rewriteRecord(dir,record=>({...record,frameDigest:{...record.frameDigest,value:'0'.repeat(64)}})),
      /frame bytes differ from the published frame digest/],
    ['no-digest',dir=>rewriteRecord(dir,record=>({...record,frameDigest:undefined})),/record lacks a valid frame digest/],
    ['version-1-record',dir=>rewriteRecord(dir,record=>({...record,schemaVersion:1})),/schemaVersion 1 is not 2/],
    ['no-record',dir=>fs.rmSync(path.join(dir,RECORD)),/no publication record/],
    ['extra',dir=>fs.writeFileSync(path.join(dir,'extra.txt'),'TEST'),/Unexpected artifact/],
    ['no-marker',dir=>fs.rmSync(path.join(dir,'.hf-complete')),/lack the SDK completion marker/],
    ['unreadable',dir=>fs.chmodSync(path.join(dir,'frame_00002.png'),0o000),/frame_00002\.png is unreadable \(EACCES\)/],
  ];
  for(const [label,mutate,reason] of cases){
    const {key,entry}=publishTest(store,label);mutate(entry.dir);
    assert.throws(()=>readStoreEntry(store,key,4),error=>error instanceof SourceStoreEntryRefused&&reason.test(error.message),label);
    assert.equal(inspectStoreEntry(store,key,4).state,['digest','unreadable'].includes(label)?'present':'refused',label);
  }
}));

/** A caller deadline about `seconds` from now for jobs started after this call (TEST owner record). */
function shortDeadline(f, seconds) {
  fs.writeFileSync(f.owner,JSON.stringify({startedAt:new Date(Date.now()-(570-seconds)*1000).toISOString(),runDeadlineSeconds:600}));
}

async function corruptUnderReader(f) {
  const reader=f.start(f.spec('reader',f.project('native-v1'),{holdMs:60000}));
  await f.waitFor(row=>row.type==='acquired'&&row.label==='reader');
  const store=f.store(),[key]=fs.readdirSync(store.entriesV2),frame=path.join(store.entriesV2,key,'frame_00004.png');
  const size=fs.statSync(frame).size;fs.writeFileSync(writable(frame),'X'.repeat(size));
  return {reader,store,key,frame,corrupt:'X'.repeat(size)};
}

test('a refused entry a live reader links is neither served nor replaced before that reader exits',()=>withStore(async f=>{
  const {store,frame,corrupt}=await corruptUnderReader(f);
  shortDeadline(f,1.5);
  const blocked=await f.start(f.spec('blocked',f.project('native-v2'))).done;
  assert.equal(blocked.code,1);assert.match(blocked.stdout,/linked by live reader lease\(s\) \S+; waiting for them within the caller deadline/);
  assert.match(blocked.result.error,/frame bytes differ from the published frame digest; live reader lease\(s\) \S+ link it, so it was neither served nor replaced before the caller deadline/);
  assert.equal(extractions(f,'blocked').length,0);assert.deepEqual(fs.readdirSync(store.quarantine),[]);
  assert.equal(fs.readFileSync(frame,'utf8'),corrupt,'the entry under the live reader was not moved or rewritten');
}));

test('a job held by a live reader waits without holding locks and replaces the entry once that reader exits',()=>withStore(async f=>{
  const {reader,store,key}=await corruptUnderReader(f);
  const waiter=f.start(f.spec('waiter',f.project('native-v2')));
  for(let tries=0;tries<500&&!/waiting for them within the caller deadline/.test(waiter.captured());tries++)await sleep(20);
  assert.match(waiter.captured(),/waiting for them within the caller deadline/);
  const probe=tryStoreLock(STORE_INTERNALS.lockFile(store,key),'ex');
  assert.ok(probe!==null,'the waiting job holds no entry lock');fs.closeSync(probe);
  reader.kill('SIGKILL');await reader.done;
  const after=await waiter.done;ok(after);
  assert.equal(after.result.entries[0].outcome,'published-by-this-job');assert.match(after.result.entries[0].replaced.reason,/frame bytes differ/);
  assert.equal(fs.readdirSync(store.quarantine).length,1);assert.ok(readStoreEntry(store,key,25));
}));

test('an old version-1 entry without a live reader is regenerated as v2, never read or upgraded, then collected',()=>withStore(async f=>{
  const first=await f.start(f.spec('first',f.project('native-v1'))).done;ok(first);
  const store=f.store(),key=first.result.entries[0].contentKey,v1=demoteToVersionOne(store,key),before=treeState(v1);
  const second=await f.start(f.spec('second',f.project('native-v2'))).done;ok(second);
  const row=second.result.entries[0];
  assert.equal(row.outcome,'published-by-this-job');assert.equal(extractions(f,'second').length,1);
  assert.equal(row.untrustedVersion1Kept,v1);assert.equal(treeState(v1),before,'the old entry was not read into, rewritten or upgraded');
  const entry=readStoreEntry(store,key,25);
  assert.equal(entry.frameDigest,first.result.entries[0].frameDigest);
  assert.ok(entry.names.every(name=>!fs.readFileSync(path.join(entry.dir,name),'utf8').includes('OLD')),'no old frame reached v2');
  const sizes={store:realBytes(entry.dir),'store-v1':realBytes(v1)};
  const stats=collect(store,{maxBytes:1,minAgeMs:0});
  assert.equal(stats.liveLeases,0);assert.equal(stats.bytesBefore,sizes.store+sizes['store-v1'],'both versions are measured exactly');
  assert.deepEqual(stats.evicted.map(value=>[value.kind,value.key,value.bytes]).sort(),
    [['store',key,sizes.store],['store-v1',key,sizes['store-v1']]]);
  assert.equal(stats.bytesAfter,0);assert.ok(!fs.existsSync(v1));
}));

/** A lease written by an engine that still reads version-1 entries: no `entryVersion`. */
function oldFormatLease(store, owner, view, key) {
  fs.mkdirSync(view,{recursive:true});
  fs.writeFileSync(path.join(store.leases,'TEST-old-format.json'),JSON.stringify({schemaVersion:1,id:'TEST-old-format',
    owner,holderPid:process.pid,view,keys:[key],createdAt:new Date().toISOString()}));
}

test('only an old-format live lease keeps a version-1 copy; a v2 reader lease does not keep a double copy',()=>withStore(async f=>{
  const first=await f.start(f.spec('first',f.project('native-v1'))).done;ok(first);
  const store=f.store(),{contentKey:key,pathName}=first.result.entries[0],v1=demoteToVersionOne(store,key);
  const oldOwner=holdStoreOwner(store),oldView=storeViewPath(store,'/TEST/old-format-reader');
  oldFormatLease(store,oldOwner.file,oldView,key);fs.symlinkSync(v1,path.join(oldView,pathName),'dir');
  const before=treeState(v1);
  const second=await f.start(f.spec('second',f.project('native-v2'))).done;ok(second);
  assert.equal(second.result.entries[0].outcome,'published-by-this-job');assert.equal(second.result.entries[0].untrustedVersion1Kept,v1);
  const kept=collect(store,{maxBytes:1,minAgeMs:0});
  assert.equal(kept.liveLeases,1);assert.deepEqual(kept.evicted,[],'the old-format lease protects every version of its key');
  assert.equal(treeState(v1),before);assert.equal(fs.realpathSync(path.join(oldView,pathName)),v1,'the old reader still reads its entry');
  const newOwner=holdStoreOwner(store);
  const lease=await createStoreLease(store,{owner:newOwner.file,view:storeViewPath(store,'/TEST/v2-reader'),keys:[key]},
    storeDeadline(Date.now()+10000));
  assert.equal(lease.entryVersion,2);fs.closeSync(oldOwner.fd);
  const upgraded=collect(store,{maxBytes:1,minAgeMs:0});
  assert.deepEqual(upgraded.evicted.map(value=>value.kind),['store-v1'],'a v2 reader never keeps the v1 copy alive');
  assert.ok(readStoreEntry(store,key,25),'the v2 entry stays under its live v2 lease');
  fs.closeSync(newOwner.fd);
  assert.deepEqual(collect(store,{maxBytes:1,minAgeMs:0}).evicted.map(value=>value.kind),['store']);
}));

test('SDK superset hard links are copied at publication: the shared entry owns single-link read-only frames',()=>withStore(async f=>{
  const result=await f.start(f.spec('superset',f.project('native-v1'),{hardLinkFrames:true})).done;ok(result);
  const store=f.store(),key=result.result.entries[0].contentKey,entry=readStoreEntry(store,key,25);
  assert.equal(entry.record.materializedLinks,25);
  for(const name of entry.names){
    const stat=fs.lstatSync(path.join(entry.dir,name));assert.equal(stat.nlink,1);assert.equal(stat.mode&0o777,0o444);
  }
  const sibling=fs.readdirSync(result.result.view).find(name=>name.endsWith('.TEST-overlapping-member'));
  fs.writeFileSync(path.join(result.result.view,sibling,'frame_00001.png'),'TEST write through the former link');
  assert.equal(readStoreEntry(store,key,25).frameDigest,entry.frameDigest,'the former link cannot reach the shared entry');
}));

test('collection measures exact bytes, quarantines an unleased refused entry and keeps a leased one',()=>withStore(async f=>{
  const store=f.store(),good=publishTest(store,'good'),bad=publishTest(store,'bad'),held=publishTest(store,'held');
  for(const row of [bad,held])fs.appendFileSync(writable(path.join(row.entry.dir,'frame_00001.png')),'X');
  const owner=holdStoreOwner(store);
  await createStoreLease(store,{owner:owner.file,view:storeViewPath(store,'/TEST/held'),keys:[held.key]},storeDeadline(Date.now()+10000));
  const legacy=path.join(f.cache,'hfcache-v4-00000000000000aa');fs.mkdirSync(legacy);fs.writeFileSync(path.join(legacy,'frame_00001.png'),'TEST');
  const badBytes=realBytes(bad.entry.dir);
  const first=collect(store,{maxBytes:64*1024**3});
  assert.deepEqual(first.refused.map(row=>[row.key,row.leased]).sort(),[[bad.key,false],[held.key,true]].sort());
  const [quarantined]=fs.readdirSync(store.quarantine),holder=path.join(store.quarantine,quarantined);
  assert.equal(realBytes(path.join(holder,'entry')),badBytes);assert.match(JSON.parse(fs.readFileSync(path.join(holder,'refusal.json'))).reason,/truncated/);
  assert.equal(first.bytesBefore,realBytes(good.entry.dir)+realBytes(held.entry.dir),
    'quarantine and unowned legacy caches are outside the eviction budget');
  assert.ok(fs.existsSync(legacy),'the maintained Short adapter may still be reading this cache');
  assert.equal(first.quarantineBytes,realBytes(holder));
  assert.deepEqual(first.quarantineRemoved,[],'quarantine is kept for diagnosis within the idle floor');
  assert.deepEqual(fs.readdirSync(store.entriesV2).sort(),[good.key,held.key].sort(),'the leased refused entry stays in place');
  const old=Date.now()/1000-2*3600;fs.utimesSync(path.join(good.entry.dir,RECORD),old,old);
  const exact=collect(store,{maxBytes:first.bytesBefore});
  assert.deepEqual(exact.evicted,[],'young quarantine it cannot free never evicts a valid aged entry');
  assert.ok(exact.quarantineBytes>0);assert.deepEqual(exact.quarantineRemoved,[]);
  const later=collect(store,{maxBytes:64*1024**3,minAgeMs:0});
  assert.deepEqual(later.quarantineRemoved.map(row=>row.key),[quarantined]);assert.deepEqual(later.evicted,[]);
  fs.closeSync(owner.fd);
}));

test('an admitted entry changed after admission fails its pre-use identity re-check',()=>withStore(async f=>{
  const store=f.store(),{key}=publishTest(store,'recheck'),admitted=readStoreEntry(store,key,4);
  recheckStoreEntry(key,admitted);
  const file=writable(path.join(admitted.dir,'frame_00002.png')),size=fs.statSync(file).size;fs.writeFileSync(file,'Y'.repeat(size));
  assert.throws(()=>recheckStoreEntry(key,admitted),/frame_00002\.png changed after admission/);
  const added=publishTest(store,'added'),current=readStoreEntry(store,added.key,4);
  fs.writeFileSync(path.join(current.dir,'frame_00005.png'),'TEST frame the SDK would find when it scans the directory');
  assert.throws(()=>recheckStoreEntry(added.key,current),/the entry directory changed after admission/);
}));
