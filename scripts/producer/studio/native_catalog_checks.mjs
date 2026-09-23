/** Actual mounted-catalog state checks shared by native Short capture and final QC. */
import assert from 'node:assert/strict';

/** The authored transport must declare the complete catalog time windows. */
export function catalogMounts(plan) {
  const markup=plan.extension?.markup??'',mounts=[];
  for(const tag of markup.matchAll(/<[a-z][^>]*\bdata-composition-src\s*=[^>]*>/giu)){
    const attrs=Object.fromEntries([...tag[0].matchAll(/([\w-]+)\s*=\s*(["'])(.*?)\2/gu)].map(row=>[row[1],row[3]]));
    const start=Number(attrs['data-start']),duration=Number(attrs['data-duration']);
    assert.ok(attrs.id&&attrs['data-composition-id']&&Number.isFinite(start)&&start>=0
      &&Number.isFinite(duration)&&duration>0,'Catalog mounts require stable IDs and explicit timing');
    mounts.push({id:attrs.id,composition:attrs['data-composition-id'],file:attrs['data-composition-src'],start,duration});
  }
  const expected=(plan.catalogFiles??[]).map(row=>row.file).sort();
  assert.deepEqual([...new Set(mounts.map(row=>row.file))].sort(),expected,'Catalog mount inventory differs from staged files');
  return mounts;
}

/** Include the arrival, interior and departure of catalog graphics without a built-in title. */
export function catalogCapturePoints(plan) {
  if(!plan.catalogFiles?.length)return [];
  const [num,den]=plan.canvas.frameRate.split('/').map(Number),rate=num/den;
  return catalogMounts(plan).flatMap(row=>[row.start,row.start+row.duration/2,row.start+row.duration]
    .map(time=>Math.round(time*rate)));
}

/** Compiled file identity, timeline registration and full selected title copy remain observable. */
export async function checkCatalogMounts(page, frame, plan) {
  if(!plan.catalogFiles?.length)return;
  const mounts=catalogMounts(plan);
  const values=await page.evaluate(rows=>rows.map(row=>{
    const el=document.getElementById(row.id);
    if(!el)return null;
    const box=el.getBoundingClientRect(),css=getComputedStyle(el);
    return {id:el.id,file:el.getAttribute('data-composition-file')??el.getAttribute('data-composition-src'),
      start:Number(el.dataset.start),duration:Number(el.dataset.duration??el.dataset.hfAuthoredDuration??(Number(el.dataset.end)-Number(el.dataset.start))),width:box.width,height:box.height,
      timeline:!!window.__timelines?.[row.composition],clip:css.clipPath,display:css.display,
      text:el.textContent.replace(/\s+/gu,' ').trim()};
  }),mounts);
  const [num,den]=plan.canvas.frameRate.split('/').map(Number),time=frame*den/num;
  for(const [index,mount] of mounts.entries()){
    const value=values[index];assert.ok(value,`Catalog mount ${mount.id} is absent`);
    assert.equal(value.file,mount.file);assert.equal(value.start,mount.start);assert.equal(value.duration,mount.duration,JSON.stringify(value));
    assert.ok(value.timeline&&value.width>0&&value.height>0,`Catalog mount ${mount.id} is not live`);
    if(mount.start<=time&&time<mount.start+mount.duration){
      assert.notEqual(value.display,'none');assert.notEqual(value.clip,'inset(100%)');
      if(plan.catalogTitle?.file===mount.file)assert.ok(value.text.includes(plan.catalogTitle.copy.text.replace(/\s+/gu,' ').trim()),
        'Mounted catalog title omits the selected canonical copy');
    }
  }
}
