/** Structural SDK-boundary tests only: fake metadata/PNG bytes; no media process is launched. */
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {test} from 'node:test';
import {batchFixture} from './native_short_batched_render_fixture.mjs';
import {createNativeCaptureContext,prepareNativeCaptureContext} from '../producer/studio/native_short_capture_context.mjs';
import {nativeSourceCacheEntry,nativeSourceCacheIdentity,SEQUENTIAL_SOURCE_CACHE_MODE} from '../producer/studio/native_source_cache.mjs';

function cacheFixture() {
  const f=batchFixture(10);fs.rmSync(f.entry,{recursive:true});
  f.request.sourceCacheMode=SEQUENTIAL_SOURCE_CACHE_MODE;
  f.videos=[f.video];f.extractions=[];f.publications=0;f.active=0;f.maximum=0;
  const compile=f.sdk.runCompileStage;
  f.sdk.runCompileStage=async options=>{
    const result=await compile(options);result.composition.videos=f.videos;return result;
  };
  f.sdk.isHdrColorSpace=value=>value?.colorTransfer==='smpte2084';
  f.sdk.extractAllVideoFrames=async(...args)=>{
    f.active++;f.maximum=Math.max(f.active,f.maximum);f.extractions.push(args);
    try{await new Promise(resolve=>setTimeout(resolve,1));return fakePublication(f,args);}
    finally{f.active--;}
  };
  f.context=()=>createNativeCaptureContext(f.request,path.join(f.request.output,'work'),f.sdk);
  return f;
}

function fakePublication(f, args) {
  const [videos,,options,,config]=args,video=videos[0];
  if(f.failId===video.id)return {success:false,errors:[{videoId:video.id,error:'TEST decode failure'}],extracted:[]};
  const context={project:f.request.project,request:{cache:config.extractCacheDir},fps:options.fps,rate:25};
  const {entry}=nativeSourceCacheIdentity(context,video);
  if(fs.existsSync(path.join(entry,'.hf-complete'))){
    const now=new Date();fs.utimesSync(path.join(entry,'.hf-complete'),now,now);
    const cached=nativeSourceCacheEntry(context,video);
    return {success:true,errors:[],phaseBreakdown:{cacheMisses:0,cacheHits:1},durationMs:1,
      extracted:[{videoId:video.id,outputDir:entry,framePaths:cached.framePaths,totalFrames:cached.names.length}]};
  }
  f.publications++;fs.mkdirSync(entry);
  fs.writeFileSync(path.join(entry,'.hf-complete'),'TEST SDK publication seam');
  const framePaths=new Map();
  for(let index=0;index<Math.round((video.end-video.start)*25);index++){
    const file=path.join(entry,`frame_${String(index+1).padStart(5,'0')}.png`);
    fs.writeFileSync(file,`TEST source PNG ${index}`);framePaths.set(index,file);
  }
  if(f.missingFrame)fs.rmSync(framePaths.get(1));
  if(f.changedWindow)video.mediaStart+=1;
  f.afterPublication?.();
  return {success:true,errors:[],phaseBreakdown:{cacheMisses:1,cacheHits:0},durationMs:1,
    extracted:[{videoId:video.id,outputDir:entry,framePaths,totalFrames:framePaths.size}]};
}

async function withFixture(run) {
  const f=cacheFixture();try{await run(f);}finally{f.cleanup();}
}

test('cold caches use one awaited SDK video at a time and reuse duplicate exact views',()=>withFixture(async f=>{
  f.videos.push({...f.video,id:'duplicate-view'},{...f.video,id:'later-range',mediaStart:1,end:.2});
  const source2=path.join(f.request.project,'assets/web.mp4');fs.writeFileSync(source2,'TEST web video');
  f.videos.push({...f.video,id:'real-web-context',src:'assets/web.mp4'});
  const context=await f.context();await prepareNativeCaptureContext(context);
  assert.equal(f.extractions.length,4);assert.equal(f.publications,3);assert.equal(f.maximum,1);
  assert.deepEqual(context.sourceCacheAcquisition.entries.map(row=>row.status),
    ['sdk-published-exact-cache','exact-cache-hit','sdk-published-exact-cache','sdk-published-exact-cache']);
  assert.equal(context.sourceCacheAcquisition.sources.length,2);
  assert.equal(context.cacheEntries.length,4);assert.equal(context.sourceCacheAcquisition.status,'exact-source-caches-ready');
  for(const [videos,base,options,signal,config,compiled] of f.extractions){
    assert.equal(videos.length,1);assert.equal(base,f.request.project);assert.equal(options.format,'png');
    assert.deepEqual(options.fps,{num:25,den:1});assert.equal(options.maxTransientRetries,0);
    assert.equal(options.timelineEnd,.4);assert.equal(options.collectProbeFailures,true);
    assert.equal(signal,undefined);assert.equal(config.extractCacheDir,f.request.cache);
    assert.equal(compiled,path.join(context.work,'compiled'));assert.equal('width' in options,false);assert.equal('height' in options,false);
  }
  assert.ok(context.cacheEntries.every(row=>row.width===3840&&row.height===2160));
  assert.equal(f.calls.sessions.length,0);assert.equal(f.calls.encodes.length,0);
}));

test('existing-only remains a cache-miss failure with no extraction fallback',()=>withFixture(async f=>{
  delete f.request.sourceCacheMode;
  await assert.rejects(()=>f.context().then(prepareNativeCaptureContext),/Exact native source frame cache missing/);
  assert.equal(f.extractions.length,0);assert.equal(f.calls.sessions.length,0);
}));

test('ordinary streaming preflight acquires exact cold SDK source frames before browser capture',()=>withFixture(async f=>{
  f.request.sourceCacheMode='acquire-sdk-preflight';f.request.captureMode='sdk-streaming';
  const context=await f.context();await prepareNativeCaptureContext(context);
  assert.equal(f.extractions.length,1);assert.equal(f.calls.sessions.length,0);
  assert.equal(f.calls.encodes.length,0);assert.equal(context.sourceCacheAcquisition.status,'exact-source-caches-ready');
  assert.deepEqual(f.extractions[0][0],[f.video]);
  assert.ok(context.cacheEntries.every(row=>row.width===3840&&row.height===2160));
}));

test('streaming preflight refuses mutated SDK windows and incomplete retained caches',async()=>{
  await withFixture(async f=>{
    f.request.sourceCacheMode='acquire-sdk-preflight';f.changedWindow=true;
    await assert.rejects(()=>f.context().then(prepareNativeCaptureContext),/changed source timing/);
    assert.equal(f.calls.sessions.length,0);
  });
  await withFixture(async f=>{
    f.request.sourceCacheMode='acquire-sdk-preflight';fs.mkdirSync(f.entry);
    fs.writeFileSync(path.join(f.entry,'retain.txt'),'TEST partial cache');
    await assert.rejects(()=>f.context().then(prepareNativeCaptureContext),/must be preserved/);
    assert.equal(f.extractions.length,0);
  });
});

test('unknown modes and cold acquisition without batch mode reject before extraction',async()=>{
  await withFixture(async f=>{
    f.request.sourceCacheMode='automatic-unqualified-fallback';
    await assert.rejects(()=>f.context().then(prepareNativeCaptureContext),/Unsupported source cache/);
    assert.equal(f.extractions.length,0);
  });
  await withFixture(async f=>{
    f.request.captureMode='sdk-streaming';
    await assert.rejects(()=>f.context().then(prepareNativeCaptureContext),/explicit bounded native batches/);
    assert.equal(f.extractions.length,0);
  });
});

test('all sources are checked for HDR before the first source extraction starts',()=>withFixture(async f=>{
  const second=path.join(f.request.project,'assets/hdr.mp4');fs.writeFileSync(second,'TEST HDR source');
  f.videos.push({...f.video,id:'hdr-view',src:'assets/hdr.mp4'});
  f.sdk.extractMediaMetadata=async source=>({width:3840,height:2160,colorSpace:{colorTransfer:source===second?'smpte2084':'bt709'}});
  await assert.rejects(()=>f.context().then(prepareNativeCaptureContext),/does not admit HDR/);
  assert.equal(f.extractions.length,0);
  const receipt=JSON.parse(fs.readFileSync(path.join(f.request.output,'work/source-cache.json')));
  assert.equal(receipt.status,'failed');assert.equal(receipt.sources.length,1);
}));

test('first SDK error stops later extractions and retains its exact failure receipt',()=>withFixture(async f=>{
  f.failId=f.video.id;f.videos.push({...f.video,id:'later-range',mediaStart:1});
  await assert.rejects(()=>f.context().then(prepareNativeCaptureContext),/SDK source extraction failed/);
  assert.equal(f.extractions.length,1);assert.equal(f.calls.sessions.length,0);
  const receipt=JSON.parse(fs.readFileSync(path.join(f.request.output,'work/source-cache.json')));
  assert.equal(receipt.status,'failed');assert.equal(receipt.entries[0].sdkResult.errors[0].error,'TEST decode failure');
}));

test('an aged warm hit receives SDK touch before a later miss can run ordinary cache GC',()=>withFixture(async f=>{
  fakePublication(f,[[f.video],f.request.project,{fps:{num:25,den:1}},undefined,{extractCacheDir:f.request.cache}]);
  const marker=path.join(f.entry,'.hf-complete'),old=new Date(Date.now()-2*60*60*1000);fs.utimesSync(marker,old,old);
  f.videos.push({...f.video,id:'later-cold-range',mediaStart:1});
  f.afterPublication=()=>{
    if(Date.now()-fs.statSync(marker).mtimeMs>=60*60*1000)fs.rmSync(f.entry,{recursive:true});
  };
  const context=await f.context();await prepareNativeCaptureContext(context);
  assert.equal(f.extractions.length,2);assert.ok(fs.existsSync(marker));
  assert.equal(context.sourceCacheAcquisition.entries[0].status,'exact-cache-hit');
  assert.equal(context.sourceCacheAcquisition.entries[0].sdkResult.phaseBreakdown.cacheHits,1);
}));

test('partial existing entries and incomplete SDK publication cannot become approved cache hits',async()=>{
  await withFixture(async f=>{
    fs.mkdirSync(f.entry);fs.writeFileSync(path.join(f.entry,'diagnostic.txt'),'TEST retain me');
    await assert.rejects(()=>f.context().then(prepareNativeCaptureContext),/must be preserved/);
    assert.equal(f.extractions.length,0);assert.equal(fs.readFileSync(path.join(f.entry,'diagnostic.txt'),'utf8'),'TEST retain me');
  });
  await withFixture(async f=>{
    f.missingFrame=true;
    await assert.rejects(()=>f.context().then(prepareNativeCaptureContext),/Incomplete native source cache/);
    assert.equal(f.extractions.length,1);assert.equal(f.calls.sessions.length,0);
    assert.ok(fs.existsSync(path.join(f.entry,'.hf-complete')));
  });
});

test('window clamping or nonlocal, looping and accelerated inputs fail explicitly',async()=>{
  await withFixture(async f=>{
    f.changedWindow=true;
    await assert.rejects(()=>f.context().then(prepareNativeCaptureContext),/changed the requested extraction window/);
  });
  for(const change of [{src:'https://example.com/video.mp4'},{src:'../outside.mp4'},{loop:true},{playbackRate:2}])await withFixture(async f=>{
    Object.assign(f.video,change);
    await assert.rejects(()=>f.context().then(prepareNativeCaptureContext));assert.equal(f.extractions.length,0);
  });
});

test('cache identity matches the installed SDK canonical blob for integer and rational clocks',()=>withFixture(async f=>{
  const sdk=fs.readFileSync('templates/motion/node_modules/hyperframes/dist/cli.js','utf8');
  const start=sdk.indexOf('function canonicalKeyBlob('),end=sdk.indexOf('\nfunction computeCacheKey(',start);
  assert.ok(start>0&&end>start);const sandbox={};
  vm.runInNewContext(sdk.slice(start,end)+';this.blob=canonicalKeyBlob;',sandbox,{timeout:1000});
  for(const fps of [{num:25,den:1},{num:30000,den:1001}]){
    const context={project:f.request.project,request:f.request,fps,rate:fps.num/fps.den};
    const identity=nativeSourceCacheIdentity(context,{...f.video,mediaStart:23.76}),b=identity.keyBlob;
    const expected=sandbox.blob({videoPath:b.p,mtimeMs:b.m,size:b.s,mediaStart:b.ms,duration:b.d,fps:b.f,format:b.fmt,transform:b.t});
    assert.equal(JSON.stringify(b),expected);
    assert.equal(path.basename(identity.entry),'hfcache-v4-'+createHash('sha256').update(expected).digest('hex').slice(0,16));
  }
}));

test('adapter exposes the same qualified extraction primitives in the CLI and capture library',()=>{
  const manifest=JSON.parse(fs.readFileSync('scripts/producer/studio/runtime/patches.json'));
  const stock=fs.readFileSync('templates/motion/node_modules/hyperframes/dist/cli.js');
  const hash=bytes=>createHash('sha256').update(bytes).digest('hex');
  const apply=(bytes,row)=>{
    assert.equal(hash(bytes),row.baseSha256);
    for(const patch of [...row.patches].reverse())bytes=Buffer.concat([bytes.subarray(0,patch.offset),Buffer.from(patch.text),bytes.subarray(patch.offset+patch.remove)]);
    assert.equal(hash(bytes),row.sha256);return bytes;
  };
  const cliRow=manifest.files.find(row=>row.file==='cli.js'),cli=apply(stock,cliRow);
  assert.equal(hash(cli),'e565a6640e071d4abac38d7601e0ad0faa7cab9284abd73127f014e29b74afb9');
  const libraryRow=manifest.files.find(row=>row.file==='native-capture-library.mjs'),library=apply(cli,libraryRow);
  const patch=libraryRow.patches[0];assert.deepEqual(library.subarray(0,patch.offset),cli.subarray(0,patch.offset));
  assert.match(library.subarray(patch.offset).toString(),/export \{[^}]*extractAllVideoFrames, isHdrColorSpace,/);
});
