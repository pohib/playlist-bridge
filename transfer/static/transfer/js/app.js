(() => {
  const transferForm=document.getElementById("transfer-form");
  if(transferForm){
    const box=document.getElementById("transfer-status"),title=document.getElementById("job-title"),percent=document.getElementById("progress-value"),bar=document.getElementById("progress-bar"),caption=document.getElementById("progress-caption"),result=document.getElementById("job-result"),submit=transferForm.querySelector('button[type="submit"]');
    const csrf=()=>transferForm.querySelector('input[name="csrfmiddlewaretoken"]')?.value||"";
    async function request(url,options={}){const response=await fetch(url,{credentials:"same-origin",...options,headers:{"Accept":"application/json",...(options.body?{"Content-Type":"application/json"}:{}),...(options.method==="POST"?{"X-CSRFToken":csrf()}:{}),...(options.headers||{})}});const data=await response.json().catch(()=>({}));if(!response.ok)throw new Error(data.error?.message||"Ошибка запроса к API.");return data;}
    function update(job){box.hidden=false;const value=Math.max(0,Math.min(100,Number(job.progress||0)));percent.textContent=value+"%";bar.style.width=value+"%";if(job.status==="queued"){title.textContent="Задача в очереди";caption.textContent="Ожидаем свободный worker…";}else if(job.status==="running"){title.textContent="Идёт подбор композиций";caption.textContent="Обработано "+(job.total?Math.round(job.total*value/100):0)+" из "+(job.total||"…")+" треков";}else if(job.status==="succeeded"){title.textContent="Перенос завершён";caption.textContent="Перенесено "+job.matched+" из "+job.total+". Не найдено: "+job.not_found+"; неоднозначных: "+job.ambiguous+".";result.replaceChildren();const link=document.createElement("a");link.href="/api/v1/transfers/"+encodeURIComponent(job.id)+"/report/";link.textContent="Открыть JSON-отчёт";link.target="_blank";link.rel="noopener noreferrer";result.append(link);submit.disabled=false;}else if(job.status==="failed"){title.textContent="Не удалось выполнить перенос";caption.textContent=job.error||"Неизвестная ошибка.";submit.disabled=false;}}
    async function poll(id){try{const data=await request("/api/v1/transfers/"+encodeURIComponent(id)+"/");update(data.job);if(["queued","running"].includes(data.job.status))window.setTimeout(()=>poll(id),1800);}catch(error){title.textContent="Ошибка получения статуса";caption.textContent=error.message;submit.disabled=false;}}
    transferForm.addEventListener("submit",async event=>{event.preventDefault();result.replaceChildren();title.textContent="Запускаем перенос";caption.textContent="Отправляем задачу в очередь…";box.hidden=false;submit.disabled=true;try{const data=await request("/api/v1/transfers/",{method:"POST",body:JSON.stringify({source_url:transferForm.elements.source_url.value.trim(),target_playlist:transferForm.elements.target_playlist.value.trim()})});update(data.job);if(["queued","running"].includes(data.job.status))poll(data.job.id);}catch(error){title.textContent="Не удалось запустить перенос";caption.textContent=error.message;submit.disabled=false;}});
  }
  const librarySearch=document.getElementById("library-search");
  if(librarySearch)librarySearch.addEventListener("input",()=>{const query=librarySearch.value.trim().toLocaleLowerCase();document.querySelectorAll(".library-card-shell").forEach(card=>{card.hidden=!card.textContent.toLocaleLowerCase().includes(query);});});
  const player=document.getElementById("global-player");if(!player)return;
  const key="playlist-bridge-player-v2",el=id=>document.getElementById(id),audio=el("player-audio"),popoutChannel="BroadcastChannel" in window?new BroadcastChannel("playlist-bridge-player"):null;let popoutWindow=null;
  const ui={cover:el("player-cover"),placeholder:el("player-placeholder"),title:el("player-title"),artist:el("player-artist"),provider:el("player-provider"),embed:el("player-embed"),count:el("player-queue-count"),size:el("player-queue-size"),list:el("player-queue-list"),panel:el("player-queue-panel"),backdrop:el("player-queue-backdrop"),toggle:el("player-queue-toggle"),source:el("player-source-mode"),summary:el("player-queue-summary"),searchResults:el("player-search-results"),transport:el("player-transport"),trackTransport:el("player-track-transport"),play:el("player-play-pause"),repeat:el("player-repeat"),shuffle:el("player-shuffle"),progress:el("player-progress"),currentTime:el("player-current-time"),duration:el("player-duration"),status:el("player-status"),volume:el("player-volume"),mute:el("player-mute"),collapse:el("player-collapse"),expand:el("player-expand"),popout:el("player-popout"),eqOpen:el("player-eq-open"),eqPanel:el("player-eq-panel"),eqClose:el("player-eq-close"),eqEnabled:el("player-eq-enabled"),eqPreset:el("player-eq-preset"),eqPresetNote:el("player-eq-preset-note"),eqPresetName:el("player-eq-preset-name"),eqPresetSave:el("player-eq-preset-save"),eqPresetDelete:el("player-eq-preset-delete"),eqReset:el("player-eq-reset"),eqGraph:el("player-eq-graph"),eqCurve:el("player-eq-curve"),eqArea:el("player-eq-area"),eqPoints:el("player-eq-points"),eqNote:el("player-eq-note"),csrf:document.querySelector("#player-csrf-form input[name=csrfmiddlewaretoken]")};
  audio.crossOrigin="anonymous";
  let state={queue:[],index:0,sourceProviders:["auto"],repeat:"off",shuffle:false,shuffleOrder:[],eqGains:[0,0,0,0,0],eqEnabled:false};
  try{const saved=JSON.parse(localStorage.getItem(key)||"null");if(saved&&Array.isArray(saved.queue)){state={...state,...saved};}}catch(_){}
  state.repeat=["off","all","one"].includes(state.repeat)?state.repeat:"off";state.eqGains=Array.isArray(state.eqGains)&&state.eqGains.length===5?state.eqGains.map(value=>Math.max(-12,Math.min(12,Number(value)||0))):[0,0,0,0,0];state.eqFrequencies=Array.isArray(state.eqFrequencies)&&state.eqFrequencies.length===5?state.eqFrequencies.map(value=>Math.max(20,Math.min(20000,Number(value)||1000))):[60,250,1000,4000,12000];state.eqQs=Array.isArray(state.eqQs)&&state.eqQs.length===5?state.eqQs.map(value=>Math.round(Math.max(.3,Math.min(8,Number(value)||1))*10)/10):[1,1,1,1,1];state.eqPreset=({flat:"reference",bass:"sub808",pop:"silk",rock:"club",jazz:"dusty",electronic:"club"})[state.eqPreset]||(["reference","sub808","kick","darktrap","dusty","silk","vocal","club","air","custom"].includes(state.eqPreset)?state.eqPreset:"custom");state.eqEnabled=Boolean(state.eqEnabled);state.shuffle=Boolean(state.shuffle);state.shuffleOrder=Array.isArray(state.shuffleOrder)?state.shuffleOrder.filter(value=>typeof value==="string"):[];
  state.queue.forEach((track,index)=>{if(!track._queueKey)track._queueKey="queue-"+index+"-"+Math.random().toString(36).slice(2,9);});
  if(state.shuffle){const keys=new Set(state.queue.map(track=>track._queueKey));state.shuffleOrder=state.shuffleOrder.filter(key=>keys.has(key));state.queue.forEach(track=>{if(!state.shuffleOrder.includes(track._queueKey))state.shuffleOrder.push(track._queueKey);});}else{state.shuffleOrder=[];}
  function ensureShuffleOrder(){if(!state.shuffleOrder.length)state.shuffleOrder=state.queue.map(track=>track._queueKey);state.queue.forEach(track=>{if(!state.shuffleOrder.includes(track._queueKey))state.shuffleOrder.push(track._queueKey);});}
  function restoreShuffleOrder(){if(!state.shuffleOrder.length)return;const current=state.queue[state.index]?state.queue[state.index]._queueKey:null;const order=new Map(state.shuffleOrder.map((key,index)=>[key,index]));state.queue.sort((a,b)=>(order.get(a._queueKey)??Number.MAX_SAFE_INTEGER)-(order.get(b._queueKey)??Number.MAX_SAFE_INTEGER));state.index=Math.max(0,state.queue.findIndex(track=>track._queueKey===current));state.shuffleOrder=[];}
  function syncVolumeSlider(){if(ui.volume)ui.volume.style.setProperty("--volume-level",(Number(ui.volume.value)*100)+"%");}
  function newQueueKey(){return "queue-"+Date.now().toString(36)+"-"+Math.random().toString(36).slice(2,10);}state.volume=Number.isFinite(Number(state.volume))?Math.max(0,Math.min(1,Number(state.volume))):0.8;state.collapsed=Boolean(state.collapsed);state.muted=Boolean(state.muted);audio.volume=state.volume;audio.muted=state.muted;ui.volume.value=String(state.volume);syncVolumeSlider();ui.mute.textContent=state.muted?"🔇":state.volume===0?"🔈":"🔊";ui.mute.setAttribute("aria-label",state.muted?"Включить звук":"Выключить звук");player.classList.toggle("is-collapsed",state.collapsed);ui.collapse.hidden=state.collapsed;ui.expand.hidden=!state.collapsed;
  syncPlaybackModes();
  state.sourceProviders=(state.sourceProviders||["auto"]).filter(value=>value!=="vk");if(!state.sourceProviders.length)state.sourceProviders=["auto"];
  state.queue=state.queue.map(track=>{
    if(track&&track.cover)track.cover=sameOriginCover(track.cover);
    if(track&&track.provider==="vk"&&typeof track.stream_url==="string"&&track.stream_url.startsWith("/api/v1/library/tracks/")){
      const match=track.stream_url.match(/^\/api\/v1\/library\/tracks\/([0-9a-f-]+)\/vk-stream\/$/);
      if(match){track.stream_resolve_url=track.stream_resolve_url||track.stream_url;track.stream_url="/library/tracks/"+match[1]+"/vk-audio/";}
    }
    if(track&&track.provider==="vk"&&!track.stream_resolve_url&&typeof track.stream_url==="string"){
      const match=track.stream_url.match(/^\/library\/tracks\/([0-9a-f-]+)\/vk-audio\/$/);
      if(match)track.stream_resolve_url="/api/v1/library/tracks/"+match[1]+"/vk-stream/";
    }
    return track;
  });
  function sameOriginCover(value){if(!value)return "";try{const url=new URL(String(value),window.location.origin);if(url.origin!==window.location.origin||url.pathname!=="/library/cover/"||!url.searchParams.get("track_id"))return "";return url.pathname+url.search;}catch(_){return "";}}
  function providerFor(track){let u;try{u=new URL(String(track.url||""),window.location.origin);}catch(_){return "";}const p=track.provider;if(p==="local"&&u.origin===window.location.origin&&u.pathname.startsWith("/library/tracks/"))return "local";if(p==="vk"&&typeof track.stream_url==="string"&&(/^\/library\/tracks\/[0-9a-f-]+\/vk-audio\/$/.test(track.stream_url)||/^\/api\/v1\/library\/tracks\/[0-9a-f-]+\/vk-stream\/$/.test(track.stream_url)))return "vk";if(u.protocol!=="https:")return "";const h=u.hostname.toLowerCase();if(p==="spotify"&&["open.spotify.com","www.open.spotify.com"].includes(h))return "spotify";if(p==="soundcloud"&&["soundcloud.com","www.soundcloud.com","m.soundcloud.com"].includes(h))return "soundcloud";if(p==="manual"){if(["soundcloud.com","www.soundcloud.com","m.soundcloud.com"].includes(h))return "soundcloud";if(["open.spotify.com","www.open.spotify.com"].includes(h))return "spotify";}return "";}
  function syncPopoutState(){if(!popoutChannel)return;const track=state.queue[state.index];const embedded=Boolean(track&&["spotify","soundcloud"].includes(providerFor(track)));popoutChannel.postMessage({type:"state",source:"main",state,playing:embedded||!audio.paused,currentTime:audio.currentTime||0,duration:Number.isFinite(audio.duration)?audio.duration:0,embedded,status:ui.status.textContent||" "});}
  function persist(){try{localStorage.setItem(key,JSON.stringify(state));}catch(_){}syncPopoutState();}
  const eqMinHz=20,eqMaxHz=20000,eqLeft=24,eqRight=576,eqBottom=156,eqCenter=90,eqGainScale=5.2;
  const eqPresets={
    reference:{label:"REFERENCE / FLAT",description:"Без окраски: нейтральная отправная точка для честной оценки микса.",gains:[0,0,0,0,0]},
    sub808:{label:"808 FOUNDATION",description:"Глубокий саб с чистым низом: фундамент 808 без мутной середины.",gains:[4,-2,-1,0,2]},
    kick:{label:"KICK CUT",description:"Плотный удар и читаемая атака бочки, без лишнего гула в нижней середине.",gains:[3,-2,-1,2,1]},
    darktrap:{label:"LOW-END FOCUS",description:"Тёмный, увесистый вайб: низ впереди, верх приглушён, середина не выпирает.",gains:[4,1,-2,-1,-2]},
    dusty:{label:"DUSTY BOOM BAP",description:"Тёплый сэмплерный оттенок: тело в нижней середине и немного зерна сверху.",gains:[1,2,-1,0,2]},
    silk:{label:"SILK R&B",description:"Мягкий низ, гладкая середина и шелковистый верх без резкости.",gains:[2,-1,1,2,3]},
    vocal:{label:"VOX FORWARD",description:"Вокал выходит вперёд: ясность и присутствие без чрезмерной яркости.",gains:[-2,-1,3,3,1]},
    club:{label:"CLUB TRANSLATE",description:"Собранный клубный баланс: мощный низ, читаемая атака и контролируемый воздух.",gains:[3,1,-1,2,2]},
    air:{label:"AIR & SPACE",description:"Добавляет ощущение открытого верха и пространства, сохраняя низ аккуратным.",gains:[-1,-1,0,2,4]}
  };
  const defaultEqFrequencies=[60,250,1000,4000,12000];let eqContext=null,eqSource=null,eqFilters=[],eqDragIndex=-1,eqKnobDrag=null,eqSelectedIndex=0;
  function eqFrequencyToX(f){return eqLeft+Math.log(Math.max(eqMinHz,Math.min(eqMaxHz,f))/eqMinHz)/Math.log(eqMaxHz/eqMinHz)*(eqRight-eqLeft);}
  function eqXToFrequency(x){return eqMinHz*Math.pow(eqMaxHz/eqMinHz,Math.max(0,Math.min(1,(x-eqLeft)/(eqRight-eqLeft))));}
  function eqSupported(){const track=state.queue[state.index];return Boolean(track&&["local","vk"].includes(providerFor(track)));}
  function ensureEqGraph(){const C=window.AudioContext||window.webkitAudioContext;if(!C)throw new Error("Браузер не поддерживает аудиоэквалайзер.");if(!eqContext){eqContext=new C();eqSource=eqContext.createMediaElementSource(audio);let previous=eqSource;state.eqFrequencies.forEach((f,i)=>{const filter=eqContext.createBiquadFilter();filter.type="peaking";filter.frequency.value=f;filter.Q.value=state.eqQs[i];filter.gain.value=state.eqEnabled?state.eqGains[i]:0;previous.connect(filter);previous=filter;eqFilters.push(filter);});previous.connect(eqContext.destination);}return eqContext;}
  async function activateEq(){const context=ensureEqGraph();if(context.state==="suspended")await context.resume();applyEqGains();}
  async function prepareEqForPlayback(){if(!state.eqEnabled)return;try{await activateEq();}catch(error){state.eqEnabled=false;if(ui.eqEnabled)ui.eqEnabled.checked=false;applyEqGains();if(ui.eqNote)ui.eqNote.textContent=error.message+" Воспроизведение продолжится без обработки.";persist();}}
  function applyEqGains(){if(!eqContext)return;eqFilters.forEach((f,i)=>{f.frequency.setTargetAtTime(state.eqFrequencies[i],eqContext.currentTime,.025);f.Q.setTargetAtTime(state.eqQs[i],eqContext.currentTime,.025);f.gain.setTargetAtTime(state.eqEnabled?state.eqGains[i]:0,eqContext.currentTime,.025);});}
  function drawEqCurve(){
    if(!ui.eqCurve||!ui.eqArea||!ui.eqPoints)return;
    const points=state.eqGains.map((g,i)=>({x:eqFrequencyToX(state.eqFrequencies[i]),y:eqCenter-g*eqGainScale}));
    const samples=[];
    for(let n=0;n<=120;n++){
      const x=eqLeft+(eqRight-eqLeft)*n/120,f=eqXToFrequency(x);
      let response=0;
      state.eqGains.forEach((g,i)=>{
        const width=.48/Math.sqrt(state.eqQs[i]);
        response+=g*Math.exp(-.5*Math.pow(Math.log(f/state.eqFrequencies[i])/width,2));
      });
      samples.push({x,y:eqCenter-Math.max(-12,Math.min(12,response))*eqGainScale});
    }
    const path=samples.map((p,i)=>(i?"L ":"M ")+p.x.toFixed(1)+" "+p.y.toFixed(1)).join(" ");
    ui.eqCurve.setAttribute("d",path);
    ui.eqArea.setAttribute("d",path+" L "+eqRight+" "+eqBottom+" L "+eqLeft+" "+eqBottom+" Z");
    ui.eqPoints.replaceChildren();
    points.forEach((p,i)=>{
      const c=document.createElementNS("http://www.w3.org/2000/svg","circle");
      c.setAttribute("cx",p.x);c.setAttribute("cy",p.y);c.setAttribute("r","7");
      c.setAttribute("class","player-eq-point"+(state.eqEnabled?" is-active":"")+(eqSelectedIndex===i?" is-selected":""));
      c.setAttribute("data-eq-index",String(i));
      c.setAttribute("aria-label","Полоса "+(i+1)+": "+Math.round(state.eqFrequencies[i])+" Гц, "+state.eqGains[i]+" дБ, Q "+state.eqQs[i].toFixed(1));
      ui.eqPoints.append(c);
    });
    document.querySelectorAll("[data-eq-band]").forEach(input=>{
      const i=Number(input.dataset.eqBand),v=state.eqGains[i];
      input.value=String(v);input.nextElementSibling.textContent=(v>0?"+":"")+v+" dB";
    });
    document.querySelectorAll("[data-eq-frequency]").forEach(output=>{
      const f=state.eqFrequencies[Number(output.dataset.eqFrequency)];
      output.textContent=f>=1000?(f/1000).toFixed(f%1000?1:0)+" kHz":Math.round(f)+" Hz";
    });
    document.querySelectorAll("[data-eq-q-knob]").forEach(knob=>{
      const i=Number(knob.dataset.eqQKnob),q=state.eqQs[i];
      knob.style.setProperty("--eq-knob-angle",(-135+(q-.3)/7.7*270)+"deg");
      knob.setAttribute("aria-valuenow",q.toFixed(1));
      knob.setAttribute("aria-valuetext","Q "+q.toFixed(1));
      knob.title="Q "+q.toFixed(1)+" · колесо или перетаскивание";
    });
    document.querySelectorAll("[data-eq-q-value]").forEach(output=>{
      output.textContent=state.eqQs[Number(output.dataset.eqQValue)].toFixed(1);
    });
    if(ui.eqEnabled)ui.eqEnabled.checked=state.eqEnabled;
    if(ui.eqPreset)ui.eqPreset.value=state.eqSavedPresetId?"user:"+state.eqSavedPresetId:state.eqPreset;
    if(ui.eqPresetNote)ui.eqPresetNote.textContent=eqPresets[state.eqPreset]?.description||"Своя настройка: частоты, уровни и Q изменены вручную.";
  }
  function updateEqAvailability(){const ok=eqSupported();document.querySelectorAll("[data-eq-band], [data-eq-q-knob]").forEach(input=>input.disabled=!ok);if(ui.eqEnabled)ui.eqEnabled.disabled=!ok;if(ui.eqPreset)ui.eqPreset.disabled=!ok;if(ui.eqNote)ui.eqNote.textContent=ok?"Перетаскивай точки: вверх/вниз — усиление, влево/вправо — частота; колесо над точкой или крутилка меняют Q.":"Эквалайзер работает с локальными треками и аудио VK; встроенные плееры Spotify и SoundCloud недоступны для обработки.";}
  function setEqOpen(open){if(!ui.eqPanel)return;ui.eqPanel.hidden=!open;ui.eqOpen?.setAttribute("aria-expanded",String(open));if(open){updateEqAvailability();drawEqCurve();}}
  function applyEqPreset(name){if(name==="flat")name="reference";const preset=eqPresets[name];if(!preset)return;state.eqPreset=name;state.eqSavedPresetId=null;state.eqGains=preset.gains.slice();state.eqFrequencies=defaultEqFrequencies.slice();state.eqQs=[1,1,1,1,1];applyEqGains();drawEqCurve();persist();}
  ui.eqPreset?.addEventListener("change",()=>{const value=ui.eqPreset.value;if(value.startsWith("user:"))loadSavedEqPreset(value.slice(5));else applyEqPreset(value);});ui.eqOpen?.addEventListener("click",()=>setEqOpen(ui.eqPanel.hidden));ui.eqClose?.addEventListener("click",()=>setEqOpen(false));
  ui.eqEnabled?.addEventListener("change",async()=>{if(!eqSupported()){ui.eqEnabled.checked=false;return;}state.eqEnabled=ui.eqEnabled.checked;try{if(state.eqEnabled)await activateEq();else applyEqGains();persist();drawEqCurve();}catch(error){state.eqEnabled=false;ui.eqEnabled.checked=false;applyEqGains();if(ui.eqNote)ui.eqNote.textContent=error.message;}});
  document.querySelectorAll("[data-eq-band]").forEach(input=>input.addEventListener("input",()=>{const i=Number(input.dataset.eqBand);state.eqGains[i]=Number(input.value);state.eqPreset="custom";state.eqSavedPresetId=null;drawEqCurve();applyEqGains();persist();}));ui.eqReset?.addEventListener("click",()=>applyEqPreset("flat"));

  const eqPresetEndpoint="/api/v1/player/eq-presets/";
  function eqCsrf(){return ui.csrf?.value||"";}
  async function loadSavedEqPresets(){
    if(!ui.eqPreset)return;
    try{
      const response=await fetch(eqPresetEndpoint,{credentials:"same-origin",headers:{"Accept":"application/json"}});
      if(!response.ok)throw new Error("Не удалось загрузить сохранённые пресеты.");
      const data=await response.json(),selected=ui.eqPreset.value;
      ui.eqPreset.querySelectorAll("option[data-user-preset]").forEach(option=>option.remove());
      (data.presets||[]).forEach(preset=>{
        const option=document.createElement("option");option.value="user:"+preset.id;option.textContent="МОЙ / "+preset.name;option.dataset.userPreset="true";ui.eqPreset.append(option);
      });
      if(selected.startsWith("user:")&&Array.from(ui.eqPreset.options).some(option=>option.value===selected))ui.eqPreset.value=selected;
    }catch(error){if(ui.eqPresetNote)ui.eqPresetNote.textContent=error.message;}
  }
  async function loadSavedEqPreset(id){
    try{
      const response=await fetch(eqPresetEndpoint,{credentials:"same-origin",headers:{"Accept":"application/json"}});
      if(!response.ok)throw new Error("Не удалось получить сохранённый пресет.");
      const data=await response.json(),preset=(data.presets||[]).find(item=>item.id===id);
      if(!preset)throw new Error("Сохранённый пресет не найден.");
      state.eqGains=preset.gains;state.eqFrequencies=preset.frequencies;state.eqQs=preset.qs;
      state.eqPreset="custom";state.eqSavedPresetId=id;applyEqGains();drawEqCurve();persist();
      if(ui.eqPresetNote)ui.eqPresetNote.textContent="Пользовательский пресет: "+preset.name;
    }catch(error){if(ui.eqPresetNote)ui.eqPresetNote.textContent=error.message;ui.eqPreset.value=state.eqPreset;}
  }
  async function saveEqPreset(){
    const name=(ui.eqPresetName?.value||"").trim();
    if(!name){if(ui.eqPresetNote)ui.eqPresetNote.textContent="Укажи название пресета.";ui.eqPresetName?.focus();return;}
    try{
      const response=await fetch(eqPresetEndpoint+"create/",{method:"POST",credentials:"same-origin",headers:{"Accept":"application/json","Content-Type":"application/json","X-CSRFToken":eqCsrf()},body:JSON.stringify({name,gains:state.eqGains,frequencies:state.eqFrequencies,qs:state.eqQs})});
      const data=await response.json();
      if(!response.ok)throw new Error(data.error||"Не удалось сохранить пресет.");
      state.eqSavedPresetId=data.preset.id;state.eqPreset="custom";persist();
      await loadSavedEqPresets();ui.eqPreset.value="user:"+data.preset.id;
      if(ui.eqPresetNote)ui.eqPresetNote.textContent="Сохранён пресет «"+data.preset.name+"». Он привязан к твоему аккаунту.";
    }catch(error){if(ui.eqPresetNote)ui.eqPresetNote.textContent=error.message;}
  }
  async function deleteEqPreset(){
    const value=ui.eqPreset?.value||"";
    if(!value.startsWith("user:")){if(ui.eqPresetNote)ui.eqPresetNote.textContent="Выбери свой сохранённый пресет для удаления.";return;}
    const id=value.slice(5);
    try{
      const response=await fetch(eqPresetEndpoint+encodeURIComponent(id)+"/",{method:"DELETE",credentials:"same-origin",headers:{"X-CSRFToken":eqCsrf(),"Accept":"application/json"}});
      const data=await response.json().catch(()=>({}));
      if(!response.ok)throw new Error(data.error||"Не удалось удалить пресет.");
      state.eqSavedPresetId=null;applyEqPreset("reference");await loadSavedEqPresets();
      if(ui.eqPresetNote)ui.eqPresetNote.textContent="Сохранённый пресет удалён.";
    }catch(error){if(ui.eqPresetNote)ui.eqPresetNote.textContent=error.message;}
  }
  ui.eqPresetSave?.addEventListener("click",saveEqPreset);
  ui.eqPresetDelete?.addEventListener("click",deleteEqPreset);
  ui.eqPresetName?.addEventListener("keydown",event=>{if(event.key==="Enter"){event.preventDefault();saveEqPreset();}});
  loadSavedEqPresets();
  function eqLocalPoint(event){const p=ui.eqGraph.createSVGPoint();p.x=event.clientX;p.y=event.clientY;return p.matrixTransform(ui.eqGraph.getScreenCTM().inverse());}
  function nearestEqPoint(p){
    let index=0,distance=Infinity;
    state.eqGains.forEach((gain,i)=>{
      const dx=eqFrequencyToX(state.eqFrequencies[i])-p.x,dy=eqCenter-gain*eqGainScale-p.y;
      const candidate=Math.hypot(dx,dy);
      if(candidate<distance){distance=candidate;index=i;}
    });
    return {index,distance};
  }
  function setEqQ(index,value){
    const next=Math.round(Math.max(.3,Math.min(8,value))*10)/10;
    if(next===state.eqQs[index])return;
    state.eqQs[index]=next;eqSelectedIndex=index;state.eqPreset="custom";state.eqSavedPresetId=null;
    applyEqGains();drawEqCurve();persist();
  }
  function updateEqFromGraph(p){if(eqDragIndex<0)return;state.eqFrequencies[eqDragIndex]=Math.round(eqXToFrequency(p.x));state.eqGains[eqDragIndex]=Math.round(Math.max(-12,Math.min(12,(eqCenter-p.y)/eqGainScale))*2)/2;eqSelectedIndex=eqDragIndex;state.eqPreset="custom";state.eqSavedPresetId=null;drawEqCurve();applyEqGains();persist();}
  ui.eqGraph?.addEventListener("pointerdown",event=>{
    if(!eqSupported())return;
    const p=eqLocalPoint(event),nearest=nearestEqPoint(p);
    eqDragIndex=nearest.index;eqSelectedIndex=nearest.index;
    ui.eqGraph.setPointerCapture(event.pointerId);updateEqFromGraph(p);
  });
  ui.eqGraph?.addEventListener("pointermove",event=>{if(eqDragIndex>=0)updateEqFromGraph(eqLocalPoint(event));});
  function finishEqDrag(){eqDragIndex=-1;}
  ui.eqGraph?.addEventListener("pointerup",finishEqDrag);ui.eqGraph?.addEventListener("pointercancel",finishEqDrag);
  ui.eqGraph?.addEventListener("wheel",event=>{
    if(!eqSupported())return;
    const nearest=nearestEqPoint(eqLocalPoint(event));
    if(nearest.distance>22)return;
    event.preventDefault();
    setEqQ(nearest.index,state.eqQs[nearest.index]+(event.deltaY<0?.1:-.1));
  },{passive:false});
  document.querySelectorAll("[data-eq-q-knob]").forEach(knob=>{
    const index=Number(knob.dataset.eqQKnob);
    knob.addEventListener("pointerdown",event=>{
      if(!eqSupported())return;
      event.preventDefault();
      eqKnobDrag={index,startY:event.clientY,startQ:state.eqQs[index],pointerId:event.pointerId};
      knob.setPointerCapture(event.pointerId);eqSelectedIndex=index;drawEqCurve();
    });
    knob.addEventListener("pointermove",event=>{
      if(!eqKnobDrag||eqKnobDrag.index!==index||eqKnobDrag.pointerId!==event.pointerId)return;
      setEqQ(index,eqKnobDrag.startQ+(eqKnobDrag.startY-event.clientY)*.05);
    });
    const finishKnobDrag=()=>{eqKnobDrag=null;};
    knob.addEventListener("pointerup",finishKnobDrag);
    knob.addEventListener("pointercancel",finishKnobDrag);
    knob.addEventListener("wheel",event=>{
      if(!eqSupported())return;
      event.preventDefault();setEqQ(index,state.eqQs[index]+(event.deltaY<0?.1:-.1));
    },{passive:false});
    knob.addEventListener("keydown",event=>{
      if(!eqSupported())return;
      if(["ArrowUp","ArrowRight","ArrowDown","ArrowLeft","Home","End"].includes(event.key))event.preventDefault();
      if(event.key==="ArrowUp"||event.key==="ArrowRight")setEqQ(index,state.eqQs[index]+.1);
      else if(event.key==="ArrowDown"||event.key==="ArrowLeft")setEqQ(index,state.eqQs[index]-.1);
      else if(event.key==="Home")setEqQ(index,.3);
      else if(event.key==="End")setEqQ(index,8);
    });
  });
  window.addEventListener("keydown",event=>{if(event.key==="Escape"&&!ui.eqPanel?.hidden)setEqOpen(false);});drawEqCurve();
  function openPopout(){if(popoutWindow&&!popoutWindow.closed){try{popoutWindow.focus();}catch(_){}syncPopoutState();return true;}popoutWindow=window.open("/player/popout/","playlistBridgePlayer","width=190,height=430,resizable=yes,scrollbars=no");if(!popoutWindow){showPlaybackError("Браузер заблокировал дополнительный плеер. Разреши всплывающие окна для сайта и нажми кнопку ещё раз.");return false;}syncPopoutState();return true;}
  ui.popout?.addEventListener("click",openPopout);
  function syncPlaybackModes(){const labels={off:"Повтор выключен",all:"Повтор всей очереди",one:"Повтор текущего трека"};ui.repeat.textContent=state.repeat==="one"?"↻₁":"↻";ui.repeat.title=labels[state.repeat];ui.repeat.setAttribute("aria-label",labels[state.repeat]);ui.repeat.setAttribute("aria-pressed",String(state.repeat!=="off"));ui.repeat.classList.toggle("is-active",state.repeat!=="off");ui.repeat.dataset.mode=state.repeat;ui.shuffle.classList.toggle("is-active",state.shuffle);ui.shuffle.setAttribute("aria-pressed",String(state.shuffle));ui.shuffle.title=state.shuffle?"Выключить перемешивание":"Перемешать очередь";ui.shuffle.setAttribute("aria-label",ui.shuffle.title);}
  function sameQueue(queue){return Array.isArray(queue)&&queue.length===state.queue.length&&queue.every((track,index)=>track&&state.queue[index]&&track.title===state.queue[index].title&&track.url===state.queue[index].url&&track.id===state.queue[index].id);}
  function syncLibraryPlaybackButtons(){
    const data=document.getElementById("playlist-playback-data");
    if(data){try{const queue=JSON.parse(data.textContent||"[]");document.querySelectorAll("[data-track-index]:not([data-add-to-queue])").forEach(button=>{const index=Number(button.dataset.trackIndex);const active=sameQueue(queue)&&index===state.index;button.textContent=active&&!audio.paused?"⏸":"▶";button.setAttribute("aria-label",active&&!audio.paused?"Приостановить воспроизведение":"Воспроизвести композицию");});const playAll=el("play-playlist");if(playAll)playAll.textContent=sameQueue(queue)&&!audio.paused?"⏸ Приостановить плейлист":"▶ Слушать плейлист";}catch(_){}}
    document.querySelectorAll("[data-library-playlist]").forEach(button=>{const node=document.getElementById("library-playback-"+button.dataset.libraryPlaylist);if(!node)return;try{button.textContent=sameQueue(JSON.parse(node.textContent||"[]"))&&!audio.paused?"⏸":"▶";}catch(_){}});
  }
  let collapseAnimation=null;
  function setCollapsed(collapsed){
    const next=Boolean(collapsed);
    if(next===state.collapsed&&!player.classList.contains("is-collapsing"))return;
    if(collapseAnimation){collapseAnimation.cancel();collapseAnimation=null;}
    const first=player.getBoundingClientRect();
    state.collapsed=next;
    player.classList.remove("is-collapsing");
    player.classList.add("is-morphing");
    player.classList.toggle("is-collapsed",next);
    ui.collapse.hidden=next;
    ui.expand.hidden=!next;
    const last=player.getBoundingClientRect();
    const dx=first.left-last.left;
    const dy=first.top-last.top;
    const sx=last.width?first.width/last.width:1;
    const sy=last.height?first.height/last.height:1;
    const shouldAnimate=typeof player.animate==="function"
      &&!window.matchMedia("(prefers-reduced-motion: reduce)").matches
      &&(Math.abs(dx)>1||Math.abs(dy)>1||Math.abs(sx-1)>.01||Math.abs(sy-1)>.01);
    if(shouldAnimate){
      const animation=player.animate(
        [
          {transformOrigin:"top left",transform:"translate3d("+dx+"px,"+dy+"px,0) scale("+sx+","+sy+")"},
          {transformOrigin:"top left",transform:"translate3d(0,0,0) scale(1,1)"}
        ],
        {duration:360,easing:"cubic-bezier(.2,.78,.2,1)",fill:"none"}
      );
      collapseAnimation=animation;
      const cleanup=()=>{
        if(collapseAnimation===animation)collapseAnimation=null;
        player.classList.remove("is-morphing");
      };
      animation.addEventListener("finish",cleanup,{once:true});
      animation.addEventListener("cancel",cleanup,{once:true});
    }else{
      player.classList.remove("is-morphing");
    }
    persist();
  }
  popoutChannel?.addEventListener("message",event=>{
    const message=event.data;if(!message)return;
    if(message.type==="ready"){syncPopoutState();return;}
    if(message.type!=="command"||message.source!=="popout")return;
    if(message.command==="toggle"){togglePlayback();return;}
    if(message.command==="next"){el("player-next").click();return;}
    if(message.command==="previous"){el("player-prev").click();return;}
    if(message.command==="selectIndex"){const index=Number(message.index);if(Number.isInteger(index)&&index>=0&&index<state.queue.length){state.index=index;render();}return;}
    if(message.command==="seek"){if(Number.isFinite(audio.duration)&&audio.duration>0){audio.currentTime=Math.max(0,Math.min(Number(message.value)||0,audio.duration));syncPopoutState();}return;}
    if(message.command==="volume"){const value=Math.max(0,Math.min(1,Number(message.value)||0));audio.volume=value;state.volume=value;if(value>0){audio.muted=false;state.muted=false;}ui.volume.value=String(value);syncVolumeSlider();ui.mute.textContent=audio.muted?"🔇":value===0?"🔈":"🔊";persist();return;}
    if(message.command==="mute"){ui.mute.click();return;}
    if(message.command==="shuffle"){ui.shuffle.click();return;}
    if(message.command==="repeat"){ui.repeat.click();}
  });
  window.addEventListener("focus",()=>{if(popoutWindow?.closed)popoutWindow=null;});
  ui.volume.addEventListener("input",()=>{audio.volume=Number(ui.volume.value);syncVolumeSlider();state.volume=audio.volume;if(audio.volume>0){audio.muted=false;state.muted=false;}ui.mute.textContent=audio.muted?"🔇":audio.volume===0?"🔈":"🔊";ui.mute.setAttribute("aria-label",audio.muted?"Включить звук":"Выключить звук");persist();});
  ui.mute.addEventListener("click",()=>{if(audio.muted||audio.volume===0){if(audio.volume===0){audio.volume=state.volume>0?state.volume:0.8;ui.volume.value=String(audio.volume);syncVolumeSlider();state.volume=audio.volume;}audio.muted=false;state.muted=false;}else{audio.muted=true;state.muted=true;}ui.mute.textContent=audio.muted?"🔇":audio.volume===0?"🔈":"🔊";ui.mute.setAttribute("aria-label",audio.muted?"Включить звук":"Выключить звук");persist();});
  ui.collapse.addEventListener("click",()=>setCollapsed(true));ui.expand.addEventListener("click",()=>setCollapsed(false));
  ui.cover.addEventListener("error",()=>{ui.cover.hidden=true;ui.placeholder.hidden=false;});
  function unsupported(message,track){const span=document.createElement("span");span.textContent=message;ui.embed.append(span);if(track.url){const a=document.createElement("a");a.href=track.url;a.target="_blank";a.rel="noopener noreferrer";a.textContent="Открыть источник";ui.embed.append(a);}const hint=document.createElement("small");hint.className="player-source-hint";hint.textContent="Можно выбрать другой источник в настройках очереди или загрузить аудиофайл.";ui.embed.append(hint);}
  document.addEventListener("error",event=>{const image=event.target;if(!(image instanceof HTMLImageElement)||!image.matches("[data-cover-image]"))return;image.hidden=true;const fallback=image.nextElementSibling;if(fallback)fallback.hidden=false;},true);
  document.addEventListener("submit",event=>{const form=event.target.closest("form[data-confirm-delete]");if(form&&!window.confirm(form.dataset.confirmDelete||"Подтвердить удаление?"))event.preventDefault();});
  function renderQueue(){syncPlaybackModes();ui.list.replaceChildren();state.queue.forEach((track,index)=>{const li=document.createElement("li");li.className="player-queue-item"+(index===state.index?" is-current":"");li.dataset.queueIndex=String(index);const art=document.createElement("span");art.className="player-queue-art";if(track.cover){const image=document.createElement("img");image.src=track.cover;image.alt="";image.loading="lazy";image.referrerPolicy="strict-origin-when-cross-origin";image.addEventListener("error",()=>{image.remove();art.textContent="♫";},{once:true});art.append(image);}else{art.textContent="♫";}const play=document.createElement("button");play.type="button";play.className="player-queue-track";play.title="Воспроизвести";const name=document.createElement("strong");name.textContent=track.title||"Без названия";const artist=document.createElement("small");artist.textContent=track.artist||"Неизвестный исполнитель";play.append(name,artist);play.addEventListener("click",()=>{state.index=index;render();});const controls=document.createElement("div");controls.className="player-queue-item-actions";for(const [label,action,disabled] of [["↑",()=>moveQueueItem(index,-1),index===0],["↓",()=>moveQueueItem(index,1),index===state.queue.length-1],["×",()=>removeQueueItem(index),false]]){const b=document.createElement("button");b.type="button";b.textContent=label;b.setAttribute("aria-label",label==="×"?"Удалить из очереди":label==="↑"?"Переместить выше":"Переместить ниже");b.disabled=disabled;b.addEventListener("click",action);controls.append(b);}li.append(art,play,controls);ui.list.append(li);});ui.size.textContent=String(state.queue.length);ui.summary.textContent=state.queue.length?state.queue.length+" композиций · "+(state.index+1)+" текущая":"Очередь пока пуста";ui.count.textContent=state.queue.length?"В очереди: "+state.queue.length+" · "+(state.index+1)+"/"+state.queue.length:"Очередь пуста";}
  let seeking=false;
  function formatClock(value){if(!Number.isFinite(value)||value<0)return "0:00";const seconds=Math.floor(value);return Math.floor(seconds/60)+":"+String(seconds%60).padStart(2,"0");}
  function updateAudioUi(){if(!audio||!ui.progress)return;const duration=Number.isFinite(audio.duration)?audio.duration:0;ui.progress.max=String(duration||100);if(!seeking)ui.progress.value=String(Math.min(audio.currentTime||0,duration||100));const position=Number(ui.progress.value)||0;const played=duration>0?Math.max(0,Math.min(100,position/duration*100)):0;ui.progress.style.setProperty("--played",played+"%");ui.currentTime.textContent=formatClock(seeking?position:audio.currentTime);ui.duration.textContent=formatClock(duration);if(ui.play)ui.play.textContent=audio.paused?"▶":"⏸";syncLibraryPlaybackButtons();syncPopoutState();}
  audio.addEventListener("timeupdate",updateAudioUi);audio.addEventListener("loadedmetadata",updateAudioUi);audio.addEventListener("durationchange",updateAudioUi);audio.addEventListener("play",updateAudioUi);audio.addEventListener("pause",updateAudioUi);
  audio.addEventListener("waiting",()=>{if(!navigator.onLine)showPlaybackError("Нет подключения к интернету. Проверь соединение и нажми Play.");else if(!ui.status.textContent)ui.status.textContent="Буферизация аудио…";});
  audio.addEventListener("stalled",()=>{if(!navigator.onLine)showPlaybackError("Интернет-соединение потеряно. Воспроизведение приостановлено.");});
  audio.addEventListener("error",()=>{if(!audio.src)return;const code=audio.error?.code;const message=code===3?"Браузер не смог декодировать аудиопоток.":code===4?"Источник отклонил или не поддерживает этот аудиоформат.":!navigator.onLine?"Нет подключения к интернету.":"Соединение с аудиосервером прервано или недоступно.";showPlaybackError(message);});
  function showPlaybackError(message){ui.status.textContent=message;ui.status.dataset.state="error";}
  function clearPlaybackError(){ui.status.textContent="";delete ui.status.dataset.state;}
  window.addEventListener("offline",()=>showPlaybackError("Нет подключения к интернету. Проверь соединение — воспроизведение продолжится после восстановления сети."));
  window.addEventListener("online",()=>{if(ui.status.dataset.state==="error"&&/интернет|соединение/i.test(ui.status.textContent))showPlaybackError("Соединение восстановлено. Нажми Play, чтобы продолжить.");});
  function togglePlayback(){if(audio.paused){const track=state.queue[state.index];if(providerFor(track)==="vk"){const hasReusableStream=Boolean(audio.currentSrc)&&!audio.error;if(hasReusableStream){audio.play().then(clearPlaybackError).catch(()=>{if(audio.error)playVkTrack(track).catch(error=>showPlaybackError(error.message));else showPlaybackError(!navigator.onLine?"Нет подключения к интернету.":"Браузер не разрешил воспроизведение. Попробуй ещё раз.");});}else{playVkTrack(track).catch(error=>showPlaybackError(error.message));}return;}audio.play().then(clearPlaybackError).catch(()=>showPlaybackError(!navigator.onLine?"Нет подключения к интернету.":"Браузер не разрешил воспроизведение. Попробуй ещё раз."));}else audio.pause();}
  ui.play.addEventListener("click",togglePlayback);
  ui.progress.addEventListener("pointerdown",()=>{seeking=true;});
  ui.progress.addEventListener("input",()=>{if(Number.isFinite(audio.duration)&&audio.duration>0){seeking=true;const target=Number(ui.progress.value);ui.currentTime.textContent=formatClock(target);const played=Math.max(0,Math.min(100,target/audio.duration*100));ui.progress.style.setProperty("--played",played+"%");}});
  const finishSeeking=()=>{if(!seeking)return;const target=Number(ui.progress.value);if(Number.isFinite(audio.duration)&&audio.duration>0&&Number.isFinite(target)){try{audio.currentTime=Math.max(0,Math.min(target,audio.duration));}catch(_){}}seeking=false;updateAudioUi();};
  document.addEventListener("pointerup",finishSeeking);ui.progress.addEventListener("pointerup",finishSeeking);ui.progress.addEventListener("pointercancel",finishSeeking);ui.progress.addEventListener("change",finishSeeking);ui.progress.addEventListener("keyup",event=>{if(["ArrowLeft","ArrowRight","Home","End","PageUp","PageDown"].includes(event.key))finishSeeking();});ui.progress.addEventListener("keydown",event=>{if(["ArrowLeft","ArrowRight","Home","End","PageUp","PageDown"].includes(event.key)){seeking=true;requestAnimationFrame(updateAudioUi);}});
  async function resolveVkStream(track,format){if(!navigator.onLine)throw new Error("Нет подключения к интернету.");const resolveUrl=track.stream_resolve_url||(typeof track.stream_url==="string"?track.stream_url.replace(/^\/library\/tracks\/([0-9a-f-]+)\/vk-audio\/$/,"/api/v1/library/tracks/$1/vk-stream/"):"");if(!resolveUrl||resolveUrl===track.stream_url)throw new Error("Для резервного потока VK отсутствует адрес разрешения.");let response;try{response=await fetch(resolveUrl,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","Accept":"application/json","X-CSRFToken":ui.csrf?.value||""},body:JSON.stringify({format}),signal:AbortSignal.timeout(18000)});}catch(error){throw new Error(!navigator.onLine?"Нет подключения к интернету.":error.name==="TimeoutError"?"VK не ответил вовремя.":"Не удалось связаться с VK. Проверь VPN или сетевое соединение.");}const data=await response.json().catch(()=>({}));if(!response.ok||!data.url)throw new Error(data.error||"VK не выдал аудиопоток.");return data.url;}
  function waitForAudio(url){audio.pause();audio.removeAttribute("src");return new Promise((resolve,reject)=>{let settled=false;const finish=(error)=>{if(settled)return;settled=true;clearTimeout(timer);audio.removeEventListener("canplay",ready);audio.removeEventListener("error",failed);error?reject(error):resolve();};const ready=()=>finish();const failed=()=>finish(new Error(!navigator.onLine?"Нет подключения к интернету.":"VK/CDN отклонил аудиопоток или соединение было заблокировано."));const timer=setTimeout(()=>finish(new Error(!navigator.onLine?"Нет подключения к интернету.":"VK/CDN не ответил за отведённое время.")),18000);audio.addEventListener("canplay",ready,{once:true});audio.addEventListener("error",failed,{once:true});audio.src=url;audio.load();});}
  async function playVkTrack(track){
    if(!navigator.onLine)throw new Error("Нет подключения к интернету. Подключись к сети и попробуй снова.");
    await prepareEqForPlayback();
    clearPlaybackError();ui.status.textContent="Подключаем поток VK…";
    try{await waitForAudio(track.stream_url);await audio.play();clearPlaybackError();updateAudioUi();return;}
    catch(mp3Error){
      if(!navigator.onLine)throw new Error("Потеряно подключение к интернету во время загрузки трека.");
      clearPlaybackError();ui.status.textContent="Основной поток недоступен. Проверяем резервный формат…";
      try{const url=await resolveVkStream(track,"hls_ts");await waitForAudio(url);await audio.play();clearPlaybackError();updateAudioUi();return;}
      catch(fallbackError){
        const details=(mp3Error.message+" "+fallbackError.message).toLowerCase();
        if(!navigator.onLine)throw new Error("Нет подключения к интернету. Проверь соединение и попробуй снова.");
        if(/ограничение доступа|content_restricted|недоступен в вашем регионе|правообладател|не предоставил аудиопоток/.test(details))throw new Error("VK ограничил воспроизведение этой композиции. Такое бывает из-за прав, региона или VPN. Мы не можем обойти ограничение VK — попробуй отключить VPN или сменить сервер, либо пропусти трек.");
        if(/blocked|403|forbidden|отклонил|заблокирован/.test(details))throw new Error("VK или его CDN отклонил запрос. VPN, региональная маршрутизация или временное ограничение VK могут мешать загрузке. Попробуй отключить VPN/сменить сервер или пропустить композицию.");
        throw new Error("Не удалось загрузить трек VK. Проверь интернет и VPN. Основной поток: "+mp3Error.message+" Резервный: "+fallbackError.message);
      }
    }
  }function render(){const track=state.queue[state.index];player.hidden=!track;if(!track){renderQueue();return;}ui.title.textContent=track.title||"Без названия";ui.artist.textContent=track.artist||"Неизвестный исполнитель";ui.provider.textContent=(providerFor(track)||"ИСТОЧНИК НЕ ВЫБРАН").toUpperCase();if(track.cover){ui.cover.src=track.cover;ui.cover.hidden=false;ui.placeholder.hidden=true;}else{ui.cover.hidden=true;ui.placeholder.hidden=false;}ui.embed.replaceChildren();audio.pause();audio.removeAttribute("src");audio.hidden=false;ui.transport.hidden=true;ui.trackTransport.hidden=true;clearPlaybackError();const provider=providerFor(track);if(provider==="local"){ui.transport.hidden=false;ui.trackTransport.hidden=false;ui.embed.append(audio);audio.src=track.url;audio.load();if(state.eqEnabled&&eqSupported())prepareEqForPlayback().then(()=>audio.play()).catch(()=>{ui.status.textContent="Нажми Play для начала воспроизведения.";});else audio.play().catch(()=>{ui.status.textContent="Нажми Play для начала воспроизведения.";});}else if(provider==="vk"){ui.transport.hidden=false;ui.trackTransport.hidden=false;ui.embed.append(audio);playVkTrack(track).catch(error=>{showPlaybackError(error.message);});}else if(provider==="spotify"){const id=String(track.id||"").match(/^[A-Za-z0-9]{22}$/);if(!id){unsupported("Некорректный Spotify ID.",track);}else{const frame=document.createElement("iframe");frame.title="Spotify player";frame.src="https://open.spotify.com/embed/track/"+id[0]+"?utm_source=generator&theme=0";frame.allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture";frame.loading="lazy";frame.referrerPolicy="strict-origin-when-cross-origin";ui.embed.append(frame);}}else if(provider==="soundcloud"){const frame=document.createElement("iframe");frame.title="SoundCloud player";frame.src="https://w.soundcloud.com/player/?url="+encodeURIComponent(track.url)+"&auto_play=true&hide_related=true&show_comments=false&show_user=true&visual=false";frame.allow="autoplay";frame.loading="lazy";frame.referrerPolicy="strict-origin-when-cross-origin";ui.embed.append(frame);}else{unsupported("Для этого трека пока нет подтверждённого способа воспроизведения из выбранного источника.",track);}renderQueue();updateEqAvailability();drawEqCurve();persist();}
  function nextTrack(automatic=false){if(!state.queue.length)return;if(automatic&&state.repeat==="one"){audio.currentTime=0;audio.play().catch(()=>{});return;}if(state.index>=state.queue.length-1){if(state.repeat!=="all")return;state.index=0;}else state.index++;render();}
  function playQueue(queue,index=0){const valid=queue.filter(t=>t&&typeof t.title==="string"&&typeof t.url==="string");if(!valid.length)return;valid.forEach(track=>{track._queueKey=newQueueKey();});state.queue=valid;state.index=Math.max(0,Math.min(index,valid.length-1));state.shuffleOrder=state.shuffle?valid.map(track=>track._queueKey):[];if(state.shuffle&&valid.length>state.index+1){for(let i=valid.length-1;i>state.index+1;i--){const j=state.index+1+Math.floor(Math.random()*(i-state.index));[state.queue[i],state.queue[j]]=[state.queue[j],state.queue[i]];}}render();}
  function addQueueItem(track,playNow=false){if(!track||typeof track.title!=="string"||typeof track.url!=="string")return;const duplicate=state.queue.findIndex(t=>t.url===track.url&&t.title===track.title&&t.artist===track.artist);if(duplicate>=0){if(playNow){state.index=duplicate;render();}return;}track._queueKey=newQueueKey();let insertAt=state.queue.length;if(state.shuffle&&state.queue.length){ensureShuffleOrder();state.shuffleOrder.push(track._queueKey);insertAt=state.index+1+Math.floor(Math.random()*(state.queue.length-state.index));state.queue.splice(insertAt,0,track);}else state.queue.push(track);if(state.queue.length===1||playNow){state.index=playNow?insertAt:state.queue.length-1;render();}else{renderQueue();persist();}}
  function removeQueueItem(index){if(index<0||index>=state.queue.length)return;const wasCurrent=index===state.index;const removedTrack=state.queue[index];state.queue.splice(index,1);if(state.shuffle&&removedTrack)state.shuffleOrder=state.shuffleOrder.filter(key=>key!==removedTrack._queueKey);if(!state.queue.length){state.index=0;audio.pause();ui.embed.replaceChildren();player.hidden=true;}else{if(index<state.index)state.index--;else if(wasCurrent)state.index=Math.min(index,state.queue.length-1);render();}renderQueue();persist();}
  function moveQueueItem(index,delta){const target=index+delta;if(target<0||target>=state.queue.length)return;const firstTrack=state.queue[index],secondTrack=state.queue[target];[state.queue[index],state.queue[target]]=[secondTrack,firstTrack];if(state.shuffle){ensureShuffleOrder();const firstOrder=state.shuffleOrder.indexOf(firstTrack._queueKey),secondOrder=state.shuffleOrder.indexOf(secondTrack._queueKey);if(firstOrder>=0&&secondOrder>=0)[state.shuffleOrder[firstOrder],state.shuffleOrder[secondOrder]]=[state.shuffleOrder[secondOrder],state.shuffleOrder[firstOrder]];}if(state.index===index)state.index=target;else if(state.index===target)state.index=index;render();persist();}
  document.addEventListener("keydown",event=>{if((event.key==="Enter"||event.key===" ")&&event.target.matches("[data-track-row-index]")){event.preventDefault();event.target.click();}});
  document.addEventListener("click",event=>{
    const trackRow=event.target.closest("[data-track-row-index]");
    const libraryButton=event.target.closest("[data-library-playlist]");
    const trackButton=event.target.closest("[data-track-index]");
    const playAllButton=event.target.closest("#play-playlist");
    const rowPlay=trackRow&&!event.target.closest("button,form,a,input,select");
    const startsPlayback=Boolean(rowPlay||libraryButton||(trackButton&&!trackButton.hasAttribute("data-add-to-queue"))||playAllButton);
    const data=document.getElementById("playlist-playback-data");
    if(rowPlay){
      if(data){try{const q=JSON.parse(data.textContent||"[]");const index=Number(trackRow.dataset.trackRowIndex);if(Number.isInteger(index)&&index>=0&&index<q.length){if(sameQueue(q)&&state.index===index){if(audio.paused)togglePlayback();else audio.pause();}else playQueue(q,index);}}catch(_){}}
      return;
    }
    if(libraryButton){
      const libraryData=document.getElementById("library-playback-"+libraryButton.dataset.libraryPlaylist);
      if(libraryData){try{const q=JSON.parse(libraryData.textContent||"[]");if(sameQueue(q)){if(audio.paused)togglePlayback();else audio.pause();}else playQueue(q);}catch(_){}}
      return;
    }
    if(trackButton&&data){
      try{const q=JSON.parse(data.textContent||"[]");const index=Number(trackButton.dataset.trackIndex);if(trackButton.hasAttribute("data-add-to-queue"))addQueueItem(q[index]);else if(sameQueue(q)&&state.index===index){if(audio.paused)togglePlayback();else audio.pause();}else playQueue(q,index);}catch(_){}
      return;
    }
    if(playAllButton&&data){
      try{const q=JSON.parse(data.textContent||"[]");if(sameQueue(q)){if(audio.paused)togglePlayback();else audio.pause();}else playQueue(q);}catch(_){}
    }
  });
  el("player-prev").addEventListener("click",()=>{if(state.queue.length){if(state.index>0)state.index--;else if(state.repeat==="all")state.index=state.queue.length-1;else return;render();}});
  el("player-next").addEventListener("click",()=>nextTrack(false));audio.addEventListener("ended",()=>nextTrack(true));
  ui.repeat.addEventListener("click",()=>{state.repeat=state.repeat==="off"?"all":state.repeat==="all"?"one":"off";syncPlaybackModes();persist();});
  ui.shuffle.addEventListener("click",()=>{if(!state.shuffle){state.shuffle=true;state.shuffleOrder=state.queue.map(track=>track._queueKey);if(state.queue.length>state.index+1){for(let i=state.queue.length-1;i>state.index+1;i--){const j=state.index+1+Math.floor(Math.random()*(i-state.index));[state.queue[i],state.queue[j]]=[state.queue[j],state.queue[i]];}}}else{restoreShuffleOrder();state.shuffle=false;}syncPlaybackModes();renderQueue();persist();});
  el("player-clear").addEventListener("click",()=>{state={...state,queue:[],index:0};audio.pause();ui.embed.replaceChildren();player.hidden=true;renderQueue();persist();});
  let queueCloseTimer=0;let queueOpenFrame=0;function setQueueOpen(open){window.clearTimeout(queueCloseTimer);window.cancelAnimationFrame(queueOpenFrame);if(open){ui.panel.hidden=false;ui.backdrop.hidden=false;ui.panel.classList.remove("is-open");ui.backdrop.classList.remove("is-open");queueOpenFrame=requestAnimationFrame(()=>{queueOpenFrame=requestAnimationFrame(()=>{ui.panel.classList.add("is-open");ui.backdrop.classList.add("is-open");});});}else{ui.panel.classList.remove("is-open");ui.backdrop.classList.remove("is-open");queueCloseTimer=window.setTimeout(()=>{ui.panel.hidden=true;ui.backdrop.hidden=true;},230);}ui.toggle.setAttribute("aria-expanded",String(open));document.body.classList.toggle("queue-drawer-open",open);}
  ui.toggle.addEventListener("click",()=>setQueueOpen(ui.panel.hidden));
  ui.backdrop.addEventListener("click",()=>setQueueOpen(false));
  el("player-queue-close").addEventListener("click",()=>setQueueOpen(false));
  document.addEventListener("keydown",event=>{if(event.key==="Escape"&&!ui.panel.hidden)setQueueOpen(false);});
  Array.from(ui.source.options).forEach(option=>{option.selected=(state.sourceProviders||["auto"]).includes(option.value);});
  ui.source.addEventListener("change",()=>{let selected=Array.from(ui.source.selectedOptions).map(option=>option.value);if(selected.includes("auto"))selected=["auto"];else selected=selected.filter(value=>value!=="auto");state.sourceProviders=selected.length?selected:["auto"];Array.from(ui.source.options).forEach(option=>{option.selected=state.sourceProviders.includes(option.value);});persist();});
  function providerLabel(value){return ({vk:"VK",spotify:"Spotify",soundcloud:"SoundCloud",youtube_music:"YouTube Music",apple_music:"Apple Music"})[value]||value;}
  function renderSearchResults(data){ui.searchResults.replaceChildren();const statuses=data.statuses||{};Object.entries(statuses).forEach(([provider,status])=>{const line=document.createElement("small");line.className="player-search-status";line.textContent=providerLabel(provider)+": "+status;ui.searchResults.append(line);});(data.results||[]).forEach(result=>{const card=document.createElement("div");card.className="player-search-result";const meta=document.createElement("div");meta.className="player-search-result-meta";const title=document.createElement("strong");title.textContent=result.title||"Без названия";const artist=document.createElement("small");artist.textContent=(result.artist||"")+(result.provider?" · "+providerLabel(result.provider):"");meta.append(title,artist);card.append(meta);if(result.search_only||!result.playable){const link=document.createElement("a");link.href=result.url;link.target="_blank";link.rel="noopener noreferrer";link.textContent=result.search_only?"Открыть поиск":"Открыть в "+providerLabel(result.provider);card.append(link);}else{const track={provider:result.provider,id:result.id,url:result.url,title:result.title,artist:result.artist,cover:sameOriginCover(result.cover||""),stream_url:result.stream_url||""};const add=document.createElement("button");add.type="button";add.textContent="＋ В очередь";add.addEventListener("click",()=>addQueueItem(track));const play=document.createElement("button");play.type="button";play.textContent="▶ Играть";play.addEventListener("click",()=>{addQueueItem(track,true);});card.append(add,play);}ui.searchResults.append(card);});if(!(data.results||[]).length){const empty=document.createElement("p");empty.textContent="В выбранных сервисах совпадений не найдено. Это не влияет на импортированные плейлисты VK — они остаются в библиотеке.";const upload=document.createElement("a");upload.href="/library/";upload.textContent="Перейти к загрузке аудиофайла";ui.searchResults.append(empty,upload);}}
  el("player-search-current").addEventListener("click",async()=>{const track=state.queue[state.index];if(!track)return;ui.searchResults.replaceChildren();const loading=document.createElement("small");loading.textContent="Ищем совпадения в выбранных сервисах…";ui.searchResults.append(loading);try{const response=await fetch("/api/v1/library/tracks/search/",{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","Accept":"application/json","X-CSRFToken":ui.csrf?.value||""},body:JSON.stringify({title:track.title,artist:track.artist,providers:state.sourceProviders||["auto"]})});const data=await response.json();if(!response.ok)throw new Error(data.error||"Не удалось выполнить поиск.");renderSearchResults(data);}catch(error){ui.searchResults.replaceChildren();const message=document.createElement("small");message.textContent=error.message;ui.searchResults.append(message);}});
  if(state.queue.length)render();else renderQueue();
  // Keep the active provider iframe/audio element mounted while navigating
  // between internal application pages.
  let navigationBusy=false;
  async function navigate(url, push=true){
    if(navigationBusy)return;
    navigationBusy=true;
    try{
      const response=await fetch(url,{credentials:"same-origin",headers:{"X-Requested-With":"XMLHttpRequest"}});
      if(!response.ok||!response.headers.get("content-type")?.includes("text/html"))throw new Error("Navigation failed");
      const html=await response.text(),doc=new DOMParser().parseFromString(html,"text/html");
      const current=doc.querySelector(".page-content"),target=document.querySelector(".page-content");
      if(!current||!target)throw new Error("Page shell not found");
      target.innerHTML=current.innerHTML;document.title=doc.title;
      const nextNav=doc.querySelector(".main-nav"),nav=document.querySelector(".main-nav");if(nextNav&&nav)nav.innerHTML=nextNav.innerHTML;
      const nextMessages=doc.querySelector(".global-messages"),messages=document.querySelector(".global-messages");
      if(nextMessages){if(messages)messages.replaceWith(nextMessages);else document.querySelector(".site-shell")?.insertBefore(nextMessages,target);}
      else messages?.remove();
      if(push)history.pushState({}, "", url);
      window.scrollTo({top:0,behavior:"instant"});
    }catch(_){window.location.assign(url);}
    finally{navigationBusy=false;}
  }
  document.addEventListener("click",event=>{
    const link=event.target.closest("a[href]");
    if(!link||event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey||link.target||link.hasAttribute("download"))return;
    const url=new URL(link.href,window.location.href);
    if(url.origin!==window.location.origin||url.pathname.startsWith("/media/")||url.hash&&url.pathname===window.location.pathname)return;
    if(url.pathname.startsWith("/accounts/")||url.pathname.startsWith("/admin/"))return;
    event.preventDefault();navigate(url.href,true);
  });
  window.addEventListener("popstate",()=>navigate(window.location.href,false));
})();