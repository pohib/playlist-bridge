(() => {
  const CHANNEL="playlist-bridge-player";
  const channel="BroadcastChannel" in window?new BroadcastChannel(CHANNEL):null;
  const $=id=>document.getElementById(id);
  const ui={
    cover:$("popout-cover"),placeholder:$("popout-placeholder"),provider:$("popout-provider"),
    title:$("popout-title"),artist:$("popout-artist"),progress:$("popout-progress"),
    current:$("popout-current"),duration:$("popout-duration"),play:$("popout-play"),
    prev:$("popout-prev"),next:$("popout-next"),shuffle:$("popout-shuffle"),
    repeat:$("popout-repeat"),volume:$("popout-volume"),volumeValue:$("popout-volume-value"),
    mute:$("popout-mute"),list:$("popout-queue-list"),count:$("popout-queue-count"),
    status:$("popout-status"),embed:$("popout-embed")
  };
  let state={queue:[],index:0,volume:.8,muted:false,repeat:"off",shuffle:false};
  let duration=0,currentTime=0,playing=false,embedded=false,seeking=false;
  const clock=value=>{if(!Number.isFinite(value)||value<0)return "0:00";const n=Math.floor(value);return Math.floor(n/60)+":"+String(n%60).padStart(2,"0");};
  const track=()=>state.queue[state.index]||null;
  function command(name,extra={}){channel?.postMessage({type:"command",source:"popout",command:name,...extra});}
  function updateTime(){const max=duration||100;ui.progress.max=String(max);if(!seeking)ui.progress.value=String(Math.min(currentTime,max));const value=Number(ui.progress.value)||0;ui.progress.style.setProperty("--level",(duration?value/duration*100:0)+"%");ui.current.textContent=clock(seeking?value:currentTime);ui.duration.textContent=clock(duration);ui.play.textContent=playing?"Ⅱ":"▶";ui.play.title=playing?"Приостановить":"Воспроизвести";ui.play.setAttribute("aria-label",ui.play.title);}
  function renderQueue(){ui.list.replaceChildren();state.queue.forEach((item,index)=>{const li=document.createElement("li");li.className=index===state.index?"is-current":"";const art=document.createElement("span");art.className="popout-queue-art";if(item.cover){const img=document.createElement("img");img.src=item.cover;img.alt="";img.addEventListener("error",()=>{img.remove();art.textContent="♫";},{once:true});art.append(img);}else art.textContent="♫";const copy=document.createElement("span");copy.className="popout-queue-copy";const title=document.createElement("strong");title.textContent=item.title||"Без названия";const artist=document.createElement("small");artist.textContent=item.artist||"Неизвестный исполнитель";copy.append(title,artist);li.append(art,copy);li.addEventListener("click",()=>command("selectIndex",{index}));ui.list.append(li);});ui.count.textContent=state.queue.length+" композиций";}
  function apply(message){if(!message||message.type!=="state"||message.source!=="main")return;state={...state,...message.state};state.queue=Array.isArray(message.state?.queue)?message.state.queue:[];state.index=Math.max(0,Math.min(Number(state.index)||0,Math.max(0,state.queue.length-1)));duration=Number(message.duration)||0;currentTime=Number(message.currentTime)||0;playing=Boolean(message.playing);embedded=Boolean(message.embedded);ui.title.textContent=track()?.title||"Ожидаем воспроизведение";ui.artist.textContent=track()?.artist||"Playlist Bridge";ui.provider.textContent=(track()?.provider||"READY").toUpperCase();const cover=track()?.cover||"";if(cover){ui.cover.src=cover;ui.cover.hidden=false;ui.placeholder.hidden=true;}else{ui.cover.hidden=true;ui.placeholder.hidden=false;}ui.shuffle.classList.toggle("is-active",Boolean(state.shuffle));ui.repeat.classList.toggle("is-active",state.repeat!=="off");ui.repeat.textContent=state.repeat==="one"?"↻₁":"↻";ui.volume.value=String(Number(state.volume??.8));ui.volume.style.setProperty("--level",(Number(state.volume??.8)*100)+"%");ui.volumeValue.textContent=Math.round(Number(state.volume??.8)*100)+"%";ui.mute.textContent=state.muted?"🔇":Number(state.volume)===0?"🔈":"🔊";ui.play.disabled=embedded;ui.volume.disabled=embedded;ui.mute.disabled=embedded;ui.status.textContent=embedded?"Управление этим источником доступно во встроенном плеере сервиса.":(message.status||"");renderQueue();updateTime();}
  ui.play.addEventListener("click",()=>command("toggle"));
  ui.prev.addEventListener("click",()=>command("previous"));
  ui.next.addEventListener("click",()=>command("next"));
  ui.shuffle.addEventListener("click",()=>command("shuffle"));
  ui.repeat.addEventListener("click",()=>command("repeat"));
  ui.volume.addEventListener("input",()=>{const value=Number(ui.volume.value);ui.volume.style.setProperty("--level",(value*100)+"%");ui.volumeValue.textContent=Math.round(value*100)+"%";});
  ui.volume.addEventListener("change",()=>command("volume",{value:Number(ui.volume.value)}));
  ui.mute.addEventListener("click",()=>command("mute"));
  ui.progress.addEventListener("pointerdown",()=>seeking=true);
  ui.progress.addEventListener("input",()=>{const value=Number(ui.progress.value)||0;ui.current.textContent=clock(value);ui.progress.style.setProperty("--level",(duration?value/duration*100:0)+"%");});
  const endSeek=()=>{if(!seeking)return;seeking=false;command("seek",{value:Number(ui.progress.value)||0});};
  ui.progress.addEventListener("change",endSeek);ui.progress.addEventListener("pointerup",endSeek);ui.progress.addEventListener("pointercancel",endSeek);
  $("popout-like").addEventListener("click",()=>window.open("/app/","_blank","noopener"));
  channel?.addEventListener("message",event=>apply(event.data));
  channel?.postMessage({type:"ready",source:"popout"});
  if(!channel)ui.status.textContent="Браузер не поддерживает синхронизацию между окнами.";
})();