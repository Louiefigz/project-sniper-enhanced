/** Tiny fake PNG/source evidence only; no capture, decoding, extraction or encoding. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {test,mock} from 'node:test';
import {batchFixture} from './native_short_batched_render_fixture.mjs';
import {nativeCaptureHash} from '../producer/studio/native_short_capture_context.mjs';
import {nativeSourceCacheEntry} from '../producer/studio/native_source_cache.mjs';
import {NativeFrameTransport} from '../producer/studio/runtime/frame-source-transport.mjs';
import {observedFile,planAliases,publishAliases,executeAliasRequest} from '../producer/studio/source_cache_alias.mjs';

async function fixture(run) {
  const f=batchFixture(5),current=path.join(f.root,'project-audio-02');
  fs.cpSync(f.request.project,current,{recursive:true});
  f.aliasRequest={schemaVersion:1,root:f.request.output,project:current,donorProject:f.request.project,
    cache:f.request.cache,donorCache:f.request.cache,runtime:f.request.runtime,pins:{}};
  for(const project of [current,f.request.project])for(const name of ['assets/source.mp4','index.html','SHORT-PROJECT.json']){
    const file=path.join(project,name);f.aliasRequest.pins[file]=nativeCaptureHash(file);
  }
  f.aliasPlan=()=>planAliases(f.aliasRequest,f.plan,[f.video]);
  try{await run(f);}finally{mock.restoreAll();f.cleanup();}
}

test('exact new-path key aliases original frames without copying or creating marker bytes',()=>fixture(async f=>{
  const plan=await f.aliasPlan(),row=plan.entries[0],before=fs.readdirSync(row.sourceEntry).map(name=>[name,nativeCaptureHash(path.join(row.sourceEntry,name))]);
  assert.notEqual(row.targetEntry,row.sourceEntry);const result=await publishAliases(plan);
  assert.equal(result[0].method,'created-directory-alias');assert.ok(fs.lstatSync(row.targetEntry).isSymbolicLink());
  assert.equal(fs.realpathSync(row.targetEntry),row.sourceEntry);
  assert.deepEqual(before,fs.readdirSync(row.sourceEntry).map(name=>[name,nativeCaptureHash(path.join(row.sourceEntry,name))]));
  const context={project:f.aliasRequest.project,request:{cache:f.aliasRequest.cache},fps:{num:25,den:1},rate:25};
  assert.equal(nativeSourceCacheEntry(context,f.video).names.length,5);
  const again=await publishAliases(await f.aliasPlan());assert.equal(again[0].method,'existing-exact-alias');
}));

test('real frame transport admits directory alias and rejects an escaped child or replaced link',()=>fixture(async f=>{
  const plan=await f.aliasPlan(),row=plan.entries[0];await publishAliases(plan);
  const transport=new NativeFrameTransport();transport.report=()=>{};transport.configure([row.targetEntry]);
  const frame=path.join(row.targetEntry,'frame_00001.png');assert.match(transport.resolve(frame),/^\/__sniper_native_frame\//);
  const other=path.join(f.root,'other');fs.mkdirSync(other);fs.unlinkSync(row.targetEntry);fs.symlinkSync(other,row.targetEntry);
  assert.throws(()=>transport.resolve(frame));transport.close();
}));

test('duplicate extraction windows share one alias and source hashes',()=>fixture(async f=>{
  const plan=await planAliases(f.aliasRequest,f.plan,[f.video,{...f.video,id:'another-view'}]);
  assert.equal(plan.entries.length,1);assert.equal(plan.sources.length,2);
  assert.deepEqual(plan.entries[0].videoIds,['source-0-0','another-view']);
}));

test('source replacement, different bytes, missing pins and escaped source fail before alias',async()=>{
  for(const mode of ['bytes','pin','escape','replace'])await fixture(async f=>{
    const file=path.join(f.aliasRequest.project,'assets/source.mp4');
    if(mode==='bytes')fs.writeFileSync(file,'TEST different pixels');
    if(mode==='pin')delete f.aliasRequest.pins[file];
    if(mode==='escape')f.video.src='../project/assets/source.mp4';
    const plan=mode==='replace'?await f.aliasPlan():null;
    if(mode==='replace'){const bytes=fs.readFileSync(file);fs.unlinkSync(file);fs.writeFileSync(file,bytes);}
    await assert.rejects(()=>plan?publishAliases(plan):f.aliasPlan());
  });
});

test('incomplete, aliased, extra or mutated source frames cannot qualify',async()=>{
  for(const mode of ['gap','symlink','extra','mutate','marker'])await fixture(async f=>{
    const first=path.join(f.entry,'frame_00001.png'),plan=mode==='mutate'?await f.aliasPlan():null;
    if(mode==='gap')fs.unlinkSync(first);
    if(mode==='symlink'){fs.unlinkSync(first);fs.symlinkSync(path.join(f.entry,'frame_00002.png'),first);}
    if(mode==='extra')fs.writeFileSync(path.join(f.entry,'frame_bogus.png'),'TEST extra');
    if(mode==='mutate')fs.writeFileSync(first,'TEST changed PNG');
    if(mode==='marker')fs.unlinkSync(path.join(f.entry,'.hf-complete'));
    await assert.rejects(async()=>{const current=plan??await f.aliasPlan();await publishAliases(current);});
  });
});

test('conflicting target or dangling alias is preserved without overwrite',async()=>{
  for(const mode of ['directory','dangling','other-alias'])await fixture(async f=>{
    const plan=await f.aliasPlan(),row=plan.entries[0];
    if(mode==='directory')fs.mkdirSync(row.targetEntry);
    else fs.symlinkSync(mode==='dangling'?path.join(f.root,'absent'):f.request.cache,row.targetEntry);
    const before=fs.lstatSync(row.targetEntry).ino;
    await assert.rejects(()=>publishAliases(plan),/Conflicting/);
    assert.equal(fs.lstatSync(row.targetEntry).ino,before);
  });
});

test('the worker invokes only existing SDK compilation and retains bounded evidence',()=>fixture(async f=>{
  const sdk={...f.sdk,extractAllVideoFrames:()=>assert.fail('must not extract'),extractMediaMetadata:()=>assert.fail('must not probe')};
  const result=await executeAliasRequest(f.aliasRequest,sdk);
  assert.equal(result.status,'source-cache-aliases-prepared');assert.equal(result.additionalSourceExtractions,0);
  assert.equal(f.calls.compiles.length,1);assert.equal(f.calls.sessions.length,0);assert.equal(f.calls.encodes.length,0);
  const plan=JSON.parse(fs.readFileSync(path.join(f.aliasRequest.root,'alias-plan.json')));
  assert.equal(plan.entries[0].frames.length,5);assert.equal(result.aliasPlanSha256,nativeCaptureHash(path.join(f.aliasRequest.root,'alias-plan.json')));
}));


test('every standalone observation yields and rehashes, without memoizing prior reads',()=>fixture(async f=>{
  const file=path.join(f.root,'hash-fixture.bin'),bytes=Buffer.alloc(3*1024*1024+17,71);
  fs.writeFileSync(file,bytes);const expected=nativeCaptureHash(file),stream=fs.createReadStream;let reads=0;
  mock.method(fs,'createReadStream',function(source,options){
    if(source===file){reads++;assert.equal(options.highWaterMark,1024*1024);}
    return stream.call(this,source,options);
  });
  for(let pass=0;pass<2;pass++){
    let yielded=false;setImmediate(()=>{yielded=true;});const observed=await observedFile(file);
    assert.ok(yielded,'Alias hashing must service child-exit callbacks');assert.equal(observed.sha256,expected);
  }
  assert.equal(reads,2,'Each qualification must perform a fresh bounded read');
}));

test('standalone observation rejects mutation while an asynchronous read is pending',()=>fixture(async f=>{
  const file=path.join(f.root,'mutating-fixture.bin');fs.writeFileSync(file,Buffer.alloc(3*1024*1024,71));
  const stream=fs.createReadStream;
  mock.method(fs,'createReadStream',function(source,options){
    const result=stream.call(this,source,options);
    if(source===file)result.once('data',()=>fs.appendFileSync(file,' mutation'));
    return result;
  });
  await assert.rejects(()=>observedFile(file),/changed during hashing|changed while hashed/);
}));
