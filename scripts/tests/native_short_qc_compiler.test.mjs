/** Compiler reuse tests use an in-memory SDK and tiny files; no browser/probe/media process runs. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {deserialize} from 'node:v8';
import {test} from 'node:test';
import {batchFixture} from './native_short_batched_render_fixture.mjs';
import {runNativeBatchedRender} from '../producer/studio/native_short_batched_render.mjs';
import {planNativeShortQc,captureNativeShortQcChunk,finishNativeShortQc} from '../producer/studio/native_short_qc_phase.mjs';
import {serializeCompilerResult} from '../producer/studio/native_short_qc_compiler.mjs';

const read=file=>JSON.parse(fs.readFileSync(file,'utf8'));
const planRoot=f=>path.join(f.request.output,'native-qc-phases/plan');
const scheduleFile=f=>path.join(f.request.output,'native-qc-phases/schedule.json');
const chunk=(f,p,index=0)=>captureNativeShortQcChunk(f.request,{index,expectedScheduleSha256:p.scheduleSha256},{sdk:f.sdk});

async function withPicture(action, maximum=4) {
  const f=batchFixture(80);
  f.sdk.extractMediaMetadata=async()=>maximum===1?{width:20000,height:20000}:{width:12000,height:8000};
  try {
    const result=await runNativeBatchedRender(f.request,{sdk:f.sdk,encode:f.encode});
    assert.equal(result.status,'picture-encoded-awaiting-parent-qc',result.error);await action(f);
  }finally{f.cleanup();}
}

function compilerWithDependencies(f) {
  const compile=f.sdk.runCompileStage,originalCapture=f.sdk.createCaptureSession,lookup=f.sdk.createFrameLookupTable;
  const state={compiles:0,captures:0,metadata:0,results:[]};
  const metadata=f.sdk.extractMediaMetadata;
  f.sdk.extractMediaMetadata=async(...args)=>{state.metadata++;return metadata(...args);};
  fs.writeFileSync(path.join(f.request.project,'styles.css'),'project fallback css');
  f.sdk.runCompileStage=async input=>{
    const result=await compile(input);state.compiles++;
    fs.mkdirSync(path.join(input.workDir,'compiled/sub'));fs.mkdirSync(path.join(input.workDir,'downloads'));
    fs.writeFileSync(path.join(input.workDir,'compiled/sub/index.html'),'sub composition');
    const downloaded=path.join(input.workDir,'downloads/font.woff');fs.writeFileSync(downloaded,'downloaded bytes');
    const shared=[undefined,{id:'shared'}];input.cfg.changedByCompiler=true;
    result.compiled={externalAssets:new Map([['fonts/font.woff',downloaded]]),subCompositions:new Map([['sub/index.html','sub composition']])};
    result.alias=shared;result.shared=new Map([['same',shared]]);result.cfg=input.cfg;input.cfg.shared=shared;
    result.compiled.videos=result.composition.videos;state.results.push(result);return result;
  };
  f.sdk.createFrameLookupTable=(videos,...args)=>{assert.deepEqual(videos,[f.video]);return lookup(videos,...args);};
  f.sdk.createCaptureSession=async(url,directory,options,injector,cfg)=>{
    assert.equal(cfg.changedByCompiler,true);assert.equal(cfg.shared[0],undefined);state.captures++;return originalCapture(url,directory,options,injector,cfg);
  };
  return state;
}

test('V8 compiler snapshot preserves Maps, undefined, sparse arrays, cycles and shared aliases',()=>{
  const shared=[undefined,{a:1}],value={shared,map:new Map([['shared',shared]]),sparse:new Array(3)};
  value.self=value;Object.defineProperty(value,'__proto__',{value:'ordinary own property',enumerable:true,writable:true,configurable:true});
  const decoded=deserialize(serializeCompilerResult(value));
  assert.deepEqual(decoded,value);assert.equal(decoded.shared,decoded.map.get('shared'));assert.equal(decoded.self,decoded);
  assert.equal(Object.getPrototypeOf(decoded),Object.prototype);assert.equal(Object.hasOwn(decoded,'__proto__'),true);
});

for(const [label,value] of [['function',()=>{}],['symbol',Symbol('unsupported')],['null prototype',Object.create(null)]])test(`unsupported compiler ${label} fails serialization`,()=>{
  assert.throws(()=>serializeCompilerResult(value));
});

test('one actual compiler call feeds every phase with full cfg, Maps, paths and byte-exact files',()=>withPicture(async f=>{
  const state=compilerWithDependencies(f),planned=await planNativeShortQc(f.request,{sdk:f.sdk});
  assert.equal(state.compiles,1);assert.ok(planned.compilerPins[path.join(planRoot(f),'compiler-result.bin')]);
  assert.ok(planned.compilerPins[path.join(planRoot(f),'compiled/index.html')]);
  const record=read(path.join(planRoot(f),'compiler-result.json'));
  const payload=deserialize(fs.readFileSync(record.payload.path));
  assert.deepEqual(payload.result,state.results[0]);assert.equal(payload.result.cfg,payload.cfg);
  assert.equal(payload.result.alias,payload.result.shared.get('same'));
  assert.equal(payload.result.alias,payload.cfg.shared);
  assert.equal(payload.result.compiled.videos,payload.result.composition.videos);
  for(let index=0;index<planned.chunkCount;index++){
    const result=await chunk(f,planned,index);assert.equal(result.status,'native-qc-chunk-complete',result.error);
    const base=path.join(f.request.output,'native-qc-phases',`chunk-${String(index).padStart(3,'0')}`,'context');
    for(const name of record.work.files)assert.deepEqual(fs.readFileSync(path.join(base,name)),fs.readFileSync(path.join(planRoot(f),name)));
  }
  assert.equal((await finishNativeShortQc(f.request,planned.scheduleSha256,{sdk:f.sdk,encode:f.encode})).status,'native-references-and-seek-states-pass');
  assert.equal(state.compiles,1);assert.equal(state.metadata,planned.chunkCount+2);assert.ok(state.captures>0);
}));

for(const [name,mutate] of [
  ['modified preparation receipt',f=>fs.appendFileSync(path.join(planRoot(f),'compiler-result.json'),' ')],
  ['modified payload bytes',f=>fs.appendFileSync(path.join(planRoot(f),'compiler-result.bin'),'x')],
  ['missing payload',f=>fs.unlinkSync(path.join(planRoot(f),'compiler-result.bin'))],
  ['missing compiled index',f=>fs.unlinkSync(path.join(planRoot(f),'compiled/index.html'))],
  ['changed compiled subcomposition',f=>fs.appendFileSync(path.join(planRoot(f),'compiled/sub/index.html'),'x')],
  ['extra compiled override',f=>fs.writeFileSync(path.join(planRoot(f),'compiled/styles.css'),'override')],
  ['changed downloaded dependency',f=>fs.appendFileSync(path.join(planRoot(f),'downloads/font.woff'),'x')],
  ['changed project CSS',f=>fs.appendFileSync(path.join(f.request.project,'styles.css'),'x')],
  ['missing project source',f=>fs.unlinkSync(path.join(f.request.project,'assets/source.mp4'))],
  ['new project dependency',f=>fs.writeFileSync(path.join(f.request.project,'new.css'),'x')],
  ['symlinked dependency',f=>fs.symlinkSync(path.join(f.request.project,'styles.css'),path.join(planRoot(f),'compiled/new.css'))],
])test(`${name} fails before any replay session or new compiler call`,()=>withPicture(async f=>{
  const state=compilerWithDependencies(f),planned=await planNativeShortQc(f.request,{sdk:f.sdk});mutate(f);
  const result=await chunk(f,planned);assert.equal(result.status,'failed');assert.equal(state.captures,0);assert.equal(state.compiles,1);
  assert.equal(fs.existsSync(path.join(f.request.output,'native-frames.json')),false);
}));

for(const target of ['project','compiled','download'])test(`${target} mutation during capture cannot publish a passing child`,()=>withPicture(async f=>{
  const state=compilerWithDependencies(f),planned=await planNativeShortQc(f.request,{sdk:f.sdk});
  const capture=f.sdk.captureFrame;let changed=false;
  f.sdk.captureFrame=async(...args)=>{
    const result=await capture(...args);
    if(!changed){
      changed=true;
      const destination=target==='project'?path.join(f.request.project,'styles.css'):
        path.join(f.request.output,'native-qc-phases/chunk-000/context',target==='compiled'?'compiled/styles.css':'downloads/font.woff');
      fs.writeFileSync(destination,'changed during capture');
    }
    return result;
  };
  const result=await chunk(f,planned);assert.equal(result.status,'failed');assert.ok(state.captures>0);assert.equal(state.compiles,1);
  assert.equal(f.calls.sessionCloses,f.calls.sessions.length);
}));

test('compiler cfg changes before replay fail before any session',()=>withPicture(async f=>{
  const planned=await planNativeShortQc(f.request,{sdk:f.sdk}),count=f.calls.sessions.length;
  const resolve=f.sdk.resolveConfig;f.sdk.resolveConfig=cfg=>({...resolve(cfg),changed:true});
  const result=await chunk(f,planned);assert.equal(result.status,'failed');assert.match(result.error,/parameters\/configuration changed/);
  assert.equal(f.calls.sessions.length,count);
}));

test('eligible unsupported compiler result fails without a published schedule',()=>withPicture(async f=>{
  const compile=f.sdk.runCompileStage;f.sdk.runCompileStage=async input=>({...await compile(input),unsupported:()=>{}});
  await assert.rejects(()=>planNativeShortQc(f.request,{sdk:f.sdk}));assert.equal(fs.existsSync(scheduleFile(f)),false);
  assert.equal(fs.existsSync(path.join(planRoot(f),'compiler-result.json')),false);
}));

for(const maximum of [4,1])test(`valid legacy selection at max ${maximum} does not require compiler serialization`,()=>withPicture(async f=>{
  if(maximum===4){
    const file=path.join(f.request.output,'batched-picture.json'),receipt=read(file);delete receipt.forwardQc;fs.writeFileSync(file,JSON.stringify(receipt));
  }
  const compile=f.sdk.runCompileStage;f.sdk.runCompileStage=async input=>({...await compile(input),unsupported:()=>{}});
  const result=await planNativeShortQc(f.request,{sdk:f.sdk});assert.equal(result.status,'native-qc-phases-ineligible');
  assert.equal(fs.existsSync(scheduleFile(f)),false);assert.equal(Object.hasOwn(result,'compilerPins'),false);
  assert.equal(fs.existsSync(path.join(planRoot(f),'compiler-result.json')),false);
},maximum));

for(const descriptor of [{get:()=>1,enumerable:true},{value:1,enumerable:false}])test('compiler accessors or hidden authority fail before serialization',()=>{
  const value={};Object.defineProperty(value,'hidden',descriptor);assert.throws(()=>serializeCompilerResult(value),/descriptor/);
});

test('compiler work dependency absent from its complete file inventory cannot publish',()=>withPicture(async f=>{
  const compile=f.sdk.runCompileStage;
  f.sdk.runCompileStage=async input=>({...await compile(input),compiled:{externalAssets:new Map([['missing',path.join(input.workDir,'missing.file')]])}});
  await assert.rejects(()=>planNativeShortQc(f.request,{sdk:f.sdk}),/external work dependency is missing/);
  assert.equal(fs.existsSync(scheduleFile(f)),false);
}));
