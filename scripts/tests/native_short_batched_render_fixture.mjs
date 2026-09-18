/** Tiny fake SDK fixtures: no browser, metadata probe, image decode or encoder is launched. */
import fs from 'node:fs';
import path from 'node:path';
import os from 'node:os';
import assert from 'node:assert/strict';
import {EventEmitter} from 'node:events';
import {NativeFrameTransport} from '../producer/studio/runtime/frame-source-transport.mjs';
import {nativeSourceCacheIdentity} from '../producer/studio/native_source_cache.mjs';

/** Exercise the real local transport contract without opening a server or decoding an image. */
function fakeServer(calls) {
  const frameTransport=new NativeFrameTransport(),configure=frameTransport.configure.bind(frameTransport);
  frameTransport.report=()=>{};
  frameTransport.configure=entries=>{calls.cacheEntries.push(entries);configure(entries);};
  calls.transports.push(frameTransport);
  return {url:'http://localhost:39999',frameTransport,
    close:async()=>{frameTransport.close();calls.serverCloses++;}};
}

function fakePage(session, plan) {
  const page=new EventEmitter(),client=new EventEmitter();client.detached=false;
  client.send=async()=>{};client.detach=async()=>{client.detached=true;};
  page.createCDPSession=async()=>client;page.setRequestInterception=async()=>{};
  page.evaluate=async fn=>observedPage(fn,session,plan);return page;
}

function fakeSdk(fixture) {
  const {calls,plan,video,entry}=fixture;
  return {
    VIRTUAL_TIME_SHIM:'TEST shim',resolveConfig:cfg=>{calls.config=cfg;return cfg;},
    runCompileStage:async options=>{
      calls.compiles.push(options);fs.mkdirSync(path.join(options.workDir,'compiled'));
      fs.writeFileSync(path.join(options.workDir,'compiled/index.html'),'TEST compiled');
      return {composition:{width:1080,height:1920,duration:plan.canvas.totalFrames/25,videos:[video]}};
    },
    extractMediaMetadata:async()=>({width:3840,height:2160}),
    createFrameLookupTable:()=>({getActiveFramePayloads:time=>new Map([['source-0-0',{
      frameIndex:Math.round(time*25),framePath:path.join(entry,`frame_${String(Math.round(time*25)+1).padStart(5,'0')}.png`)}]])}),
    createFileServer2:async()=>fakeServer(calls),
    createVideoFrameInjector:(lookup,options)=>{calls.injectors.push(options);return lookup;},
    createCaptureSession:async(url,directory,options)=>{
      fs.mkdirSync(directory,{recursive:true});const session={outputDir:directory,options,captureMode:'screenshot',currentFrame:0};
      calls.sessions.push(session);session.page=fakePage(session,plan);return session;
    },
    initializeSession:async()=>{},
    captureFrame:async(session,frame,time)=>{
      if(frame===fixture.failFrame)throw new Error(`TEST screenshot decode failure at frame ${frame}`);
      session.currentFrame=frame;calls.frames.push(frame);const destination=path.join(session.outputDir,`frame_${String(frame).padStart(6,'0')}.jpg`);
      fs.writeFileSync(destination,`TEST JPEG screenshot frame ${frame}`);return {frameIndex:frame,time,path:destination,captureTimeMs:1};
    },
    closeCaptureSession:async()=>{calls.sessionCloses++;},drainBrowserPool:async()=>{calls.poolDrains++;},
  };
}

function observedPage(fn,session,plan) {
  const source=String(fn);
  if(source.includes('new DOMMatrix'))return [{id:'TEST state',frame:session.currentFrame}];
  if(source.includes('titleClip'))return {titleClip:session.currentFrame>=plan.canvas.titleCard.endFrame?'inset(100%)':'inset(0%)',
    lines:[],captions:[],words:[]};
  return {fonts:[{family:'Inter',status:'loaded'}],images:[{id:'source-0-0',loaded:true,display:'block'}],texts:[]};
}

export function batchFixture(totalFrames=100) {
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'sniper-batch-test-')));
  const project=path.join(root,'project'),runtime=path.join(root,'runtime'),cache=path.join(root,'cache'),output=path.join(root,'output');
  for(const directory of [path.join(project,'assets'),path.join(runtime,'dist'),cache,output])fs.mkdirSync(directory,{recursive:true});
  const source=path.join(project,'assets/source.mp4');fs.writeFileSync(source,'TEST source bytes');
  fs.writeFileSync(path.join(project,'index.html'),'TEST composition');
  fs.writeFileSync(path.join(runtime,'dist/native-capture-library.mjs'),'TEST SDK library');fs.writeFileSync(path.join(runtime,'dist/cli.js'),'TEST SDK CLI');
  const plan={canvas:{frameRate:'25/1',totalFrames,pictureViews:[{startFrame:0,endFrame:totalFrames}],captionViews:[],text:[],shapes:[],motion:[],
    occurrences:[],titleCard:{endFrame:25}},strategy:{scenes:[{startFrame:0,endFrame:totalFrames}]},expectations:[]};
  fs.writeFileSync(path.join(project,'SHORT-PROJECT.json'),JSON.stringify(plan));
  const video={id:'source-0-0',src:'assets/source.mp4',mediaStart:0,start:0,end:totalFrames/25};
  const {entry}=nativeSourceCacheIdentity({project,request:{cache},fps:{num:25,den:1}},video);
  fs.mkdirSync(entry);fs.writeFileSync(path.join(entry,'.hf-complete'),'TEST complete cache');
  for(let frame=0;frame<totalFrames;frame++)fs.writeFileSync(path.join(entry,`frame_${String(frame+1).padStart(5,'0')}.png`),`TEST PNG frame ${frame}`);
  const calls={compiles:[],sessions:[],frames:[],cacheEntries:[],transports:[],injectors:[],encodes:[],serverCloses:0,sessionCloses:0,poolDrains:0};
  const request={schemaVersion:1,project,runtime,cache,output,captureMode:'cached-native-batches',tools:{ffmpeg:'TEST ffmpeg'}};
  const fixture={root,request,plan,video,entry,calls,failFrame:null};
  fixture.sdk=fakeSdk(fixture);
  fixture.encode=async(command,args)=>{assert.equal(command,'TEST ffmpeg');calls.encodes.push(args);
    fs.writeFileSync(args.at(-1),'TEST encoded picture',{flag:'wx'});return {exitCode:0,elapsedMs:1};};
  fixture.cleanup=()=>fs.rmSync(root,{recursive:true,force:true});
  return fixture;
}
