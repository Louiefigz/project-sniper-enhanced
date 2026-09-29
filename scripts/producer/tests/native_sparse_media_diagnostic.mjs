/** Actual pinned SDK extraction of synthetic media; no render/editorial qualification. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';
import {createHash} from 'node:crypto';
import {execFileSync} from 'node:child_process';
import {pathToFileURL} from 'node:url';
import {sparseSourceSpans,sparseSourceSelections} from '../studio/native_segments/sparse_sources.mjs';
import {nativeSourceCacheIdentity} from '../studio/native_source_identity.mjs';

const file=process.argv[2],request=JSON.parse(fs.readFileSync(file,'utf8'));
assert.equal(process.env.SNIPER_INSPECTION_REQUEST,file,'Diagnostic requires owned Python wrapper');
const sdk=await import(pathToFileURL(path.join(request.runtime,'dist/native-capture-library.mjs')).href);
const root=path.dirname(file),project=request.project;
const hash=file=>createHash('sha256').update(fs.readFileSync(file)).digest('hex');

/** Generate real, rapidly changing CFR H.264 pixels with explicit SDR metadata. */
function source(rate) {
  const file=path.join(project,`synthetic-${rate.replace('/','-')}.mp4`);
  if(fs.existsSync(file))return path.basename(file);
  execFileSync(request.tools.ffmpeg,['-nostdin','-v','error','-n','-f','lavfi','-i',
    `testsrc2=size=320x180:rate=${rate}`,'-t','5','-an','-c:v','libx264','-preset','veryfast',
    '-crf','15','-pix_fmt','yuv420p','-color_primaries','bt709','-color_trc','bt709',
    '-colorspace','bt709','-color_range','tv',file],{timeout:30000});
  return path.basename(file);
}

/** Independent cache roots prevent sparse requests from slicing the full-run cache. */
async function extract(videos,clock,directory) {
  fs.mkdirSync(directory);
  const result=await sdk.extractAllVideoFrames(structuredClone(videos),project,
    {fps:clock,format:'png',outputDir:path.join(directory,'frames'),maxTransientRetries:0,collectProbeFailures:true},
    undefined,{...sdk.resolveConfig({}),extractCacheDir:path.join(directory,'cache')},project);
  assert.ok(result.success&&result.errors.length===0,JSON.stringify(result.errors));
  assert.equal(result.extracted.length,videos.length);
  return result.extracted;
}

/** Compare requested original-local indexes, retaining mismatched real PNG references. */
function compare(full,rows,spans) {
  const checks=[];
  for(const span of spans){
    const row=rows.find(item=>item.videoId===span.video.id);
    assert.equal(row.totalFrames,span.endIndex-span.startIndex);
    for(const [offset,file] of row.framePaths){
      const index=span.startIndex+offset,original=full.framePaths.get(index);
      assert.ok(original,`Full cache lacks original frame ${index}`);
      checks.push({index,full:original,sparse:file,fullSha256:hash(original),sparseSha256:hash(file),equal:hash(original)===hash(file)});
    }
  }
  return checks;
}

/** Candidate correction keeps the original input seek and selects after its original fps grid. */
function anchored(full,video,indices,spec) {
  const directory=path.join(path.dirname(full.outputDir),'anchored');fs.mkdirSync(directory);
  const selection=indices.map(index=>`eq(n\\,${index})`).join('+');
  execFileSync(request.tools.ffmpeg,['-nostdin','-v','error','-ss',String(video.mediaStart),'-i',
    path.join(project,video.src),'-vf',`fps=${spec.output}:start_time=0,select=${selection}`,
    '-fps_mode','passthrough','-frames:v',String(indices.length),'-q:v','0','-compression_level','1',
    '-n',path.join(directory,'frame_%05d.png')],{timeout:30000});
  return indices.map((index,offset)=>{
    const original=full.framePaths.get(index),file=path.join(directory,`frame_${String(offset+1).padStart(5,'0')}.png`);
    return {index,full:original,selected:file,fullSha256:hash(original),selectedSha256:hash(file),equal:hash(original)===hash(file)};
  });
}

/** Exercise integer, converted and rational clocks, fractional mounts, and interval ends. */
async function runCase(spec,index) {
  const [num,den]=spec.output.split('/').map(Number),rate=num/den;
  const video={id:'source',src:source(spec.source),start:spec.mount,end:spec.mount+2.4,
    mediaStart:spec.offset,loop:false,playbackRate:1};
  const begin=Math.ceil(video.start*rate),end=Math.ceil(video.end*rate)-1;
  const points=[...new Set([begin,begin+1,begin+9,begin+10,begin+27,end-1,end])].sort((a,b)=>a-b);
  const spans=sparseSourceSpans([video],points,rate),directory=path.join(root,`case-${index}`);fs.mkdirSync(directory);
  const full=(await extract([video],{num,den},path.join(directory,'full')))[0];
  const sparse=await extract(spans.map(row=>row.video),{num,den},path.join(directory,'sparse'));
  const checks=compare(full,sparse,spans);
  const anchoredChecks=anchored(full,video,checks.map(row=>row.index),spec);
  const selection=sparseSourceSelections([video],points,rate)[0];
  const selected=(await extract([selection.video],{num,den},path.join(directory,'selected-sdk')))[0];
  const predicted=nativeSourceCacheIdentity({project,fps:{num,den},request:{cache:path.join(directory,'selected-sdk/cache')}},selection.video);
  assert.equal(selected.outputDir,predicted.entry,'Selected SDK cache identity differs from shared-store prediction');
  const selectedChecks=[...selected.framePaths].map(([offset,file])=>({index:selection.indices[offset],
    equal:hash(file)===hash(full.framePaths.get(selection.indices[offset]))}));
  console.log(`SNIPER_PROGRESS synthetic-source-grid ${index+1}`);
  return {...spec,points,fullFrames:full.totalFrames,sparseFrames:checks.length,checks,
    metadata:full.metadata,passed:checks.every(row=>row.equal),anchoredChecks,
    anchoredPassed:anchoredChecks.every(row=>row.equal),selectedChecks,selectedPassed:selectedChecks.every(row=>row.equal),
    selectedCacheIdentityMatches:true};
}

const cases=[
  {source:'25',output:'25/1',offset:0,mount:0},
  {source:'25',output:'25/1',offset:.113,mount:.017},
  {source:'30',output:'25/1',offset:0,mount:0},
  {source:'30',output:'25/1',offset:.113,mount:.017},
  {source:'30000/1001',output:'30000/1001',offset:.113,mount:.017},
  {source:'25',output:'30000/1001',offset:.113,mount:.017},
];
const results=[];
for(const [index,spec] of cases.entries())results.push(await runCase(spec,index));
const result={schemaVersion:1,kind:'synthetic-cfr-source-grid',productionQualification:false,
  passed:results.every(row=>row.selectedPassed),legacyShiftedPassed:results.every(row=>row.passed),
  anchoredPassed:results.every(row=>row.anchoredPassed),results};
fs.writeFileSync(path.join(root,'result.json'),JSON.stringify(result,null,2)+'\n',{flag:'wx'});
console.log(JSON.stringify({passed:result.passed,cases:results.map(row=>({source:row.source,output:row.output,
  offset:row.offset,frames:row.sparseFrames,mismatches:row.checks.filter(check=>!check.equal).map(check=>check.index),
  anchoredMismatches:row.anchoredChecks.filter(check=>!check.equal).map(check=>check.index)}))}));
