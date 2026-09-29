/** Shared TEST fixture for source-store proofs: real child processes, real kernel locks, TEST frames only. */
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {createHash} from 'node:crypto';
import {setTimeout as sleep} from 'node:timers/promises';
import {openSourceStore} from '../producer/studio/native_source_store.mjs';
import {collectStoreGarbage} from '../producer/studio/native_source_store_collection.mjs';

/** Every collection gets an explicit caller bound; tests allow ten seconds unless they test the bound. */
export const collect=(store,budget)=>collectStoreGarbage(store,{until:performance.now()+10000,...budget});

const CHILD=path.resolve('scripts/tests/native_source_store_child.mjs');
export const sha=bytes=>createHash('sha256').update(bytes).digest('hex');

export function storeFixture() {
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'sniper-store-test-')));
  const cache=path.join(root,'cache'),events=path.join(root,'events.jsonl');fs.mkdirSync(cache);
  const owner=path.join(root,'owner.render.json');
  fs.writeFileSync(owner,JSON.stringify({startedAt:new Date().toISOString(),runDeadlineSeconds:600}));
  const project=name=>{
    const directory=path.join(root,name),assets=path.join(directory,'assets');fs.mkdirSync(assets,{recursive:true});
    fs.writeFileSync(path.join(assets,'source.mp4'),'TEST identical source bytes for every revision');
    return directory;
  };
  const f={root,cache,events,owner,project,children:[]};
  f.spec=(label,directory,extra={})=>{
    const source=path.join(directory,'assets/source.mp4');
    return {label,project:directory,cache,events,output:path.join(root,`attempt-${label}`),work:path.join(root,`work-${label}`),
      rate:25,totalFrames:50,runtimeLibrarySha256:'1'.repeat(64),tools:{ffmpeg:'TEST ffmpeg',ffprobe:'TEST ffprobe'},
      pins:{[source]:sha(fs.readFileSync(source)),'TEST ffmpeg':'2'.repeat(64),'TEST ffprobe':'3'.repeat(64)},
      videos:[{id:'source-0-0',src:'assets/source.mp4',mediaStart:0,start:0,end:1}],frameDelayMs:0,...extra};
  };
  f.start=spec=>{
    const child=spawn(process.execPath,[CHILD,JSON.stringify(spec)],{env:{...process.env,SNIPER_NATIVE_EXPORT_OWNER:owner},
      stdio:['ignore','pipe','pipe']});
    let stdout='',stderr='';child.stdout.on('data',data=>{stdout+=data;});child.stderr.on('data',data=>{stderr+=data;});
    child.captured=()=>stdout;
    child.done=new Promise(resolve=>child.on('close',(code,signal)=>{
      const line=stdout.trim().split('\n').filter(value=>value.startsWith('{')).at(-1);
      resolve({code,signal,stdout,stderr,result:line?JSON.parse(line):null});
    }));
    f.children.push(child);return child;
  };
  f.eventRows=()=>fs.existsSync(events)?fs.readFileSync(events,'utf8').trim().split('\n').filter(Boolean).map(JSON.parse):[];
  f.waitFor=async(predicate,ms=10000)=>{
    const end=Date.now()+ms;
    while(Date.now()<end){if(f.eventRows().some(predicate))return;await sleep(20);}
    throw new Error('TEST event did not arrive');
  };
  f.store=()=>openSourceStore(cache);
  f.cleanup=()=>{for(const child of f.children)if(child.exitCode===null&&child.signalCode===null)child.kill('SIGKILL');
    fs.rmSync(root,{recursive:true,force:true});};
  return f;
}

export async function withStore(run) {
  const f=storeFixture();try{await run(f);}finally{f.cleanup();}
}

export const extractions=(f,label)=>f.eventRows().filter(row=>row.type==='extract-start'&&(!label||row.label===label));
