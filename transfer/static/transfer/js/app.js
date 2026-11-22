(() => {
 const form=document.getElementById("transfer-form"); if(!form)return;
 const box=document.getElementById("transfer-status"),title=document.getElementById("job-title"),percent=document.getElementById("progress-value"),bar=document.getElementById("progress-bar"),caption=document.getElementById("progress-caption"),result=document.getElementById("job-result"),submit=form.querySelector('button[type="submit"]');
 const csrf=()=>form.querySelector('input[name="csrfmiddlewaretoken"]')?.value||"";
 async function request(url,options={}) {
  const response=await fetch(url,{credentials:"same-origin",...options,headers:{"Accept":"application/json",...(options.body?{"Content-Type":"application/json"}:{}),...(options.method==="POST"?{"X-CSRFToken":csrf()}:{}),...(options.headers||{})}});
  const data=await response.json().catch(()=>({}));
  if(!response.ok)throw new Error(data.error?.message||"Ошибка запроса к API.");
  return data;
 }
 function update(job) {
  box.hidden=false;const value=Math.max(0,Math.min(100,Number(job.progress||0)));percent.textContent=value+"%";bar.style.width=value+"%";
  if(job.status==="queued"){title.textContent="Задача в очереди";caption.textContent="Ожидаем свободного worker…";}
  else if(job.status==="running"){title.textContent="Идёт подбор композиций";caption.textContent="Обработано "+(job.total?Math.round(job.total*value/100):0)+" из "+(job.total||"…")+" треков";}
  else if(job.status==="succeeded"){title.textContent="Перенос завершён";caption.textContent="Перенесено "+job.matched+" из "+job.total+". Не найдено: "+job.not_found+"; неоднозначных: "+job.ambiguous+".";result.replaceChildren();const link=document.createElement("a");link.href="/api/v1/transfers/"+encodeURIComponent(job.id)+"/report/";link.textContent="Открыть JSON-отчёт →";link.target="_blank";link.rel="noopener noreferrer";result.append(link);submit.disabled=false;}
  else if(job.status==="failed"){title.textContent="Не удалось выполнить перенос";caption.textContent=job.error||"Неизвестная ошибка.";submit.disabled=false;}
 }
 async function poll(id){try{const data=await request("/api/v1/transfers/"+encodeURIComponent(id)+"/");update(data.job);if(["queued","running"].includes(data.job.status))window.setTimeout(()=>poll(id),1800);}catch(error){title.textContent="Ошибка получения статуса";caption.textContent=error.message;submit.disabled=false;}}
 form.addEventListener("submit",async event=>{event.preventDefault();result.replaceChildren();title.textContent="Запускаем перенос";caption.textContent="Отправляем задачу в очередь…";box.hidden=false;submit.disabled=true;
  try{const data=await request("/api/v1/transfers/",{method:"POST",body:JSON.stringify({source_url:form.elements.source_url.value.trim(),target_playlist:form.elements.target_playlist.value.trim()})});update(data.job);if(["queued","running"].includes(data.job.status))poll(data.job.id);}
  catch(error){title.textContent="Не удалось запустить перенос";caption.textContent=error.message;submit.disabled=false;}
 });
})();