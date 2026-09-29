/** Attempt-scoped admission ledger and re-admission of an entry replaced after admission.
 * Real kernel locks and child processes; TEST frames only, no media process. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {test,mock} from 'node:test';
import {setTimeout as sleep} from 'node:timers/promises';
import {STORE_INTERNALS,storeKey,storeViewPath,storeDeadline,tryStoreLock} from '../producer/studio/native_source_store.mjs';
import {readStoreEntry,publishStoreEntry,entryDirectoryIdentity} from '../producer/studio/native_source_store_entry.mjs';
import {acquireStoreEntries} from '../producer/studio/native_source_store_publisher.mjs';
import {withStore} from './native_source_store_fixture.mjs';

const ok=result=>assert.equal(result.code,0,result.stdout+result.stderr);

function publishTest(store, label) {
  const blob={schema:'TEST sniper-source-frames',label},key=storeKey(blob),staging=path.join(store.views,`test-${label}`);
  fs.mkdirSync(staging,{recursive:true});fs.writeFileSync(path.join(staging,'.hf-complete'),'');
  for(let index=1;index<=4;index++)fs.writeFileSync(path.join(staging,`frame_0000${index}.png`),`TEST ${label} frame ${index}`);
  return {key,entry:publishStoreEntry(store,{key,blob,frames:4,directory:staging,publisher:{test:label}})};
}

async function supervisorOwner(f) {
  const supervisor=f.start({role:'supervisor',cache:f.cache,events:f.events,label:'supervisor',holdMs:60000});
  for(let attempt=0;attempt<500;attempt++){
    const line=supervisor.captured().split('\n').find(value=>value.startsWith('{'));
    if(line)return JSON.parse(line).owner;
    await sleep(20);
  }
  throw new Error('TEST supervisor did not publish its owner lock');
}

test('an attempt ledger admits without reading frames only while every identity holds and the files had settled',()=>withStore(async f=>{
  const store=f.store(),{key}=publishTest(store,'ledger');
  await sleep(2100);
  const first=readStoreEntry(store,key,4);assert.equal(first.admittedBy,'full-hash');
  const prior={frameDigest:first.frameDigest,directoryIdentity:first.directoryIdentity,identities:first.identities,
    hashStartedMs:first.hashStartedMs};
  const reads=mock.method(fs,'readSync');
  try{
    assert.equal(readStoreEntry(store,key,4,prior).admittedBy,'attempt-ledger');
    assert.equal(reads.mock.callCount(),0,'no frame byte was read');
    const racy={...prior,hashStartedMs:prior.hashStartedMs-1500};
    assert.equal(readStoreEntry(store,key,4,racy).admittedBy,'full-hash','files changed within the racy margin are rehashed');
    assert.ok(reads.mock.callCount()>0);
    assert.equal(readStoreEntry(store,key,4,{...prior,frameDigest:'0'.repeat(64)}).admittedBy,'full-hash');
    fs.chmodSync(path.join(first.dir,'frame_00003.png'),0o400);
    assert.equal(readStoreEntry(store,key,4,prior).admittedBy,'full-hash','a changed frame identity is rehashed');
  }finally{mock.restoreAll();}
}));

test('a later acquisition in the same attempt admits from its ledger; another attempt hashes in full',()=>withStore(async f=>{
  const owner=await supervisorOwner(f),spec=f.spec('attempt',f.project('native-v1'),{sourceStoreOwner:owner});
  const published=await f.start(spec).done;ok(published);
  assert.equal(published.result.entries[0].admittedBy,'publication');
  await sleep(2100);
  const second=await f.start(spec).done;ok(second);
  assert.equal(second.result.entries[0].admittedBy,'full-hash','a publication-time record is inside the racy margin');
  const third=await f.start(spec).done;ok(third);
  assert.equal(third.result.entries[0].admittedBy,'attempt-ledger');
  assert.equal(third.result.entries[0].frameDigest,published.result.entries[0].frameDigest);
  const {contentKey}=third.result.entries[0];
  assert.ok(fs.statSync(path.join(third.result.view,'.sniper-admissions',`${contentKey}.json`)).isFile());
  const other=await f.start(f.spec('other',f.project('native-v2'),{sourceStoreOwner:owner})).done;ok(other);
  assert.equal(other.result.entries[0].admittedBy,'full-hash','a new attempt never trusts another attempt ledger');
}));

test('an entry replaced after admission (refused copy republished) is admitted again, not refused',()=>withStore(async f=>{
  const store=f.store(),one=publishTest(store,'one'),two={schema:'TEST sniper-source-frames',label:'two'};
  const twoKey=storeKey(two),held=tryStoreLock(STORE_INTERNALS.lockFile(store,twoKey),'ex');
  const view=storeViewPath(store,'/TEST/reader'),before=entryDirectoryIdentity(store,one.key);
  let replaced=false;
  const onWait=()=>{
    if(replaced)return;
    replaced=true;fs.renameSync(one.entry.dir,path.join(f.root,'TEST-quarantined-one'));
    publishTest(store,'one');publishTest(store,'two');fs.closeSync(held);
  };
  const entries=await acquireStoreEntries(store,[{key:one.key,frames:4},{key:twoKey,frames:4}],
    {deadline:storeDeadline(Date.now()+10000),holder:{pid:process.pid,view,attempt:'/TEST/reader'},extract:null,publish:null,onWait});
  assert.ok(replaced,'the other entry was replaced while this job waited');
  assert.notEqual(entries.get(one.key).directoryIdentity,before);
  assert.equal(entries.get(one.key).directoryIdentity,entryDirectoryIdentity(store,one.key),'the republished entry was re-admitted');
  assert.equal(entries.get(twoKey).outcome,'published-by-another-live-job');
}));
