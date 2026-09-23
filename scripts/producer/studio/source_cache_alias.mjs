/** Alias byte-identical staged sources to retained exact SDK frame directories. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {pathToFileURL} from 'node:url';
import {nativeCaptureHash,nativeCaptureSourceHash} from './native_short_capture_context.mjs';
import {nativeSourceCacheIdentity,nativeSourceCacheEntry} from './native_source_cache.mjs';

const MAX_FRAME_BYTES=64*1024*1024;

function identity(file) {
  const stat=fs.lstatSync(file,{bigint:true});
  assert.ok(stat.isFile()&&!stat.isSymbolicLink()&&fs.realpathSync(file)===file,'Alias evidence must be a canonical regular file');
  return Object.fromEntries(['dev','ino','size','mtimeNs','ctimeNs'].map(key=>[key,String(stat[key])]));
}

/** Hash retained pixels in bounded memory, checking exact file identity around the read. */
export async function observedFile(file, maximum=MAX_FRAME_BYTES, allowEmpty=false) {
  const before=identity(file);assert.ok(BigInt(before.size)<=BigInt(maximum)
    &&(allowEmpty||BigInt(before.size)>0n),'Alias evidence is empty or exceeds its byte bound');
  const sha256=await nativeCaptureSourceHash({},file);assert.deepEqual(identity(file),before,'Alias evidence changed while hashed');
  return {path:file,sha256,identity:before};
}

function sourcePair(request, video) {
  assert.ok(typeof video.src==='string'&&!/^[a-z][a-z0-9+.-]*:|^\/\//i.test(video.src),'Alias requires local staged video');
  const current=path.resolve(request.project,video.src),original=path.resolve(request.donorProject,video.src);
  for(const [file,root] of [[current,request.project],[original,request.donorProject]]){
    assert.ok(file.startsWith(root+path.sep)&&fs.realpathSync(file)===file,'Alias source escaped its project');
    assert.match(request.pins[file]??'',/^[a-f0-9]{64}$/,'Alias source has no admitted hash');
  }
  assert.equal(request.pins[current],request.pins[original],'Staged source bytes differ');
  return {current,original};
}

function contexts(request, plan) {
  const [num,den]=plan.canvas.frameRate.split('/').map(Number),rate=num/den;
  assert.ok(Number.isSafeInteger(num)&&Number.isSafeInteger(den)&&den>0&&rate>=1&&rate<=60,'Invalid alias frame clock');
  return {current:{project:request.project,request:{cache:request.cache},fps:{num,den},rate},
    original:{project:request.donorProject,request:{cache:request.donorCache},fps:{num,den},rate}};
}

async function observeSources(sources, pair, request) {
  for(const file of [pair.current,pair.original]){
    if(sources.has(file))continue;
    const source=await observedFile(file,1024**4);assert.equal(source.sha256,request.pins[file],'Admitted source changed');sources.set(file,source);
  }
}

/** Admit all source/pixel pairs before creating the first cache alias. */
export async function planAliases(request, plan, videos) {
  const context=contexts(request,plan),sources=new Map(),rows=new Map();
  for(const video of videos){
    assert.ok([video.start,video.end,video.mediaStart].every(Number.isFinite)&&video.start>=0&&video.end>video.start
      &&video.end<=plan.canvas.totalFrames/context.current.rate&&video.mediaStart>=0
      &&!video.loop&&(video.playbackRate===undefined||video.playbackRate===1),'Unsupported alias video window');
    const pair=sourcePair(request,video);
    await observeSources(sources,pair,request);
    const from=nativeSourceCacheEntry(context.original,video),to=nativeSourceCacheIdentity(context.current,video);
    assert.equal(fs.realpathSync(from.entry),from.entry,'Original SDK entry must be canonical, not another alias');
    const withoutLocation=blob=>Object.fromEntries(Object.entries(blob).filter(([key])=>!['p','m'].includes(key)));
    assert.deepEqual(withoutLocation(from.keyBlob),withoutLocation(to.keyBlob),'SDK extraction clock/transform differs');
    if(rows.has(to.entry)){assert.equal(rows.get(to.entry).sourceEntry,from.entry);rows.get(to.entry).videoIds.push(video.id);continue;}
    const marker=await observedFile(path.join(from.entry,'.hf-complete'),1024*1024,true);
    const frames=[];
    for(const name of from.names)frames.push(await observedFile(path.join(from.entry,name)));
    rows.set(to.entry,{targetEntry:to.entry,sourceEntry:from.entry,originalKey:from.keyBlob,currentKey:to.keyBlob,
      videoIds:[video.id],marker,frames,sourceDirectoryIdentity:directoryIdentity(from.entry)});
  }
  assert.ok(rows.size>0,'Alias plan has no native videos');
  return {schemaVersion:1,scope:'byte-identical-SDK-source-cache-directory-alias',sources:[...sources.values()],entries:[...rows.values()]};
}

function directoryIdentity(directory) {
  const stat=fs.lstatSync(directory,{bigint:true});
  assert.ok(stat.isDirectory()&&!stat.isSymbolicLink()&&fs.realpathSync(directory)===directory,'Original SDK frame directory changed');
  return {device:String(stat.dev),inode:String(stat.ino)};
}

async function verifyEntry(row) {
  assert.deepEqual(directoryIdentity(row.sourceEntry),row.sourceDirectoryIdentity,'Original SDK directory was replaced');
  const names=fs.readdirSync(row.sourceEntry).filter(name=>/^frame_\d{5}\.png$/.test(name)).sort();
  assert.deepEqual(names,row.frames.map(frame=>path.basename(frame.path)),'Retained SDK frame inventory changed');
  assert.ok(fs.readdirSync(row.sourceEntry).every(name=>!name.startsWith('frame')||names.includes(name)),
    'Unexpected frame-like SDK cache artifact');
  assert.deepEqual(await observedFile(row.marker.path,1024*1024,true),row.marker,'Retained SDK marker changed');
  for(const file of row.frames)assert.deepEqual(await observedFile(file.path),file,'Retained SDK frame bytes changed');
}

function aliasState(row) {
  if(row.targetEntry===row.sourceEntry)return 'same-entry';
  if(!fs.existsSync(row.targetEntry)&&!fs.lstatSync(row.targetEntry,{throwIfNoEntry:false}))return 'missing';
  const stat=fs.lstatSync(row.targetEntry);
  assert.ok(stat.isSymbolicLink()&&fs.readlinkSync(row.targetEntry)===row.sourceEntry
    &&fs.realpathSync(row.targetEntry)===row.sourceEntry,'Conflicting cache entry or alias must be preserved');
  return 'existing-exact-alias';
}

/** Create only missing directory links, retaining original SDK markers and pixels unchanged. */
export async function publishAliases(plan) {
  for(const file of plan.sources)assert.deepEqual(await observedFile(file.path,1024**4),file,'Source changed before alias publication');
  for(const row of plan.entries){await verifyEntry(row);aliasState(row);}
  const aliases=[];
  for(const row of plan.entries){
    const state=aliasState(row);
    if(state==='missing')fs.symlinkSync(row.sourceEntry,row.targetEntry,'dir');
    await verifyEntry(row);assert.notEqual(aliasState(row),'missing');
    const link=fs.lstatSync(row.targetEntry,{bigint:true});
    aliases.push({targetEntry:row.targetEntry,sourceEntry:row.sourceEntry,method:state==='missing'?'created-directory-alias':state,
      videoIds:row.videoIds,frameCount:row.frames.length,linkIdentity:{device:String(link.dev),inode:String(link.ino)}});
  }
  for(const file of plan.sources)assert.deepEqual(await observedFile(file.path,1024**4),file,'Source changed during alias publication');
  return aliases;
}

async function verifyPins(pins) {
  for(const [file,sha] of Object.entries(pins))assert.equal(await nativeCaptureSourceHash({},file),sha,`Alias input changed: ${file}`);
}

/** Use the frozen SDK parser for actual extraction descriptors, never a second timing parser. */
export async function executeAliasRequest(request, sdkOverride) {
  await verifyPins(request.pins);
  assert.equal(fs.realpathSync(request.cache),request.cache);assert.equal(fs.realpathSync(request.donorCache),request.donorCache);
  const sdk=sdkOverride??await import(pathToFileURL(path.join(request.runtime,'dist/native-capture-library.mjs')).href);
  const plan=JSON.parse(fs.readFileSync(path.join(request.project,'SHORT-PROJECT.json'),'utf8'));
  const {fps,rate}=contexts(request,plan).current;
  const work=path.join(request.root,'compile');fs.mkdirSync(work);
  const cfg=sdk.resolveConfig({browserGpuMode:'software',forceScreenshot:true,lowMemoryMode:true,enableBrowserPool:false});
  const log=Object.fromEntries(['info','warn','error','debug'].map(name=>[name,(...args)=>console.log(name,...args)]));
  const compiled=await sdk.runCompileStage({projectDir:request.project,workDir:work,
    htmlPath:path.join(request.project,'index.html'),entryFile:'index.html',
    job:{config:{fps,quality:'high',format:'mp4',workers:1}},cfg,needsAlpha:false,log,assertNotAborted:()=>{},failClosedFontFetch:true});
  assert.equal(compiled.composition.width,1080);assert.equal(compiled.composition.height,1920);
  assert.equal(compiled.composition.duration,plan.canvas.totalFrames/rate);
  console.log('Alias phase: SDK compilation completed; qualifying source and frame bytes');
  const aliasPlan=await planAliases(request,plan,compiled.composition.videos);
  fs.writeFileSync(path.join(request.root,'alias-plan.json'),JSON.stringify(aliasPlan,null,2),{flag:'wx'});
  await verifyPins(request.pins);
  console.log('Alias phase: all source and frame pairs admitted; publishing exact directory aliases');
  const aliases=await publishAliases(aliasPlan);await verifyPins(request.pins);
  const receipt={schemaVersion:1,status:'source-cache-aliases-prepared',aliases,
    aliasPlanSha256:nativeCaptureHash(path.join(request.root,'alias-plan.json')),additionalSourceExtractions:0,
    additionalPictureEncodes:0,sourceAndFrameBytesUnchangedDuringWorker:true,finalNativeEncodedQcStillRequired:true,
    frameHashObservationScope:'Observed before and after alias creation inside the owned worker; not rehashed after owned cleanup.',
    provenance:'Existing SDK key/marker/consecutive inventory admitted; frame hashes are current observations, not historical SDK signatures.'};
  fs.writeFileSync(path.join(request.root,'result.json'),JSON.stringify(receipt,null,2),{flag:'wx'});
  return receipt;
}

if(process.argv[1]&&pathToFileURL(path.resolve(process.argv[1])).href===import.meta.url){
  const request=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
  console.log(JSON.stringify(await executeAliasRequest(request)));
}
