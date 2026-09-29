/** TEST child process: one real store acquisition with a fake SDK decoder that writes TEST frames.
 *
 * The fake decoder mimics the SDK's view behaviour exactly where the store depends on it: a
 * complete path-keyed name is a hit; a miss is decoded into a `.partial-<pid>-<id>` directory,
 * given the completion marker and renamed onto its path-keyed name. No media process runs.
 * TEST faults: `symlinkFrame` makes one output frame a symbolic link, `hardLinkFrames` leaves every
 * frame hard-linked from a sibling view directory (the SDK's superset slicing), and
 * `crashAfterSdkPublish` kills the job after the SDK publication, before the store publication.
 */
import fs from 'node:fs';
import path from 'node:path';
import {randomUUID} from 'node:crypto';
import {setTimeout as sleep} from 'node:timers/promises';
import {openNativeSourcePlan,acquireNativeSources} from '../producer/studio/native_source_acquisition.mjs';
import {nativeSourceCacheIdentity} from '../producer/studio/native_source_identity.mjs';
import {nativeSourceFrameCount} from '../producer/studio/runtime/frame-source-transport.mjs';
import {holdStoreOwner,openSourceStore} from '../producer/studio/native_source_store.mjs';

const spec=JSON.parse(process.argv[2]);
const event=value=>fs.appendFileSync(spec.events,JSON.stringify({pid:process.pid,label:spec.label,...value})+'\n');

/** A symbolic-link frame points at identical TEST bytes kept outside the job's decode directory. */
function writeFrame(file, text, index) {
  if(index!==spec.symlinkFrame){fs.writeFileSync(file,text);return;}
  const target=`${spec.work}/symlink-target-${index}.png`;fs.writeFileSync(target,text);fs.symlinkSync(target,file);
}

/** The SDK's superset slicing leaves member frames hard-linked with an overlapping sibling member. */
function hardLinkSibling(name) {
  const sibling=`${name}.TEST-overlapping-member`;fs.mkdirSync(sibling);
  for(const file of fs.readdirSync(name).filter(value=>value.startsWith('frame_')))fs.linkSync(path.join(name,file),path.join(sibling,file));
}

async function decodeMiss(context, video, name) {
  event({type:'extract-start',videoId:video.id,name:path.basename(name)});
  const partial=`${name}.partial-${process.pid}-${randomUUID().slice(0,8)}`;fs.mkdirSync(partial);
  const bytes=fs.readFileSync(path.resolve(context.project,video.src));
  const frames=nativeSourceFrameCount(video.end-video.start,context.rate),framePaths=new Map();
  for(let index=0;index<frames;index++){
    if(index===spec.crashAfterFrames){event({type:'crash',frames:index});process.kill(process.pid,'SIGKILL');}
    const file=path.join(partial,`frame_${String(index+1).padStart(5,'0')}.png`);
    writeFrame(file,`TEST frame ${index} of ${bytes.length} source bytes ${bytes.subarray(0,16).toString('hex')}`,index);
    framePaths.set(index,path.join(name,path.basename(file)));
    if(spec.frameDelayMs)await sleep(spec.frameDelayMs);
  }
  if(spec.mutateSourceDuringDecode)fs.appendFileSync(path.resolve(context.project,video.src),'TEST mutation');
  fs.writeFileSync(path.join(partial,'.hf-complete'),'');fs.renameSync(partial,name);
  if(spec.hardLinkFrames)hardLinkSibling(name);
  event({type:'extract-end',videoId:video.id});
  if(spec.crashAfterSdkPublish){event({type:'crash-after-sdk-publish'});process.kill(process.pid,'SIGKILL');}
  return {videoId:video.id,outputDir:name,framePaths,totalFrames:frames};
}

const sdk={
  extractMediaMetadata:async()=>({width:1080,height:1920,colorSpace:null}),
  isHdrColorSpace:()=>false,
  async extractAllVideoFrames(videos, project, options, signal, config) {
    const context={project,request:{cache:config.extractCacheDir},fps:options.fps,rate:spec.rate},extracted=[];
    for(const video of videos){
      const name=nativeSourceCacheIdentity(context,video,config.extractCacheDir).entry;
      if(fs.existsSync(path.join(name,'.hf-complete'))){
        const files=fs.readdirSync(name).filter(file=>file.startsWith('frame_')).sort();
        extracted.push({videoId:video.id,outputDir:name,totalFrames:files.length,
          framePaths:new Map(files.map((file,index)=>[index,path.join(name,file)]))});
        continue;
      }
      extracted.push(await decodeMiss({...context,project},video,name));
    }
    return {success:true,errors:[],extracted,durationMs:1,phaseBreakdown:{}};
  },
};

/** Exercise the shared acquisition protocol with the fixture decoder, without changing Short adapters. */
async function prepareTestSources(context) {
  const plan=await openNativeSourcePlan(context,()=>{}),receipt={schemaVersion:2,status:'preparing'};
  const persist=()=>fs.writeFileSync(path.join(spec.work,'source-cache.json'),JSON.stringify(receipt));
  const extract=context.request.sourceCacheMode==='existing-only'?null:async()=>{
    const result=await sdk.extractAllVideoFrames(context.result.composition.videos,context.project,
      {fps:context.fps},undefined,{extractCacheDir:plan.view});
    if(!result.success)throw new Error('TEST decoder failed');
  };
  await acquireNativeSources(context,plan,{receipt,persist,extract,collectBytes:context.cfg.extractCacheMaxBytes});
}

async function main() {
  if(spec.role==='supervisor'){
    const owner=holdStoreOwner(openSourceStore(spec.cache));
    console.log(JSON.stringify({owner:owner.file}));
    await sleep(spec.holdMs);return;
  }
  const request={project:spec.project,cache:spec.cache,output:spec.output,captureMode:'sdk-streaming',
    sourceCacheMode:spec.mode??'acquire-sdk-preflight',pins:spec.pins,tools:spec.tools,
    ...(spec.sourceStoreOwner?{sourceStoreOwner:spec.sourceStoreOwner}:{})};
  fs.mkdirSync(spec.work,{recursive:true});
  const context={request,project:spec.project,work:spec.work,sdk,fps:{num:spec.rate,den:1},rate:spec.rate,
    plan:{canvas:{totalFrames:spec.totalFrames}},result:{composition:{videos:spec.videos}},
    runtimeLibrarySha256:spec.runtimeLibrarySha256,cfg:{extractCacheMaxBytes:spec.maxBytes??64*1024**3}};
  try{
    await prepareTestSources(context);
    const receipt=JSON.parse(fs.readFileSync(path.join(spec.work,'source-cache.json'),'utf8'));
    event({type:'acquired',entries:receipt.entries});
    console.log(JSON.stringify({status:'acquired',entries:receipt.entries,view:context.sourceView,collection:receipt.collection}));
    if(spec.holdMs)await sleep(spec.holdMs);
  }catch(error){
    console.log(JSON.stringify({status:'failed',error:String(error?.message??error)}));process.exitCode=1;
  }
}

await main();
