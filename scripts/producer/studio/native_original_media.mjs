/** Exact cached screenshots use admitted PNGs; parent FFmpeg owns original audio delivery. */
import fs from 'node:fs';
import path from 'node:path';
import assert from 'node:assert/strict';

function mediaContractRow(context, item, kind, base) {
  assert.ok(typeof item.src==='string'&&!/^[a-z][a-z0-9+.-]*:|^\/\//i.test(item.src),'Native browser media must be staged locally');
  const source=path.resolve(context.project,item.src),url=new URL(item.src,base);
  assert.ok(source.startsWith(context.project+path.sep)&&fs.realpathSync(source)===source
    &&url.origin===base.origin&&!url.search&&!url.hash,'Native browser media must stay in its canonical project');
  const stat=fs.statSync(source);assert.ok(stat.isFile()&&stat.size>0,'Native browser media requires a nonempty source');
  assert.ok(Number.isFinite(item.start)&&Number.isFinite(item.end)&&item.start>=0&&item.end>item.start,
    'Native suppressed media requires explicit finite timing');
  if(kind==='video')assert.ok(context.cacheEntries.some(row=>row.video.id===item.id&&row.keyBlob.p===source),
    'Native suppressed video lacks an admitted exact frame cache');
  return {url:url.href,source,sourceBytes:stat.size,videoIds:[],audioIds:[]};
}

/** Admit explicit staged media URLs only; the original plan, geometry and cache stay untouched. */
export function nativeOriginalMediaContract(context, serverUrl) {
  const base=new URL('/index.html',serverUrl);assert.ok(base.protocol==='http:'&&['localhost','127.0.0.1'].includes(base.hostname));
  const entries=new Map(),videos=context.result.composition.videos,audios=context.result.composition.audios??[];
  const media=[...videos.map(item=>({kind:'video',item})),...audios.map(item=>({kind:'audio',item}))];
  for(const {kind,item} of media){
    const candidate=mediaContractRow(context,item,kind,base),row=entries.get(candidate.url)??candidate;
    row[kind==='video'?'videoIds':'audioIds'].push(item.id);entries.set(row.url,row);
  }
  assert.ok(entries.size>0,'Native original media contract is empty');
  return [...entries.values()];
}

class NativeOriginalMediaGuard {
  constructor(contract, receipt) {
    this.receipt=receipt;this.rows=new Map(contract.map(row=>[row.url,row]));this.requests=new Map();
    this.pending=new Set();this.errors=[];this.listeners=[];this.client=null;this.page=null;
    Object.assign(receipt,{schemaVersion:1,scope:'exact-cached-native-original-media',status:'preparing',
      contract:contract.map(row=>({...row,suppressedRequests:0,receivedDataBytes:0,receivedEncodedBytes:0})),
      unexpectedMedia:[],requestErrors:[],disposed:false,
      sourceDelivery:'Admitted PNG transport supplies video; parent FFmpeg supplies audio',
      byteEvidence:'CDP Network.dataReceived for exact original URLs; zero is checked, never inferred from cache metadata'});
  }

  fail(message) {
    this.errors.push(message);this.receipt.status='failed';
    if(this.receipt.requestErrors.length<32)this.receipt.requestErrors.push(message);
  }

  listen(emitter, event, listener) {
    emitter.on(event,listener);this.listeners.push(()=>emitter.off(event,listener));
  }

  /** Arm before navigation; an unexpected media payload is an error, not an alternate picture path. */
  async attach(page) {
    this.page=page;this.client=await page.createCDPSession();
    this.listen(this.client,'Network.requestWillBeSent',event=>{
      if(this.rows.has(event.request.url))this.requests.set(event.requestId,event.request.url);
    });
    this.listen(this.client,'Network.dataReceived',event=>this.received(event));
    this.listen(this.client,'Network.loadingFinished',event=>this.requests.delete(event.requestId));
    this.listen(this.client,'Network.loadingFailed',event=>this.requests.delete(event.requestId));
    await this.client.send('Network.enable');
    this.listen(page,'request',request=>{
      const pending=this.intercept(request).catch(error=>this.fail(String(error))).finally(()=>this.pending.delete(pending));
      this.pending.add(pending);
    });
    await page.setRequestInterception(true);this.receipt.status='armed';
  }

  async intercept(request) {
    const url=request.url(),known=this.rows.has(url),type=request.resourceType();
    assert.ok(!request.isInterceptResolutionHandled(),'Original media guard lost request ownership');
    if(known){
      this.receipt.contract.find(row=>row.url===url).suppressedRequests++;
      await request.abort('blockedbyclient');return;
    }
    if(type==='media'){
      if(this.receipt.unexpectedMedia.length<32)this.receipt.unexpectedMedia.push({url,method:request.method()});
      this.fail(`Unexpected native browser media URL: ${url}`);await request.abort('blockedbyclient');return;
    }
    await request.continue();
  }

  received(event) {
    const url=this.requests.get(event.requestId);if(!url)return;
    const row=this.receipt.contract.find(item=>item.url===url);
    if(!Number.isFinite(event.dataLength)||event.dataLength<0||!Number.isFinite(event.encodedDataLength)||event.encodedDataLength<0){
      this.fail('Malformed original-media network byte evidence');return;
    }
    row.receivedDataBytes+=event.dataLength;row.receivedEncodedBytes+=event.encodedDataLength;
    if(event.dataLength||event.encodedDataLength)this.fail(`Original media bytes reached the native browser: ${url}`);
  }

  /** Flush interception completions and reject any observed alternate or original media delivery. */
  async assertHealthy() {
    await Promise.all([...this.pending]);
    assert.equal(this.errors.length,0,this.errors.join('\n'));
    assert.ok(this.receipt.contract.every(row=>row.receivedDataBytes===0&&row.receivedEncodedBytes===0));
  }

  /** Browser/session closure owns cancellation; detach listeners even after a failed page. */
  async dispose() {
    for(const remove of this.listeners)remove();this.listeners=[];
    if(this.client&&!this.client.detached)await this.client.detach();
    await Promise.all([...this.pending]);this.requests.clear();
    this.receipt.disposed=true;
    await this.assertHealthy();this.receipt.status='original-payloads-suppressed';
  }
}

/** Return an owned guard even if setup fails so the existing session cleanup can dispose it. */
export function nativeOriginalMediaGuard(context, serverUrl, receipt) {
  assert.equal(context.request.captureMode,'cached-native-batches','Original-media suppression requires exact cached native batches');
  return new NativeOriginalMediaGuard(nativeOriginalMediaContract(context,serverUrl),receipt);
}
