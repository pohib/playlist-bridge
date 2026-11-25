(() => {
  const KEY = "playlist-bridge-player-v2";
  const CHANNEL = "playlist-bridge-player";
  const $ = id => document.getElementById(id);
  const audio = $("popout-audio");
  const channel = "BroadcastChannel" in window ? new BroadcastChannel(CHANNEL) : null;
  const ui = {
    cover:$("popout-cover"), placeholder:$("popout-placeholder"), provider:$("popout-provider"),
    title:$("popout-title"), artist:$("popout-artist"), progress:$("popout-progress"),
    current:$("popout-current"), duration:$("popout-duration"), play:$("popout-play"),
    prev:$("popout-prev"), next:$("popout-next"), shuffle:$("popout-shuffle"),
    repeat:$("popout-repeat"), volume:$("popout-volume"), volumeValue:$("popout-volume-value"),
    mute:$("popout-mute"), list:$("popout-queue-list"), count:$("popout-queue-count"),
    status:$("popout-status"), embed:$("popout-embed"), csrf:$("popout-csrf").querySelector("[name=csrfmiddlewaretoken]")
  };
  let state = {queue:[],index:0,volume:.8,muted:false,repeat:"off",shuffle:false,shuffleOrder:[]};
  let seeking = false;
  let currentKey = "";
  let suppressState = false;
  const clock = value => {if(!Number.isFinite(value)||value<0)return "0:00";const n=Math.floor(value);return Math.floor(n/60)+":"+String(n%60).padStart(2,"0");};
  const currentTrack = () => state.queue[state.index] || null;
  function save(source="popout") {
    try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (_) {}
    channel?.postMessage({type:"state",source,state,playing:!audio.paused,currentTime:audio.currentTime||0});
  }
  function status(message,error=false){ui.status.textContent=message||"";if(error)ui.status.dataset.state="error";else delete ui.status.dataset.state;}
  function validTrack(track){return track&&typeof track.url==="string"&&typeof track.title==="string";}
  function sameOriginCover(value){if(!value)return "";try{const url=new URL(String(value),location.origin);if(url.origin===location.origin)return url.pathname+url.search;if(url.protocol==="https:")return "/library/cover/?url="+encodeURIComponent(url.href);}catch(_){}return "";}
  function providerFor(track){if(!track)return "";const p=track.provider||"";if(p==="local"&&String(track.url).startsWith("/library/tracks/"))return "local";if(p==="vk"&&typeof track.stream_url==="string"&&track.stream_url.startsWith("/library/tracks/"))return "vk";try{const u=new URL(track.url,location.origin);if(u.protocol!=="https:")return "";if(["open.spotify.com","www.open.spotify.com"].includes(u.hostname)&&p==="spotify")return "spotify";if(["soundcloud.com","www.soundcloud.com","m.soundcloud.com"].includes(u.hostname)&&["soundcloud","manual"].includes(p))return "soundcloud";if(p==="manual"&&["open.spotify.com","www.open.spotify.com"].includes(u.hostname))return "spotify";}catch(_){}return "";}
  function renderQueue(){ui.list.replaceChildren();state.queue.forEach((track,index)=>{const li=document.createElement("li");li.className=index===state.index?"is-current":"";const art=document.createElement("span");art.className="popout-queue-art";if(track.cover){const img=document.createElement("img");img.src=sameOriginCover(track.cover);img.alt="";img.addEventListener("error",()=>{img.remove();art.textContent="♫";},{once:true});art.append(img);}else art.textContent="♫";const copy=document.createElement("span");copy.className="popout-queue-copy";const title=document.createElement("strong");title.textContent=track.title||"Без названия";const artist=document.createElement("small");artist.textContent=track.artist||"Неизвестный исполнитель";copy.append(title,artist);li.append(art,copy);li.addEventListener("click",()=>playIndex(index,true));ui.list.append(li);});ui.count.textContent=state.queue.length+" композиций";}
  function updateTime(){const duration=Number.isFinite(audio.duration)?audio.duration:0;ui.progress.max=String(duration||100);if(!seeking)ui.progress.value=String(Math.min(audio.currentTime||0,duration||100));const value=Number(ui.progress.value)||0;ui.progress.style.setProperty("--level",(duration?value/duration*100:0)+"%");ui.current.textContent=clock(seeking?value:audio.currentTime);ui.duration.textContent=clock(duration);ui.play.textContent=audio.paused?"▶":"Ⅱ";ui.play.title=audio.paused?"Воспроизвести":"Приостановить";ui.play.setAttribute("aria-label",ui.play.title);}
  function syncVolume(){audio.volume=state.volume;audio.muted=state.muted;ui.volume.value=String(state.volume);ui.volume.style.setProperty("--level",(state.volume*100)+"%");ui.volumeValue.textContent=Math.round(state.volume*100)+"%";ui.mute.textContent=state.muted?"🔇":state.volume===0?"🔈":"🔊";ui.mute.setAttribute("aria-label",state.muted?"Включить звук":"Выключить звук");const embedded=["spotify","soundcloud"].includes(providerFor(currentTrack()));ui.volume.disabled=embedded;ui.mute.disabled=embedded;ui.play.disabled=embedded;}
  function syncModes(){ui.shuffle.classList.toggle("is-active",state.shuffle);ui.shuffle.setAttribute("aria-pressed",String(state.shuffle));const labels={off:"Повтор выключен",all:"Повтор всей очереди",one:"Повтор текущего трека"};ui.repeat.textContent=state.repeat==="one"?"↻₁":"↻";ui.repeat.title=labels[state.repeat];ui.repeat.setAttribute("aria-label",labels[state.repeat]);ui.repeat.classList.toggle("is-active",state.repeat!=="off");}
  async function resolveVk(track){const response=await fetch(track.stream_resolve_url||track.stream_url,{method:"POST",credentials:"same-origin",headers:{"Content-Type":"application/json","Accept":"application/json","X-CSRFToken":ui.csrf?.value||""},body:JSON.stringify({format:"hls_ts"})});const data=await response.json().catch(()=>({}));if(!response.ok||!data.url)throw new Error(data.error||"VK не выдал аудиопоток.");return data.url;}
  async function startTrack(autoplay=true){
    const track=currentTrack();if(!track){audio.pause();audio.removeAttribute("src");ui.embed.replaceChildren();ui.title.textContent="Очередь пуста";ui.artist.textContent="Добавь композиции в основном окне";ui.provider.textContent="READY";renderQueue();return;}
    const identity=track._queueKey||track.url+"|"+track.title;
    const changed=identity!==currentKey;currentKey=identity;
    ui.title.textContent=track.title||"Без названия";ui.artist.textContent=track.artist||"Неизвестный исполнитель";
    ui.provider.textContent=(providerFor(track)||"SOURCE").toUpperCase();
    const cover=sameOriginCover(track.cover||"");if(cover){ui.cover.src=cover;ui.cover.hidden=false;ui.placeholder.hidden=true;}else{ui.cover.hidden=true;ui.placeholder.hidden=false;}
    ui.embed.replaceChildren();const provider=providerFor(track);
    if(provider==="spotify"||provider==="soundcloud"){
      audio.pause();audio.removeAttribute("src");ui.progress.disabled=true;
      const frame=document.createElement("iframe");frame.title=provider==="spotify"?"Spotify player":"SoundCloud player";
      const spotifyId=String(track.id||track.url||"").match(/[A-Za-z0-9]{22}/)?.[0]||"";frame.src=provider==="spotify"?"https://open.spotify.com/embed/track/"+spotifyId+"?utm_source=generator&theme=0":"https://w.soundcloud.com/player/?url="+encodeURIComponent(track.url)+"&auto_play="+(autoplay?"true":"false")+"&hide_related=true&show_comments=false&show_user=true&visual=false";
      frame.style.height=provider==="spotify"?"152px":"86px";ui.embed.style.height=provider==="spotify"?"152px":"86px";frame.allow="autoplay; encrypted-media";frame.referrerPolicy="strict-origin-when-cross-origin";ui.embed.append(frame);
      status("Для "+(provider==="spotify"?"Spotify":"SoundCloud")+" используй встроенные элементы управления; громкость регулируется в самом сервисе.");
    }else if(provider==="local"||provider==="vk"){
      ui.progress.disabled=false;
      if(changed){audio.pause();audio.removeAttribute("src");audio.currentTime=0;audio.src=provider==="vk"?track.stream_url:track.url;audio.load();}
      try{if(provider==="vk"&&changed&&autoplay){await audio.play();}else if(autoplay&&audio.paused){await audio.play();}status("");}catch(error){
        if(provider==="vk"&&autoplay){try{const url=await resolveVk(track);audio.src=url;audio.load();await audio.play();status("");}catch(fallback){status(fallback.message,true);}}
        else status("Браузер не смог начать воспроизведение. Нажми Play ещё раз.",true);
      }
    }else{audio.pause();audio.removeAttribute("src");ui.progress.disabled=true;const note=document.createElement("p");note.textContent="Для этого источника нет поддерживаемого аудиопотока. Открой исходную композицию в сервисе.";ui.embed.append(note);status("Источник не поддерживает прямое воспроизведение в отдельном окне.",true);}
    renderQueue();syncVolume();syncModes();updateTime();save();
  }
  function applyState(next,autoplay=false){if(!next||!Array.isArray(next.queue))return;const old=currentTrack()?currentTrack()._queueKey:null;state={...state,...next};state.queue=state.queue.filter(validTrack);state.index=Math.max(0,Math.min(Number(state.index)||0,Math.max(0,state.queue.length-1)));state.volume=Math.max(0,Math.min(1,Number(state.volume??.8)));state.muted=Boolean(state.muted);state.repeat=["off","all","one"].includes(state.repeat)?state.repeat:"off";state.shuffle=Boolean(state.shuffle);const nextKey=currentTrack()?currentTrack()._queueKey:null;syncVolume();syncModes();renderQueue();if(old!==nextKey)startTrack(autoplay);else if(!state.queue.length)startTrack(false);}
  async function playIndex(index,autoplay=true){if(!state.queue.length)return;state.index=Math.max(0,Math.min(index,state.queue.length-1));await startTrack(autoplay);save();}
  function next(){if(!state.queue.length)return;if(state.index>=state.queue.length-1){if(state.repeat!=="all")return;state.index=0;}else state.index++;playIndex(state.index,true);}
  function previous(){if(!state.queue.length)return;if(audio.currentTime>3){audio.currentTime=0;return;}if(state.index>0)state.index--;else if(state.repeat==="all")state.index=state.queue.length-1;else return;playIndex(state.index,true);}
  ui.play.addEventListener("click",()=>{if(audio.paused){audio.play().then(()=>status("")).catch(()=>status("Не удалось начать воспроизведение.",true));}else audio.pause();});
  ui.prev.addEventListener("click",previous);ui.next.addEventListener("click",next);
  ui.progress.addEventListener("pointerdown",()=>seeking=true);ui.progress.addEventListener("input",()=>{if(Number.isFinite(audio.duration)&&audio.duration>0){audio.currentTime=Number(ui.progress.value);updateTime();}});const endSeek=()=>{seeking=false;updateTime();};ui.progress.addEventListener("change",endSeek);ui.progress.addEventListener("pointerup",endSeek);
  ui.volume.addEventListener("input",()=>{state.volume=Number(ui.volume.value);if(state.volume>0)state.muted=false;syncVolume();save();});
  ui.mute.addEventListener("click",()=>{state.muted=!state.muted;syncVolume();save();});
  ui.shuffle.addEventListener("click",()=>{state.shuffle=!state.shuffle;if(state.shuffle&&state.queue.length>2){const current=state.queue.splice(state.index,1)[0];for(let i=state.queue.length-1;i>state.index;i--){const j=state.index+Math.floor(Math.random()*(i-state.index+1));[state.queue[i],state.queue[j]]=[state.queue[j],state.queue[i]];}state.queue.splice(state.index,0,current);}syncModes();renderQueue();save();});
  ui.repeat.addEventListener("click",()=>{state.repeat=state.repeat==="off"?"all":state.repeat==="all"?"one":"off";syncModes();save();});
  audio.addEventListener("timeupdate",updateTime);audio.addEventListener("loadedmetadata",updateTime);audio.addEventListener("play",()=>{updateTime();save();});audio.addEventListener("pause",()=>{updateTime();save();});audio.addEventListener("ended",()=>{if(state.repeat==="one"){audio.currentTime=0;audio.play().catch(()=>{});}else next();});
  $("popout-like").addEventListener("click",()=>window.open("/app/","_blank","noopener"));
  channel?.addEventListener("message",event=>{const message=event.data;if(!message||message.type!=="state"||message.source==="popout")return;const old=currentTrack()?currentTrack()._queueKey:null;const nextState=message.state;if(!nextState||!Array.isArray(nextState.queue))return;const newKey=nextState.queue[nextState.index]?nextState.queue[nextState.index]._queueKey||null:null;state={...state,...nextState};state.queue=state.queue.filter(validTrack);state.index=Math.max(0,Math.min(state.index,state.queue.length-1));syncVolume();syncModes();renderQueue();if(old!==newKey)startTrack(Boolean(message.playing));else if(message.playing&&audio.paused&&["local","vk"].includes(providerFor(currentTrack())))startTrack(true);});
  window.addEventListener("storage",event=>{if(event.key!==KEY||!event.newValue)return;try{const nextState=JSON.parse(event.newValue);applyState(nextState,false);}catch(_){}});
  try{const saved=JSON.parse(localStorage.getItem(KEY)||"null");if(saved&&Array.isArray(saved.queue))applyState(saved,false);else status("Открой плеер из Playlist Bridge, чтобы загрузить очередь.");}catch(_){status("Не удалось прочитать очередь основного плеера.",true);}
  channel?.postMessage({type:"ready"});
  if(!channel)status("Этот браузер не поддерживает синхронизацию между окнами.",true);
})();
