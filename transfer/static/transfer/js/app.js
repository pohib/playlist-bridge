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
  const player=document.getElementById("global-player");if(!player)return;
  const key="playlist-bridge-player-v1",el=id=>document.getElementById(id),audio=el("player-audio");
  const ui={cover:el("player-cover"),placeholder:el("player-placeholder"),title:el("player-title"),artist:el("player-artist"),provider:el("player-provider"),embed:el("player-embed"),count:el("player-queue-count")};
  let state={queue:[],index:0};try{const saved=JSON.parse(localStorage.getItem(key)||"null");if(saved&&Array.isArray(saved.queue))state=saved;}catch(_){}
  function providerFor(track){let u;try{u=new URL(String(track.url||""),window.location.origin);}catch(_){return "";}const p=track.provider;if(p==="local"&&u.origin===window.location.origin&&u.pathname.startsWith("/library/tracks/"))return "local";if(u.protocol!=="https:")return "";const h=u.hostname.toLowerCase();if(p==="spotify"&&["open.spotify.com","www.open.spotify.com"].includes(h))return "spotify";if(p==="soundcloud"&&["soundcloud.com","www.soundcloud.com","m.soundcloud.com"].includes(h))return "soundcloud";if(p==="manual"){if(["soundcloud.com","www.soundcloud.com","m.soundcloud.com"].includes(h))return "soundcloud";if(["open.spotify.com","www.open.spotify.com"].includes(h))return "spotify";}return "";}
  function persist(){try{localStorage.setItem(key,JSON.stringify(state));}catch(_){}}
  function unsupported(message,track){const span=document.createElement("span");span.textContent=message;ui.embed.append(span);if(track.url){const a=document.createElement("a");a.href=track.url;a.target="_blank";a.rel="noopener noreferrer";a.textContent="Открыть источник";ui.embed.append(a);}}
  function render(){const track=state.queue[state.index];player.hidden=!track;if(!track)return;ui.title.textContent=track.title||"Без названия";ui.artist.textContent=track.artist||"Неизвестный исполнитель";ui.provider.textContent=(providerFor(track)||"НЕТ ВСТРОЕННОГО ПЛЕЕРА").toUpperCase();ui.count.textContent="В очереди: "+state.queue.length+" · "+(state.index+1)+"/"+state.queue.length;if(track.cover){ui.cover.src=track.cover;ui.cover.hidden=false;ui.placeholder.hidden=true;}else{ui.cover.hidden=true;ui.placeholder.hidden=false;}ui.embed.replaceChildren();audio.pause();audio.removeAttribute("src");audio.hidden=true;const provider=providerFor(track);if(provider==="local"){audio.src=track.url;audio.hidden=false;audio.onended=()=>{if(state.queue.length){state.index=(state.index+1)%state.queue.length;render();}};ui.embed.append(audio);const playAttempt=audio.play();if(playAttempt&&typeof playAttempt.catch==="function")playAttempt.catch(()=>{});}else if(provider==="spotify"){const id=String(track.id||"").match(/^[A-Za-z0-9]{22}$/);if(!id){unsupported("Некорректный Spotify ID.",track);persist();return;}const frame=document.createElement("iframe");frame.title="Spotify player";frame.src="https://open.spotify.com/embed/track/"+id[0]+"?utm_source=generator&theme=0";frame.allow="autoplay; clipboard-write; encrypted-media; fullscreen; picture-in-picture";frame.loading="lazy";frame.referrerPolicy="strict-origin-when-cross-origin";ui.embed.append(frame);}else if(provider==="soundcloud"){const frame=document.createElement("iframe");frame.title="SoundCloud player";frame.src="https://w.soundcloud.com/player/?url="+encodeURIComponent(track.url)+"&auto_play=true&hide_related=true&show_comments=false&show_user=true&visual=false";frame.allow="autoplay";frame.loading="lazy";frame.referrerPolicy="strict-origin-when-cross-origin";ui.embed.append(frame);}else{unsupported("Этот источник не предоставляет поддерживаемый аудиопоток. Само наличие ссылки VK не позволяет воспроизводить аудио напрямую.",track);}persist();}
  function playQueue(queue,index=0){const valid=queue.filter(t=>t&&typeof t.title==="string"&&typeof t.url==="string");if(!valid.length)return;state={queue:valid,index:Math.max(0,Math.min(index,valid.length-1))};render();}
  document.addEventListener("click",event=>{const button=event.target.closest("[data-track-index]");if(button){const data=document.getElementById("playlist-playback-data");if(data){try{playQueue(JSON.parse(data.textContent||"[]"),Number(button.dataset.trackIndex));}catch(_){}}}if(event.target.closest("#play-playlist")){const data=document.getElementById("playlist-playback-data");if(data){try{playQueue(JSON.parse(data.textContent||"[]"));}catch(_){}}}});
  el("player-prev").addEventListener("click",()=>{if(state.queue.length){state.index=(state.index-1+state.queue.length)%state.queue.length;render();}});
  el("player-next").addEventListener("click",()=>{if(state.queue.length){state.index=(state.index+1)%state.queue.length;render();}});
  el("player-clear").addEventListener("click",()=>{state={queue:[],index:0};persist();ui.embed.replaceChildren();player.hidden=true;});
  if(state.queue.length)render();

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