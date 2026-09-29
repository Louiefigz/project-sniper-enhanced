/** Adapter-neutral retained frame checks with fictional bytes, never actual video qualification. */
import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {spawnSync} from 'node:child_process';
import {retainedFrameHash,retainedFramePartition,verifyRetainedFrame,copyRetainedFrame}
  from '../producer/studio/native_retained_frames.mjs';

function fixture(t) {
  const base=fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(),'retained-generic-')));
  t.after(()=>fs.rmSync(base,{recursive:true,force:true}));
  const root=path.join(base,'original'),target=path.join(base,'current');
  fs.mkdirSync(root);fs.mkdirSync(target);
  const file=path.join(root,'frame_040000.jpg');fs.writeFileSync(file,'TEST fictional JPEG beyond Short clock');
  const row={frame:40000,path:file,sha256:retainedFrameHash(file,4096),bytes:fs.statSync(file).size,origin:'captured'};
  const contract={root,frameRange:[40000,40250],pins:{[file]:row.sha256},maximumBytes:4096};
  return {base,root,target,row,contract};
}

test('absolute range is supplied by adapter, without Short total/frame defaults',()=>{
  const value=retainedFramePartition([40000,40006],[[40002,40003]],250);
  assert.deepEqual(value,{captured:[40002],retained:[40000,40001,40003,40004,40005]});
  assert.throws(()=>retainedFramePartition([0,40000],[],250));
  assert.throws(()=>retainedFramePartition([0,10],[[2,5],[4,6]],250));
  assert.throws(()=>retainedFramePartition([0,10],[[6,9],[2,3]],250));
});

test('exclusive copy keeps source unchanged and rehashes exact bytes',t=>{
  const f=fixture(t),value=copyRetainedFrame(f.row,f.target,f.contract);
  assert.equal(value.origin,'retained');assert.equal(value.sha256,f.row.sha256);
  assert.equal(retainedFrameHash(value.path,4096),f.row.sha256);
  verifyRetainedFrame(f.row,f.contract);
  assert.throws(()=>copyRetainedFrame(f.row,f.target,f.contract),/EEXIST/);
});

test('changed or unpinned donor refuses before copying',t=>{
  const f=fixture(t);
  assert.throws(()=>copyRetainedFrame(f.row,f.target,{...f.contract,pins:{}}),/not pinned/);
  fs.writeFileSync(f.row.path,'X'.repeat(f.row.bytes));
  assert.throws(()=>copyRetainedFrame(f.row,f.target,f.contract),/changed/);
  assert.deepEqual(fs.readdirSync(f.target),[]);
});

test('symlink and hardlink source aliases are not retained frame identities',t=>{
  const f=fixture(t),alias=path.join(f.base,'alias.jpg');
  fs.symlinkSync(f.row.path,alias);assert.throws(()=>retainedFrameHash(alias,4096),/canonical/);
  fs.unlinkSync(alias);fs.linkSync(f.row.path,alias);
  assert.throws(()=>verifyRetainedFrame(f.row,f.contract),/file contract/);
});

test('wrong frame path and oversized inventory fail bounded checks',t=>{
  const f=fixture(t);
  assert.throws(()=>verifyRetainedFrame({...f.row,frame:40001},f.contract));
  assert.throws(()=>verifyRetainedFrame(f.row,{...f.contract,maximumBytes:1}));
  assert.throws(()=>retainedFrameHash(f.row.path,0));
});

test('destination link cannot be overwritten or become a retained result',t=>{
  const f=fixture(t),destination=path.join(f.target,path.basename(f.row.path));
  fs.symlinkSync(f.row.path,destination);
  assert.throws(()=>copyRetainedFrame(f.row,f.target,f.contract),/EEXIST/);
  assert.equal(retainedFrameHash(f.row.path,4096),f.row.sha256);
});

test('FIFO replacement refuses without blocking before the regular-file check',{skip:process.platform==='win32'},t=>{
  const f=fixture(t);fs.unlinkSync(f.row.path);
  const made=spawnSync('mkfifo',[f.row.path],{timeout:1000});assert.equal(made.status,0);
  const module=new URL('../producer/studio/native_retained_frames.mjs',import.meta.url).href;
  const script=`import assert from 'node:assert/strict';import {retainedFrameHash} from ${JSON.stringify(module)};
    assert.throws(()=>retainedFrameHash(process.argv[1],4096),/file contract/);`;
  const child=spawnSync(process.execPath,['--input-type=module','-e',script,f.row.path],{timeout:2000});
  assert.equal(child.error,undefined);assert.equal(child.status,0,child.stderr.toString());
});
