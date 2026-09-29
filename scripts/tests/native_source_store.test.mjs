/** Concurrent source-store ownership, lease and collection proofs with real processes and TEST frames. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {spawn} from 'node:child_process';
import {test,mock} from 'node:test';
import {setTimeout as sleep} from 'node:timers/promises';
import {storeViewPath,probeStoreOwner} from '../producer/studio/native_source_store.mjs';
import {readStoreEntry} from '../producer/studio/native_source_store_entry.mjs';
import {collectStoreGarbage} from '../producer/studio/native_source_store_collection.mjs';
import {sourceFrameInventory} from '../producer/studio/native_long_sources.mjs';
import {collect,withStore,extractions} from './native_source_store_fixture.mjs';

test('simultaneous clips from one source across revision folders extract once and share the entry',()=>withStore(async f=>{
  const first=f.start(f.spec('v7',f.project('native-v7'),{frameDelayMs:40}));
  const second=f.start(f.spec('v8',f.project('native-v8'),{frameDelayMs:40}));
  const [a,b]=await Promise.all([first.done,second.done]);
  assert.equal(a.code,0,a.stdout+a.stderr);assert.equal(b.code,0,b.stdout+b.stderr);
  assert.equal(extractions(f).length,1,'exactly one live job decodes the shared content');
  const outcomes=[a.result.entries[0].outcome,b.result.entries[0].outcome].sort();
  assert.deepEqual(outcomes,['published-by-another-live-job','published-by-this-job']);
  assert.equal(a.result.entries[0].entry,b.result.entries[0].entry,'revision folders resolve to one content entry');
  const waiter=[a,b].find(row=>row.result.entries[0].outcome==='published-by-another-live-job');
  assert.ok(waiter.result.entries[0].waitedMs>0);
  assert.match(waiter.stdout,/SNIPER_PROGRESS source-publication-wait \d+/,'waiting reports the holder progress');
  const store=f.store(),entry=readStoreEntry(store,a.result.entries[0].contentKey,25);
  assert.equal(entry.names.length,25);
  for(const result of [a,b]){
    const link=path.join(result.result.view,result.result.entries[0].pathName);
    assert.ok(fs.lstatSync(link).isSymbolicLink());assert.equal(fs.realpathSync(link),entry.dir);
  }
}));

test('concurrent sections of one export share source bytes but own separate SDK views',()=>withStore(async f=>{
  const project=f.project('long'),output=path.join(f.root,'one-long-attempt');
  const first=f.start(f.spec('section-a',project,{output,frameDelayMs:35,holdMs:100}));
  const second=f.start(f.spec('section-b',project,{output,frameDelayMs:35,holdMs:100}));
  const [a,b]=await Promise.all([first.done,second.done]);
  assert.equal(a.code,0,a.stdout+a.stderr);assert.equal(b.code,0,b.stdout+b.stderr);
  assert.equal(extractions(f).length,1,'the shared source range is decoded once');
  assert.notEqual(a.result.view,b.result.view,'a section cannot mutate a neighboring private SDK view');
  assert.equal(a.result.entries[0].entry,b.result.entries[0].entry);
}));

test('a crash during extraction leaves no complete-looking entry and the next job takes over',()=>withStore(async f=>{
  const directory=f.project('native-v1');
  const crashing=f.start(f.spec('crash',directory,{frameDelayMs:60,crashAfterFrames:20}));
  await f.waitFor(row=>row.type==='extract-start'&&row.label==='crash');
  const taker=f.start(f.spec('taker',directory,{frameDelayMs:25}));
  const crashed=await crashing.done;assert.equal(crashed.signal,'SIGKILL');
  const store=f.store(),crashView=storeViewPath(store,path.join(f.root,'work-crash'));
  assert.deepEqual(fs.readdirSync(store.entriesV2),[],'the crashed decode published nothing shared');
  assert.ok(fs.readdirSync(crashView).some(name=>name.includes('.partial-')),'its partial stayed private');
  const taken=await taker.done;assert.equal(taken.code,0,taken.stdout+taken.stderr);
  assert.equal(taken.result.entries[0].outcome,'published-by-this-job');
  assert.match(taken.stdout,/SNIPER_PROGRESS source-publication-wait \d+/,'the taker waited on the live holder first');
  assert.equal(extractions(f,'taker').length,1);
  const entry=readStoreEntry(store,taken.result.entries[0].contentKey,25);
  assert.equal(entry.record.publisher.attempt,path.join(f.root,'attempt-taker'));
  assert.deepEqual(fs.readdirSync(store.entriesV2),[taken.result.entries[0].contentKey]);
  assert.equal(taken.result.collection.status,'collected');assert.ok(taken.result.collection.views>=1);
  assert.ok(!fs.existsSync(crashView),'the dead job view was collected after publication');
}));

test('a publisher killed after its SDK publication shares nothing; the waiting job takes over and publishes',()=>withStore(async f=>{
  const directory=f.project('native-v1');
  const crashing=f.start(f.spec('crash',directory,{frameDelayMs:40,crashAfterSdkPublish:true}));
  await f.waitFor(row=>row.type==='extract-start'&&row.label==='crash');
  const taker=f.start(f.spec('taker',directory,{frameDelayMs:1}));
  assert.equal((await crashing.done).signal,'SIGKILL');
  const store=f.store(),crashView=storeViewPath(store,path.join(f.root,'work-crash'));
  const sdkName=fs.readdirSync(crashView).find(name=>!name.includes('.partial-'));
  assert.ok(fs.existsSync(path.join(crashView,sdkName,'.hf-complete')),'the killed job left a complete-looking private SDK directory');
  const taken=await taker.done;assert.equal(taken.code,0,taken.stdout+taken.stderr);
  assert.equal(taken.result.entries[0].outcome,'published-by-this-job');assert.equal(extractions(f,'taker').length,1);
  assert.match(taken.stdout,/SNIPER_PROGRESS source-publication-wait \d+/,'the taker waited on the live holder first');
  const entry=readStoreEntry(store,taken.result.entries[0].contentKey,25);
  assert.equal(entry.record.publisher.attempt,path.join(f.root,'attempt-taker'),'the private SDK directory was never adopted');
  assert.equal(entry.frameDigest,taken.result.entries[0].frameDigest);
}));

test('a publisher whose SDK output holds a symbolic-link frame is refused; a waiting job takes over',()=>withStore(async f=>{
  const directory=f.project('native-v1');
  const linked=f.start(f.spec('linked',directory,{frameDelayMs:40,symlinkFrame:5}));
  await f.waitFor(row=>row.type==='extract-start'&&row.label==='linked');
  const taker=f.start(f.spec('taker',directory,{frameDelayMs:1}));
  const refused=await linked.done;assert.equal(refused.code,1);
  assert.match(refused.result.error,/SDK output frame_00006\.png is not a regular file; publication refused/);
  const taken=await taker.done;assert.equal(taken.code,0,taken.stdout+taken.stderr);
  assert.equal(taken.result.entries[0].outcome,'published-by-this-job');
  const store=f.store();assert.deepEqual(fs.readdirSync(store.entriesV2),[taken.result.entries[0].contentKey]);
  const entry=readStoreEntry(store,taken.result.entries[0].contentKey,25);
  assert.ok(entry.names.every(name=>fs.lstatSync(path.join(entry.dir,name)).isFile()));
}));

test('a waiter bounded by its caller deadline fails without disturbing the live publisher',()=>withStore(async f=>{
  const directory=f.project('native-v1');
  const slow=f.start(f.spec('slow',directory,{frameDelayMs:100}));
  await f.waitFor(row=>row.type==='extract-start'&&row.label==='slow');
  fs.writeFileSync(f.owner,JSON.stringify({startedAt:new Date(Date.now()-599000+30000).toISOString(),runDeadlineSeconds:600}));
  const impatient=f.start(f.spec('impatient',directory));
  const refused=await impatient.done;
  assert.equal(refused.code,1);assert.match(refused.result.error,/did not publish source frames before the caller deadline/);
  assert.match(refused.result.error,/"view"/,'the refusal names the live holder');
  fs.writeFileSync(f.owner,JSON.stringify({startedAt:new Date().toISOString(),runDeadlineSeconds:600}));
  const published=await slow.done;assert.equal(published.code,0,published.stdout+published.stderr);
  assert.equal(published.result.entries[0].outcome,'published-by-this-job');
  assert.equal(extractions(f).length,1);
}));

test('cancelling the publisher releases ownership and a waiting job takes over',()=>withStore(async f=>{
  const directory=f.project('native-v1');
  const cancelled=f.start(f.spec('cancelled',directory,{frameDelayMs:50}));
  await f.waitFor(row=>row.type==='extract-start'&&row.label==='cancelled');
  const waiting=f.start(f.spec('waiting',directory,{frameDelayMs:1}));
  await sleep(300);cancelled.kill('SIGTERM');
  assert.equal((await cancelled.done).signal,'SIGTERM');
  const result=await waiting.done;assert.equal(result.code,0,result.stdout+result.stderr);
  assert.equal(result.result.entries[0].outcome,'published-by-this-job');
  assert.equal(extractions(f,'waiting').length,1);
}));

test('collection never evicts an entry or view leased by a live reader, then collects after exit',()=>withStore(async f=>{
  const reader=f.start(f.spec('reader',f.project('native-v1'),{holdMs:60000}));
  await f.waitFor(row=>row.type==='acquired'&&row.label==='reader');
  const store=f.store(),[key]=fs.readdirSync(store.entriesV2),view=storeViewPath(store,path.join(f.root,'work-reader'));
  const kept=collect(store,{maxBytes:1,minAgeMs:0});
  assert.equal(kept.status,'collected');assert.equal(kept.evicted.length,0);assert.equal(kept.liveLeases,1);
  assert.ok(kept.overBudget,'a leased entry may keep the store over budget');
  assert.ok(readStoreEntry(store,key,25));assert.ok(fs.existsSync(view));
  reader.kill('SIGKILL');await reader.done;
  const collected=collect(store,{maxBytes:1,minAgeMs:0});
  assert.deepEqual(collected.evicted.map(row=>row.key),[key]);
  assert.equal(collected.staleLeases,1);assert.ok(collected.exitedOwners>=1);
  assert.deepEqual(fs.readdirSync(store.entriesV2),[]);assert.ok(!fs.existsSync(view));
  assert.deepEqual(fs.readdirSync(store.leases),[]);assert.deepEqual(fs.readdirSync(store.trash),[]);
}));

test('a supervisor-owned lease outlives the child that published it until the supervisor exits',()=>withStore(async f=>{
  const supervisor=f.start({role:'supervisor',cache:f.cache,events:f.events,label:'supervisor',holdMs:60000});
  let owner;
  for(let attempt=0;attempt<500&&!owner;attempt++){
    await sleep(20);const line=supervisor.captured().split('\n').find(value=>value.startsWith('{'));
    if(line)owner=JSON.parse(line).owner;
  }
  assert.ok(owner,'TEST supervisor published its owner lock');
  assert.equal(probeStoreOwner(owner),'live');
  const child=await f.start(f.spec('capture',f.project('native-v1'),{sourceStoreOwner:owner})).done;
  assert.equal(child.code,0,child.stdout+child.stderr);
  const store=f.store(),key=child.result.entries[0].contentKey;
  assert.equal(collect(store,{maxBytes:1,minAgeMs:0}).evicted.length,0,'capture child exit keeps the export lease');
  assert.ok(readStoreEntry(store,key,25));
  supervisor.kill('SIGKILL');await supervisor.done;
  assert.equal(probeStoreOwner(owner),'exited');
  assert.deepEqual(collect(store,{maxBytes:1,minAgeMs:0}).evicted.map(row=>row.key),[key]);
}));

test('a live reader protects its view and frames after its export supervisor is killed',()=>withStore(async f=>{
  const supervisor=f.start({role:'supervisor',cache:f.cache,events:f.events,label:'supervisor',holdMs:60000});
  let owner;
  for(let attempt=0;attempt<500&&!owner;attempt++){
    await sleep(20);const line=supervisor.captured().split('\n').find(value=>value.startsWith('{'));
    if(line)owner=JSON.parse(line).owner;
  }
  assert.ok(owner,'TEST supervisor published its owner lock');
  const reader=f.start(f.spec('reader',f.project('native-v1'),{sourceStoreOwner:owner,holdMs:60000}));
  await f.waitFor(row=>row.type==='acquired'&&row.label==='reader');
  const receipt=JSON.parse(fs.readFileSync(path.join(f.root,'work-reader/source-cache.json'),'utf8'));
  const store=f.store(),key=receipt.entries[0].contentKey;
  assert.notEqual(receipt.readerLease.owner,owner,'reader holds an independent kernel owner');
  supervisor.kill('SIGKILL');await supervisor.done;
  const kept=collect(store,{maxBytes:1,minAgeMs:0});
  assert.equal(kept.status,'collected');assert.equal(kept.liveLeases,1);assert.deepEqual(kept.evicted,[]);
  assert.ok(readStoreEntry(store,key,25));assert.ok(fs.existsSync(receipt.view));
  const frame=path.join(receipt.view,receipt.entries[0].pathName,'frame_00001.png');
  assert.match(fs.readFileSync(frame,'utf8'),/^TEST frame/,'reader view remains usable after export exit');
  reader.kill('SIGKILL');await reader.done;
  const collected=collect(store,{maxBytes:1,minAgeMs:0});
  assert.deepEqual(collected.evicted.map(row=>row.key),[key]);assert.ok(!fs.existsSync(receipt.view));
}));

test('an unchanged revision folder has zero misses; changed bytes at an unchanged path always miss',()=>withStore(async f=>{
  const first=await f.start(f.spec('first',f.project('native-v7'))).done;
  assert.equal(first.result.entries[0].outcome,'published-by-this-job');
  const revision=f.project('native-v8');
  const warm=await f.start(f.spec('warm',revision)).done;
  assert.equal(warm.code,0,warm.stdout+warm.stderr);
  assert.equal(warm.result.entries[0].outcome,'store-hit');assert.equal(extractions(f,'warm').length,0);
  assert.equal(warm.result.entries[0].contentKey,first.result.entries[0].contentKey);
  assert.notEqual(warm.result.entries[0].pathName,first.result.entries[0].pathName,'the SDK path key alone would have missed');
  const source=path.join(revision,'assets/source.mp4'),stat=fs.statSync(source);
  fs.writeFileSync(source,Buffer.from(fs.readFileSync(source)).reverse());fs.utimesSync(source,stat.atime,stat.mtime);
  assert.equal(fs.statSync(source).size,stat.size);
  const changed=await f.start(f.spec('changed',revision)).done;
  assert.equal(changed.code,0,changed.stdout+changed.stderr);
  assert.equal(changed.result.entries[0].outcome,'published-by-this-job');assert.equal(extractions(f,'changed').length,1);
  assert.notEqual(changed.result.entries[0].contentKey,first.result.entries[0].contentKey);
}));

test('a stale admitted digest can neither publish frames nor pass a mutation during decode',()=>withStore(async f=>{
  const directory=f.project('native-v1'),spec=f.spec('stale',directory);
  fs.appendFileSync(path.join(directory,'assets/source.mp4'),' TEST changed after admission');
  const stale=await f.start(spec).done;
  assert.equal(stale.code,1);assert.match(stale.result.error,/differ from the admitted digest; publication refused/);
  const mutated=await f.start(f.spec('mutated',f.project('native-v2'),{mutateSourceDuringDecode:true})).done;
  assert.equal(mutated.code,1);assert.match(mutated.result.error,/Native source changed during extraction/);
  assert.deepEqual(fs.readdirSync(f.store().entriesV2),[],'nothing unverifiable became shared');
}));

test('progress inventory counts only this job view, never a neighbour extraction',()=>withStore(async f=>{
  const store=f.store(),mine=storeViewPath(store,'/TEST/mine'),theirs=storeViewPath(store,'/TEST/theirs');
  for(const view of [mine,theirs])fs.mkdirSync(view,{recursive:true});
  const baseline=sourceFrameInventory(mine).identities;
  const partial=path.join(theirs,'hfcache-v4-0123456789abcdef.partial-1-TEST');fs.mkdirSync(partial);
  for(let index=1;index<=30;index++)fs.writeFileSync(path.join(partial,`frame_${String(index).padStart(5,'0')}.png`),'TEST');
  assert.equal(sourceFrameInventory(mine,baseline).frames,0);
  const own=path.join(mine,'hfcache-v4-fedcba9876543210.partial-2-TEST');fs.mkdirSync(own);
  fs.writeFileSync(path.join(own,'frame_00001.png'),'TEST');
  assert.equal(sourceFrameInventory(mine,baseline).frames,1);
}));

test('collection preserves legacy entries and partials whose Short readers have no store leases',()=>withStore(async f=>{
  const store=f.store(),old=Date.now()/1000-3*3600;
  const legacy=name=>{const dir=path.join(f.cache,name);fs.mkdirSync(dir);fs.writeFileSync(path.join(dir,'frame_00001.png'),'TEST'.repeat(64));
    fs.writeFileSync(path.join(dir,'.hf-complete'),'');return dir;};
  const aged=legacy('hfcache-v4-00000000000000aa'),fresh=legacy('hfcache-v4-00000000000000bb');
  fs.utimesSync(path.join(aged,'.hf-complete'),old,old);
  const partial=path.join(f.cache,'hfcache-v4-00000000000000cc.partial-9-TEST');fs.mkdirSync(partial);fs.utimesSync(partial,old,old);
  fs.symlinkSync(fresh,path.join(f.cache,'hfcache-v4-00000000000000dd'));
  const stats=collect(store,{maxBytes:1});
  assert.deepEqual(stats.evicted,[]);
  assert.equal(stats.legacyPartials,0);assert.equal(stats.legacyRootPreserved,true);
  for(const file of [aged,fresh,partial])assert.ok(fs.existsSync(file),'unleased legacy work is never collected');
  assert.ok(fs.lstatSync(path.join(f.cache,'hfcache-v4-00000000000000dd')).isSymbolicLink(),'alias links are not collected');
  const busy=fs.openSync(store.maintenance,fs.constants.O_RDWR|0x10|fs.constants.O_NONBLOCK);
  try{assert.equal(collect(store,{maxBytes:1}).status,'skipped-maintenance-busy');}
  finally{fs.closeSync(busy);}
}));

test('collection never removes a supervisor owner stub that may be between creation and locking',()=>withStore(async f=>{
  const store=f.store(),fresh=path.join(store.owners,'.fresh.creating'),abandoned=path.join(store.owners,'.abandoned.creating');
  for(const file of [fresh,abandoned])fs.writeFileSync(file,'');
  const old=Date.now()/1000-2*3600;fs.utimesSync(abandoned,old,old);
  const stats=collect(store,{maxBytes:64*1024**3});
  assert.equal(stats.exitedOwners,1);assert.ok(fs.existsSync(fresh));assert.ok(!fs.existsSync(abandoned));
}));

test('an unleased reader treats an entry removed mid-read as missing, never as corrupt',()=>withStore(async f=>{
  const published=await f.start(f.spec('first',f.project('native-v1'))).done;
  const store=f.store(),key=published.result.entries[0].contentKey,dir=path.join(store.entriesV2,key);
  const readdir=fs.readdirSync;
  mock.method(fs,'readdirSync',function(target,...rest){
    if(target===dir&&fs.existsSync(dir))fs.renameSync(dir,path.join(store.trash,'TEST-collected-mid-read'));
    return readdir.call(this,target,...rest);
  });
  try{assert.equal(readStoreEntry(store,key,25),null);}
  finally{mock.restoreAll();}
  fs.mkdirSync(dir);
  assert.throws(()=>readStoreEntry(store,key,25),/no publication record/,'a present inconsistent entry still fails closed');
}));

test('the render source-view step refuses to run outside the supervised render owner',()=>withStore(async f=>{
  const request=path.join(f.root,'export-request.json');
  fs.writeFileSync(request,JSON.stringify({project:f.project('native-v1'),output:path.join(f.root,'attempt'),cache:f.cache}));
  const environment={...process.env};delete environment.SNIPER_NATIVE_EXPORT_REQUEST;delete environment.SNIPER_NATIVE_EXPORT_OWNER;
  const child=spawn(process.execPath,[path.resolve('scripts/producer/studio/native_source_view.mjs'),request],{env:environment,stdio:'pipe'});
  let stderr='';child.stderr.on('data',data=>{stderr+=data;});
  const code=await new Promise(resolve=>child.on('close',resolve));
  assert.notEqual(code,0);assert.match(stderr,/Native export admission/);
  assert.equal(fs.existsSync(path.join(f.cache,'sniper-source-store-v1')),false,'nothing was leased or created');
}));

test('collection stops condemning and deleting at its caller deadline; the rest waits for the next run',()=>withStore(async f=>{
  const published=await f.start(f.spec('first',f.project('native-v1'))).done;
  const store=f.store(),key=published.result.entries[0].contentKey;
  for(const lease of fs.readdirSync(store.leases))fs.rmSync(path.join(store.leases,lease));
  fs.mkdirSync(path.join(store.trash,'TEST-leftover'));
  const stopped=collectStoreGarbage(store,{maxBytes:1,minAgeMs:0,until:performance.now()});
  assert.equal(stopped.stoppedAtDeadline,true);assert.deepEqual(stopped.evicted,[]);assert.equal(stopped.trashRemoved,0);
  const deferred=fs.readdirSync(store.trash);
  assert.equal(stopped.trashDeferred,deferred.length);assert.ok(deferred.includes('TEST-leftover'),'nothing was deleted after the deadline');
  assert.ok(readStoreEntry(store,key,25));
  const later=collect(store,{maxBytes:1,minAgeMs:0});
  assert.deepEqual(later.evicted.map(row=>row.key),[key]);assert.deepEqual(fs.readdirSync(store.trash),[]);
}));

test('a live lease protects its view under any spelling of the cache root',()=>withStore(async f=>{
  const reader=f.start(f.spec('reader',f.project('native-v1'),{holdMs:60000}));
  await f.waitFor(row=>row.type==='acquired'&&row.label==='reader');
  const store=f.store(),[name]=fs.readdirSync(store.leases),file=path.join(store.leases,name);
  const lease=JSON.parse(fs.readFileSync(file,'utf8'));
  fs.writeFileSync(file,JSON.stringify({...lease,view:path.join('/System/Volumes/Data',lease.view)}));
  const stats=collect(store,{maxBytes:64*1024**3});
  assert.equal(stats.views,0);assert.ok(fs.existsSync(lease.view),'the differently spelled live view survives');
  reader.kill('SIGKILL');await reader.done;
}));
