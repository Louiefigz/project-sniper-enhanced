/** Sparse planning/lookup proof only; synthetic SDK boundaries never qualify source seeks. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {sparseSourceSpans,sparseSourceSelections,checkedSparseLookup,prepareSparseLongContext} from '../producer/studio/native_segments/sparse_sources.mjs';
import {dependencyFrames} from '../producer/studio/native_segments/probe.mjs';

test('sparse 14-minute source plan acquires only requested frames plus initialization',()=>{
  const videos=[{id:'footage',src:'assets/source.mp4',start:0,end:840,mediaStart:17.25,playbackRate:1}];
  const points=dependencyFrames({startFrame:20500,endFrame:20750});
  const spans=sparseSourceSpans(videos,points,25);
  assert.equal(spans.reduce((sum,row)=>sum+row.endIndex-row.startIndex,0),points.length+1);
  assert.ok(spans.every(row=>row.video.end<=2/25));
  assert.deepEqual(spans.flatMap(row=>Array.from({length:row.endIndex-row.startIndex},(_,i)=>row.startIndex+i)),[0,...points]);
  assert.equal(spans.at(-1).video.mediaStart,17.25+points.at(-1)/25);
  assert.equal(videos[0].end,840,'original composition timeline remains untouched');
});

test('fractional starts preserve pinned SDK floor mapping and exclusive ends',()=>{
  const videos=[{id:'out',src:'assets/a.mp4',start:0,end:1.02,mediaStart:0},
    {id:'in',src:'assets/b.mp4',start:1.02,end:2.5,mediaStart:4.125}];
  const spans=sparseSourceSpans(videos,[25,26,27,60],25);
  const incoming=spans.filter(row=>row.videoIndex===1);
  assert.deepEqual(incoming.map(row=>[row.startIndex,row.endIndex]),[[0,2],[34,35]]);
  assert.equal(incoming[1].video.mediaStart,4.125+34/25);
  assert.equal(spans.filter(row=>row.videoIndex===0).at(-1).startIndex,25);
});

test('every owner window has ordered bounded endpoints and midpoints',()=>{
  for(let length=1;length<=600;length++){
    const points=dependencyFrames({startFrame:900,endFrame:900+length});
    assert.ok(points.length<=12);assert.equal(points[0],900);assert.equal(points.at(-1),899+length);
    assert.deepEqual(points,[...new Set(points)].sort((a,b)=>a-b));
    assert.ok(points.includes(Math.floor((1800+length-1)/2)));
  }
});

test('missing active sparse frames cannot silently become absent picture layers',()=>{
  const videos=[{id:'source',start:10,end:20}],lookup={getActiveFramePayloads:()=>new Map()};
  checkedSparseLookup(lookup,videos,25);
  assert.throws(()=>lookup.getActiveFramePayloads(10),/Unacquired active sparse source/);
  assert.deepEqual([...lookup.getActiveFramePayloads(20)],[]);
  const wrong={getActiveFramePayloads:()=>new Map([['source',{frameIndex:1}]])};
  checkedSparseLookup(wrong,videos,25);
  assert.throws(()=>wrong.getActiveFramePayloads(10),/frame clock changed/);
});

test('forward and reverse sparse lookup preserves original video IDs and local frame indexes',()=>{
  const videos=[{id:'source',start:10.02,end:20}],lookup={getActiveFramePayloads:time=>
    new Map([['source',{frameIndex:Math.floor((time-10.02)*25+1e-9),framePath:'TEST admitted frame'}]])};
  checkedSparseLookup(lookup,videos,25);
  for(const time of [12,15,10.04,19.96,12]){
    assert.equal(lookup.getActiveFramePayloads(time).get('source').frameIndex,Math.floor((time-10.02)*25+1e-9));
  }
});

test('excess requested source frames and alternate playback clocks fail before extraction',()=>{
  const video={id:'source',src:'assets/a.mp4',start:0,end:900,mediaStart:0};
  assert.throws(()=>sparseSourceSpans([video],Array.from({length:2049},(_,i)=>i),25),/inventory exceeds/);
  assert.throws(()=>sparseSourceSpans([{...video,loop:true}],[0,25],25),/speed one/);
  assert.throws(()=>sparseSourceSpans([{...video,playbackRate:2}],[0,25],25),/speed one/);
});

function contextFixture(metadata={isVFR:false}) {
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'long-sparse-context-')));
  const project=path.join(root,'project'),work=path.join(root,'work');
  fs.mkdirSync(path.join(project,'assets'),{recursive:true});fs.mkdirSync(work);
  fs.writeFileSync(path.join(project,'assets/source.mp4'),'TEST source');
  const video={id:'actual',src:'assets/source.mp4',start:0,end:840,mediaStart:17.25},calls=[];
  const sdk={resolveConfig:value=>value,runCompileStage:async()=>{
    fs.mkdirSync(path.join(work,'compiled'));fs.writeFileSync(path.join(work,'compiled/index.html'),'TEST compile');
    return {composition:{width:320,height:180,duration:840,videos:[video]}};},
    extractMediaMetadata:async()=>({width:640,height:360,...metadata}),isHdrColorSpace:color=>color?.hdr===true,
    createFrameLookupTable:(videos,extracted)=>{
      calls.push({videos,extracted});
      return {getActiveFramePayloads:time=>{
        const index=Math.floor(time*25+1e-9),file=extracted[0].framePaths.get(index);
        return new Map(file?[['actual',{frameIndex:index,framePath:file}]]:[]);
      }};
    }};
  const context={project,work,sdk,plan:{canvas:{width:320,height:180,totalFrames:21000,frameRate:'25/1'}},
    request:{adapter:'native-long',pins:{[path.join(project,'assets/source.mp4')]:'a'.repeat(64)}},
    width:320,height:180,fps:{num:25,den:1},rate:25,cacheEntries:[],log:{}};
  return {root,context,calls,cleanup:()=>fs.rmSync(root,{recursive:true,force:true})};
}

test('sparse preparation acquires original-grid shared-store samples and keeps lookup identity',async()=>{
  const fixture=contextFixture(),{context,calls}=fixture,points=[20500,20625,20749];
  context.request.sourceStoreOwner='/TEST/top-export-owner';
  try{
    let requested;
    await prepareSparseLongContext(context,points,async proxy=>{
      assert.equal(proxy.request.sourceStoreOwner,undefined,'sparse views retained only by actual reader lifetime');
      requested=proxy.result.composition.videos;
      proxy.sourceEntries=new Map(requested.map(video=>{
        const directory=path.join(proxy.work,video.id);fs.mkdirSync(directory);
        const framePaths=new Map(video.nativeSourceFrameIndices.map((value,index)=>{
          const file=path.join(directory,`frame_${String(index+1).padStart(5,'0')}.png`);
          fs.writeFileSync(file,'TEST admitted source frame '+value);return [index,file];
        }));
        return [video.id,{entry:directory,frames:framePaths.size,framePaths}];
      }));
      proxy.sourceCacheAcquisition={TEST:'synthetic store acquisition'};
    });
    assert.equal(requested.length,1);assert.equal(requested[0].end,4/25);
    assert.equal(requested[0].mediaStart,17.25);assert.deepEqual(requested[0].nativeSourceFrameIndices,[0,...points]);
    assert.equal(calls[0].videos[0].id,'actual');assert.equal(calls[0].videos[0].end,840);
    assert.equal(calls[0].extracted[0].totalFrames,21000);
    assert.deepEqual([...calls[0].extracted[0].framePaths.keys()],[0,...points]);
    assert.equal(context.transportRoots.length,1);
    assert.equal(context.sparseSources.sourceFrames,4);
    assert.equal(context.request.sourceStoreOwner,'/TEST/top-export-owner','original owner authority remains unchanged');
    assert.throws(()=>context.lookup.getActiveFramePayloads(1),/Unacquired/);
    for(const frame of [...points,...points.slice().reverse()])assert.equal(context.lookup.getActiveFramePayloads(frame/25).get('actual').frameIndex,frame);
  }finally{fixture.cleanup();}
});

test('converted and rational sparse selections never shift the original media start',()=>{
  for(const rate of [25,30000/1001]){
    const video={id:'source',src:'a.mp4',start:.017,end:2.417,mediaStart:.113};
    const rows=sparseSourceSelections([video],[1,10,28,60],rate);
    assert.equal(rows.length,1);assert.equal(rows[0].video.mediaStart,.113);
    assert.deepEqual(rows[0].video.nativeSourceFrameIndices,rows[0].indices);
    assert.equal(rows[0].video.end,rows[0].indices.length/rate);
  }
});

test('VFR HDR and unknown clocks request exact existing full cache with no decode fallback',async()=>{
  for(const metadata of [{isVFR:true},{isVFR:undefined},{isVFR:false,colorSpace:{hdr:true}}]){
    const fixture=contextFixture(metadata);
    try{
      await assert.rejects(prepareSparseLongContext(fixture.context,[20500],async(context,options)=>{
        assert.equal(options.existingOnly,true);assert.equal(context.result.composition.videos[0].end,840);
        throw new Error('TEST exact full cache absent');
      }),/exact full cache absent/);
      assert.equal(fixture.calls.length,0);
    }finally{fixture.cleanup();}
  }
});
