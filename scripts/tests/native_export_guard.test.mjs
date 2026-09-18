/** Admission tests use fictional receipts; they never run SDK/browser/media work. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import crypto from 'node:crypto';
import {test} from 'node:test';
import {assertNativeRenderOwner,assertNativeCaptureOwner} from '../producer/studio/runtime/native-export-guard.mjs';

const sha=file=>crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
function fixture(t) {
  const root=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'TEST-native-admission-')));
  t.after(()=>fs.rmSync(root,{recursive:true,force:true}));
  const file=path.join(root,'export-request.json'),ownerFile=path.join(root,'picture.render.json');
  const samples=path.join(root,'sample-qc/result.json');fs.mkdirSync(path.dirname(samples));
  fs.writeFileSync(samples,JSON.stringify({passed:true}));
  const request={adapter:'native-long',project:'/TEST/project',output:root};
  fs.writeFileSync(file,JSON.stringify(request));
  const owner={project:request.project,status:'running',
    additionalFilePinsBefore:{[file]:sha(file),[samples]:sha(samples)},
    args:['/usr/bin/sandbox-exec','-f','/TEST/sandbox','/TEST/python','/TEST/native_long_worker.py',file,'picture']};
  const save=()=>fs.writeFileSync(ownerFile,JSON.stringify(owner));save();
  return {file,samples,owner,save,args:['render',request.project,'--output',path.join(root,'picture.mp4')],
    environment:{SNIPER_NATIVE_EXPORT_REQUEST:file,SNIPER_NATIVE_EXPORT_OWNER:ownerFile,SNIPER_NATIVE_EXPORT_PID:String(process.pid)}};
}

test('raw SDK render cannot launch without a shared owner',()=>{
  assert.throws(()=>assertNativeRenderOwner(['render','/TEST/project'],{}),/owner\/request/);
  assert.doesNotThrow(()=>assertNativeRenderOwner(['--help'],{}));
});

test('remote and batch render spellings cannot bypass native workflow admission',()=>{
  for(const args of [['lambda','render-batch','/TEST/batch.json'], ['cloudrun','render','/TEST/project'],
    ['cloud','render','/TEST/project'], ['render-batch','/TEST/batch.json']]) {
    assert.throws(()=>assertNativeRenderOwner(args,{}),/batch\/custom/);
    assert.doesNotThrow(()=>assertNativeRenderOwner([...args,'--help'],{}));
  }
});

test('admitted long picture retains current encoded seam proof',t=>{
  const f=fixture(t);assert.doesNotThrow(()=>assertNativeRenderOwner(f.args,f.environment));
  fs.writeFileSync(f.samples,JSON.stringify({passed:false}));
  assert.throws(()=>assertNativeRenderOwner(f.args,f.environment),/seam/);
});

test('completed owner, custom wrapper, changed request and wrong project are refused',t=>{
  const f=fixture(t);
  f.owner.completedAt='TEST terminal';f.save();
  assert.throws(()=>assertNativeRenderOwner(f.args,f.environment),/not active/);
  delete f.owner.completedAt;f.owner.args[4]='/TEST/run_assembly.py';f.save();
  assert.throws(()=>assertNativeRenderOwner(f.args,f.environment),/shared export worker/);
  f.owner.args[4]='/TEST/native_long_worker.py';f.save();
  assert.throws(()=>assertNativeRenderOwner(['render','/TEST/other',...f.args.slice(2)],f.environment),/project\/output/);
  fs.appendFileSync(f.file,' ');
  assert.throws(()=>assertNativeRenderOwner(f.args,f.environment),/bind the current request/);
});

test('direct capture needs a capture owner; picture authority is insufficient',t=>{
  const f=fixture(t);
  assert.throws(()=>assertNativeCaptureOwner(f.file,{}),/supervisor/);
  assert.throws(()=>assertNativeCaptureOwner(f.file,f.environment),/shared worker/);
  f.owner.args[6]='capture';f.save();
  assert.doesNotThrow(()=>assertNativeCaptureOwner(f.file,f.environment));
});
