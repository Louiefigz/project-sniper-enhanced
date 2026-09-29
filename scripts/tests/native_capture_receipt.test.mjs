/** Receipt compaction is exact for every frame; unknown or partial states never compact silently. */
import assert from 'node:assert/strict';
import {test} from 'node:test';
import {compactNativeTypography,expandNativeTypography,expandTypography,typographyChanges,
  TYPOGRAPHY_ENCODING} from '../producer/studio/native_capture_receipt.mjs';

/** Dense-caption state: every phrase and word element is read on every frame; one of each is active. */
function denseState(frame, words=187, captions=69) {
  const activeWord=Math.min(words-1,Math.floor(frame/7)),activeCaption=Math.min(captions-1,Math.floor(activeWord/3));
  return {titleClip:frame>=60?'inset(100%)':'inset(0%)',
    lines:frame<60?[{text:'TEST title',left:120,right:960+frame%2,scroll:840,client:840}]:[{text:'TEST title',left:120,right:960,scroll:840,client:840}],
    captions:Array.from({length:captions},(_,index)=>({id:`caption-${index}-0`,start:index*0.7,end:index*0.7+0.7,
      clip:index===activeCaption?'inset(0%)':'inset(100%)',center:540,top:1660,scroll:840,client:840})),
    words:Array.from({length:words},(_,index)=>({id:index,view:0,start:index*7,end:index*7+7,
      color:index===activeWord?'rgb(255, 176, 32)':'rgb(255, 255, 255)',text:`word${index}`}))};
}

function receiptWith(states) {
  return {status:'failed',frames:states.map((typography,index)=>({frame:index,path:`/TEST/pose-${index}.jpg`,
    visualState:[{id:'TEST',frame:index}],typography}))};
}

test('every compacted frame expands to exactly the observed state',()=>{
  const states=Array.from({length:755},(_,frame)=>denseState(frame%1369));
  const original=structuredClone(states),receipt=receiptWith(states);
  const before=JSON.stringify(receipt).length;
  compactNativeTypography(receipt);
  assert.equal(receipt.typographyEncoding,TYPOGRAPHY_ENCODING);
  assert.ok(receipt.frames.every(row=>!('typography' in row)&&row.typographyChanges));
  assert.deepEqual(expandNativeTypography(receipt),original);
  const after=JSON.stringify(receipt).length;
  assert.ok(after*10<before,`dense receipt did not shrink: ${before} -> ${after}`);
});

test('a changed row shape or title line count is kept as a whole value, still exact',()=>{
  const first=denseState(0,12,4),second=denseState(90,12,4),third=denseState(95,12,4);
  second.lines=[];third.words.pop();
  const changes=typographyChanges(first,second);
  assert.deepEqual(changes.lines,{value:[]});
  assert.deepEqual(expandTypography(first,changes),second);
  assert.deepEqual(typographyChanges(first,third).words,{value:third.words});
  assert.deepEqual(expandTypography(first,typographyChanges(first,third)),third);
  const extraField=structuredClone(first);extraField.captions[0].extra=1;
  assert.deepEqual(typographyChanges(first,extraField).captions,{value:extraField.captions});
});

test('hash-only forward rows and uncompacted receipts pass through unchanged',()=>{
  const hashed={status:'passed',observedSha256:'a'.repeat(64)};
  const receipt={frames:[{frame:0,typography:hashed},{frame:1,typography:denseState(1,3,2)},{frame:2,typography:denseState(2,3,2)}]};
  const expected=[hashed,denseState(1,3,2),denseState(2,3,2)];
  assert.deepEqual(expandNativeTypography(structuredClone(receipt)),expected);
  compactNativeTypography(receipt);
  assert.deepEqual(receipt.frames[0].typography,hashed);
  assert.deepEqual(expandNativeTypography(receipt),expected);
  const empty={frames:[{frame:0,typography:hashed}]};
  assert.equal(compactNativeTypography(empty).typographyEncoding,undefined);
});

test('a changed state key set or an unknown encoding fails closed',()=>{
  const first=denseState(0,3,2),renamed=structuredClone(first);
  renamed.titleClipX=renamed.titleClip;delete renamed.titleClip;
  const receipt=receiptWith([first,renamed]);
  receipt.frames[1].typography.titleClip=undefined;  // keeps it full-shaped, but the key set differs
  assert.throws(()=>compactNativeTypography(receipt),/keys changed/);
  assert.throws(()=>expandNativeTypography({typographyEncoding:'TEST unknown',frames:[]}),/Unknown typography encoding/);
});

test('the painted caption field compacts exactly, including across a suppression window',()=>{
  // Frames 100-199 are a reasoned caption-free window: nothing is painted even where a phrase's clip is open.
  const painted=(state,frame)=>({...state,captions:state.captions.map(row=>({...row,
    painted:row.clip!=='inset(100%)'&&!(frame>=100&&frame<200)}))});
  const states=Array.from({length:300},(_,frame)=>painted(denseState(frame),frame));
  const original=structuredClone(states),receipt=receiptWith(states),before=JSON.stringify(receipt).length;
  compactNativeTypography(receipt);
  assert.deepEqual(expandNativeTypography(receipt),original);
  assert.equal(receipt.typographyReference.captions[0].painted,true);
  // Inside the window phrase 7's clip is open but it is not painted: only the clip differs from frame 0.
  assert.deepEqual(receipt.frames[150].typographyChanges.captions.rows[7],{clip:'inset(0%)'});
  // After the window phrase 11 is open and painted: both fields are recorded sparsely.
  assert.deepEqual(receipt.frames[250].typographyChanges.captions.rows[11],{clip:'inset(0%)',painted:true});
  assert.ok(JSON.stringify(receipt).length*10<before,'painted rows still compact');
});
