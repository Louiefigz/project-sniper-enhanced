/** Observe the unchanged native Studio player; no audio gain or clock patches. */
const fs = require('node:fs');

function metrics(samples, start, end) {
  const selected = samples.filter(row => row.clock >= start && row.clock <= end);
  if (selected.length < 2) return {samples:selected.length, passed:false, reason:'insufficient samples'};
  const first = selected[0], last = selected.at(-1);
  const wallSeconds = (last.wall-first.wall)/1000;
  const maxAV = Math.max(...selected.map(row=>Math.abs(row.video-row.audio)));
  const maxAudioClock = Math.max(...selected.map(row=>Math.abs(row.clock-row.audio)));
  const coveredSeconds = last.clock-first.clock;
  const gaps = selected.slice(1).map((row,i)=>row.wall-selected[i].wall);
  const result = {samples:selected.length, maxAV, maxAudioClock, wallSeconds,
    coveredSeconds, progressRatio:wallSeconds>0?coveredSeconds/wallSeconds:0,
    maximumObservationGapMs:Math.max(...gaps), first, last};
  result.passed = maxAV<=.150 && maxAudioClock<=.150 && coveredSeconds>=end-start-.3
    && result.progressRatio>=.95 && result.progressRatio<=1.05 && result.maximumObservationGapMs<=250;
  return result;
}

function audioEvents(events, start, end) {
  const selected=events.filter(row=>row.id==='presenter-audio'&&row.time>=start&&row.time<=end);
  const counts=Object.fromEntries(['seeking','waiting','pause','stalled','error']
    .map(event=>[event,selected.filter(row=>row.event===event).length]));
  return {...counts,passed:Object.values(counts).every(value=>value===0)};
}

async function findPlayer(page) {
  for (let attempt=0; attempt<100; attempt++) {
    for (const frame of page.frames()) {
      if (await frame.evaluate(()=>Boolean(window.__playerReady&&document.querySelector('#native-root')))
        .catch(()=>false)) return frame;
    }
    await new Promise(resolve=>setTimeout(resolve,100));
  }
  throw Error('Current native player did not become ready');
}

function attachObservation() {
  const video=document.querySelector('#presenter'), audio=document.querySelector('#presenter-audio');
  if (!video||!audio) throw Error('Native presenter video and narration are required');
  const proof={samples:[],events:[],overflow:false,initial:{video:video.currentSrc,audio:audio.currentSrc,
    videoMuted:video.muted,audioMuted:audio.muted,audioVolume:audio.volume,
    duration:window.__player.getDuration?.(),rootDuration:document.querySelector('#native-root').dataset.duration}};
  const listeners=[];
  function observe() {
    if(proof.samples.length>=3000){proof.overflow=true;return;}
    const quality=video.getVideoPlaybackQuality();
    proof.samples.push({wall:performance.now(),clock:window.__player.getTime(),video:video.currentTime,
      audio:audio.currentTime,videoPaused:video.paused,audioPaused:audio.paused,videoReady:video.readyState,
      audioReady:audio.readyState,videoSeeking:video.seeking,audioSeeking:audio.seeking,
      videoRate:video.playbackRate,audioRate:audio.playbackRate,
      droppedFrames:quality.droppedVideoFrames,totalFrames:quality.totalVideoFrames,
      audioMuted:audio.muted,audioVolume:audio.volume});
  }
  for(const media of [video,audio]) for(const event of ['seeking','seeked','waiting','playing','pause','ended','stalled','ratechange','error']) {
    const listener=()=>{if(proof.events.length<10000)proof.events.push({event,id:media.id,time:media.currentTime,wall:performance.now()});else proof.overflow=true;};
    media.addEventListener(event,listener);listeners.push([media,event,listener]);
  }
  const timer=setInterval(observe,50);
  window.__nativeAudioObservation={proof,stop(){clearInterval(timer);for(const [m,e,f] of listeners)m.removeEventListener(e,f);return proof;}};
}

async function observe(page, frame, config) {
  await frame.evaluate(()=>window.__player.seek(0));
  await frame.waitForFunction(()=>[...document.querySelectorAll('video,audio')]
    .every(media=>media.readyState>=2&&!media.seeking),{timeout:15000});
  await frame.evaluate(attachObservation);
  await page.waitForFunction(()=>{const button=document.querySelector('button[aria-label="Play"]');return button&&!button.disabled;},{timeout:10000});
  await page.click('button[aria-label="Play"]');
  const started=Date.now();
  let lastHeartbeat=0;
  while(Date.now()-started<70000) {
    const sample=await frame.evaluate(()=>window.__nativeAudioObservation.proof.samples.at(-1));
    if(sample&&sample.clock>=65.2)break;
    if(Date.now()-lastHeartbeat>=5000) {
      const checkpoint=await frame.evaluate(()=>window.__nativeAudioObservation.proof);
      fs.writeFileSync(config.output+'.partial.json',JSON.stringify({status:'partial-observation',checkpoint}));
      console.log(JSON.stringify({phase:'observing',sample}));lastHeartbeat=Date.now();
    }
    await new Promise(resolve=>setTimeout(resolve,250));
  }
  const proof=await frame.evaluate(()=>window.__nativeAudioObservation.stop());
  await frame.evaluate(()=>window.__player.pause());
  return proof;
}

async function run(config) {
  const started=Date.now();
  const result={status:'running',startedAt:new Date().toISOString(),surface:'stock-studio',
    url:config.url,errors:[],badResponses:[],scope:'Playback telemetry, not listening or full-video approval'};
  let browser;
  try {
    const puppeteer=require(config.puppeteerDir);
    browser=await puppeteer.launch({executablePath:config.chrome,headless:true,protocolTimeout:20000,
      args:['--no-sandbox','--autoplay-policy=no-user-gesture-required','--disable-background-networking']});
    result.browserPid=browser.process().pid;
    const page=await browser.newPage();
    await page.setViewport({width:1440,height:1000,deviceScaleFactor:1});
    page.on('pageerror',error=>{if(result.errors.length<100)result.errors.push(String(error));});
    page.on('response',response=>{if(response.status()>=400&&result.badResponses.length<100)result.badResponses.push({status:response.status(),url:response.url()});});
    await page.goto(config.url,{waitUntil:'domcontentloaded',timeout:20000});
    const frame=await findPlayer(page);
    result.playback=await observe(page,frame,config);
    result.opening=metrics(result.playback.samples,.5,65);
    result.complaintWindow=metrics(result.playback.samples,35,65);
    result.audioEvents=audioEvents(result.playback.events,.5,65);
    const audible=result.playback.samples.filter(sample=>sample.clock>.5)
      .every(sample=>!sample.audioMuted&&sample.audioVolume>0&&!sample.audioPaused);
    result.audioEnabledThroughout=audible;
    result.status=result.opening.passed&&result.complaintWindow.passed&&result.audioEvents.passed&&audible&&!result.playback.overflow
      &&!result.errors.length&&!result.badResponses.length?'telemetry-passed':'telemetry-failed';
  } catch(error) {result.status='probe-failed';result.failure={message:error.message,stack:error.stack};}
  finally {
    if(browser)try{await browser.close();}catch(error){result.cleanupError=String(error);result.status='cleanup-failed';}
    result.elapsedSeconds=(Date.now()-started)/1000;
    fs.writeFileSync(config.output,JSON.stringify(result,null,2),{flag:'wx'});
  }
  console.log(JSON.stringify({status:result.status,output:config.output,opening:result.opening,
    complaintWindow:result.complaintWindow,failure:result.failure}));
  return result.status==='telemetry-passed'?0:1;
}

module.exports={metrics,audioEvents};
if(require.main===module) {
  const config=JSON.parse(fs.readFileSync(process.argv[2],'utf8'));
  run(config).then(code=>{process.exitCode=code;}).catch(error=>{console.error(error);process.exitCode=2;});
}
