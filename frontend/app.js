const API_BASE = (window.RESOLVE_CONFIG && window.RESOLVE_CONFIG.API_BASE) || "http://localhost:8000";
const $ = id => document.getElementById(id);
const $$ = s => [...document.querySelectorAll(s)];
const esc = value => String(value ?? "").replace(/[&<>\"]/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
const reduce = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const store = {get(k){try{return localStorage.getItem(k)}catch{return null}},set(k,v){try{localStorage.setItem(k,v);return true}catch{return false}}};
let cases = [];
let current = null;
let view = null;
let filter = "All";
let sort = {k:null,dir:1};
let toastTimer;

function toast(message){const t=$("toast");t.textContent=message;t.classList.add("on");clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.classList.remove("on"),2200)}
function count(el,to){const t0=performance.now();(function f(t){const p=Math.min((t-t0)/500,1);el.textContent=Math.round(to*(1-Math.pow(1-p,3)));if(p<1)requestAnimationFrame(f)})(t0)}
function cls(status){if(status==="No Detected Exception")return "b-ok";if(status==="Needs Attention")return "b-bad";return "b-warn"}
function attention(){return cases.filter(c=>c.status!=="No Detected Exception")}
function humanReview(){return cases.filter(c=>c.human_review && !c.reviewed)}
function humanLabel(c){return c.human_review ? (c.reviewed ? "Reviewed" : "Needed") : "Not needed"}
function scoreLabel(score){return typeof score==="number" ? `${Math.round(score*100)}%` : "—"}
function titleCase(value){return String(value||"").replace(/_/g," ").replace(/\b\w/g,c=>c.toUpperCase())}

async function api(path, options={}){
  const response = await fetch(`${API_BASE}${path}`, options);
  let body = {};
  try{body = await response.json()}catch{body={}}
  if(!response.ok){throw new Error(body?.error?.message || `Request failed (${response.status})`)}
  return body;
}

async function checkApi(){
  const el=$("connection");
  el.className="connection";el.textContent="Checking Resolve API…";
  try{
    const data=await api("/health");
    const ready=data.status==="ready";
    el.classList.add(ready?"ok":"bad");
    el.textContent=ready?"Resolve API ready":"Resolve API needs configuration";
    return ready;
  }catch(error){
    el.classList.add("bad");el.textContent="Resolve API offline";return false;
  }
}

async function loadCases(){
  try{
    const data=await api("/cases");
    cases=Array.isArray(data.cases)?data.cases:[];
    if(current){current=cases.find(c=>c.case_id===current.case_id)||null}
    refresh();
  }catch(error){cases=[];refresh();}
}

function setMetrics(anim=false){
  const values=[cases.length,attention().length,humanReview().length];
  ["reviewed-count","attention-count","human-count"].forEach((id,i)=>anim?count($(id),values[i]):($(id).textContent=values[i]));
}
function greeting(){
  const h=new Date().getHours(),g=h<12?"Good morning":h<18?"Good afternoon":"Good evening",n=attention().length;
  $("sub").textContent=cases.length?`${g}. ${n} case${n===1?"":"s"} currently need${n===1?"s":""} attention.`:`${g}. Upload a beneficiary PDF to run the live Resolve analysis pipeline.`;
}

function fill(tableBody,list){
  tableBody.innerHTML="";
  if(!list.length){tableBody.innerHTML='<tr><td colspan="5" class="empty">No analyzed cases to display.</td></tr>';return}
  list.forEach((c,i)=>{
    const tr=document.createElement("tr");tr.dataset.id=c.case_id;tr.style.animationDelay=`${i*35}ms`;
    if(current&&current.case_id===c.case_id)tr.classList.add("sel");
    tr.innerHTML=`<td><button class="rowbtn" type="button">${esc(c.case_id)}</button></td><td>${esc(c.workflow)}</td><td>${esc(c.client||"—")}</td><td><span class="badge ${cls(c.status)}">${esc(c.status)}</span></td><td>${c.issues?.length||0}</td>`;
    tr.querySelector("button").addEventListener("click",()=>select(c));tableBody.appendChild(tr);
  });
}

const match=(f,c)=>f==="All"?true:f==="Needs Attention"?c.status==="Needs Attention":f==="Human review"?(c.human_review&&!c.reviewed):f==="No Detected Exception"?c.status==="No Detected Exception":f==="Unable to Determine"?c.status==="Unable to Determine":true;
const val=(c,k)=>k==="issues"?(c.issues?.length||0):c[k];
function renderCases(){
  const q=$("q").value.trim().toLowerCase();
  let list=cases.filter(c=>match(filter,c)&&(!q||[c.case_id,c.client,c.workflow,c.account_number].join(" ").toLowerCase().includes(q)));
  if(sort.k)list=[...list].sort((a,b)=>(val(a,sort.k)>val(b,sort.k)?1:val(a,sort.k)<val(b,sort.k)?-1:0)*sort.dir);
  fill($("case-table"),list);
  $$("th[data-col]").forEach(th=>th.setAttribute("aria-sort",th.dataset.col===sort.k?(sort.dir===1?"ascending":"descending"):"none"));
}
function setFilter(f){filter=f;$$("#filters .chip").forEach(x=>x.setAttribute("aria-pressed",x.textContent===f));renderCases()}
["All","Needs Attention","Human review","No Detected Exception","Unable to Determine"].forEach(f=>{const b=document.createElement("button");b.type="button";b.className="chip";b.textContent=f;b.setAttribute("aria-pressed",f==="All");b.onclick=()=>setFilter(f);$("filters").appendChild(b)});
$$('.sort').forEach(b=>b.addEventListener("click",()=>{sort=sort.k===b.dataset.sort?{k:sort.k,dir:-sort.dir}:{k:b.dataset.sort,dir:1};renderCases()}));
$("q").addEventListener("input",renderCases);
$$('[data-goto]').forEach(b=>b.addEventListener("click",()=>{setFilter(b.dataset.goto);go("cases")}));

function findingsHtml(c){
  const findings=c.findings||[];
  if(!findings.length)return '<p class="muted">No exception was detected by the implemented deterministic checks.</p>';
  return findings.map(f=>`<div class="finding"><b>${esc(f.code||"Finding")}</b><p>${esc(f.message||"")}</p>${f.recommended_action?`<p><strong>Recommended action:</strong> ${esc(f.recommended_action)}</p>`:""}</div>`).join("");
}
function factsHtml(facts){
  const entries=Object.entries(facts||{}).filter(([,v])=>v!==null&&v!==undefined&&v!=="");
  if(!entries.length)return '<p class="muted">No structured document facts available.</p>';
  return `<div class="facts">${entries.map(([k,v])=>`<div class="fact"><b>${esc(titleCase(k))}</b>${esc(v)}</div>`).join("")}</div>`;
}
function select(c,quiet=false){
  current=c;
  $$('tr[data-id]').forEach(r=>r.classList.toggle("sel",r.dataset.id===c.case_id));
  const d=$("case-detail");d.className="";
  const agreement=c.ml?.agreement===true?"Agrees with rules":c.ml?.agreement===false?"Differs from rules":"Not comparable";
  d.innerHTML=`
    <div class="kv">
      <div><b>Case</b>${esc(c.case_id)}</div>
      <div><b>Workflow</b>${esc(c.workflow)}</div>
      <div><b>Beneficiary / Entity</b>${esc(c.client||"—")}</div>
      <div><b>Account</b>${esc(c.account_number||"—")}</div>
      <div><b>Status</b><span class="badge ${cls(c.status)}">${esc(c.status)}</span></div>
      <div><b>Human review</b>${esc(humanLabel(c))}</div>
      <div><b>ML signal</b>${esc(scoreLabel(c.ml?.model_score))}</div>
      <div><b>ML vs rules</b>${esc(agreement)}</div>
    </div>
    <h3>Findings and next action</h3>${findingsHtml(c)}
    <h3>Document facts</h3>${factsHtml(c.extraction)}
    ${c.uncertainties?.length?`<h3>Uncertainties</h3><ul>${c.uncertainties.map(u=>`<li>${esc(typeof u==="string"?u:JSON.stringify(u))}</li>`).join("")}</ul>`:""}
    <details><summary>Document evidence</summary><pre>${esc(JSON.stringify(c.evidence||[],null,2))}</pre></details>
    <details><summary>Model note</summary><p class="muted">${esc(c.ml?.score_note||"Experimental model signal.")}</p></details>`;
  $("mark-reviewed").disabled=!c.human_review;
  $("mark-reviewed").textContent=c.reviewed?"Mark needs review":"Mark reviewed";
  if(!quiet){void d.offsetWidth;d.classList.add("pop");$("detail-card").scrollIntoView({behavior:reduce()?"auto":"smooth",block:"nearest"})}
}

$("mark-reviewed").addEventListener("click",async()=>{
  if(!current||!current.human_review)return;
  try{
    const data=await api(`/cases/${encodeURIComponent(current.case_id)}/review`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({reviewed:!current.reviewed})});
    const idx=cases.findIndex(c=>c.case_id===data.case.case_id);if(idx>=0)cases[idx]=data.case;current=data.case;refresh();select(current,true);toast(current.reviewed?"Case marked reviewed":"Case returned to review queue");
  }catch(error){toast(error.message)}
});

function bars(id,map){const el=$(id),max=Math.max(1,...map.map(m=>m[1]));el.innerHTML="";map.forEach(([k,v])=>el.insertAdjacentHTML("beforeend",`<div class="bar-row"><span>${esc(k)}</span><div class="bar"><i data-w="${v/max*100}"></i></div><b>${v}</b></div>`));requestAnimationFrame(()=>requestAnimationFrame(()=>el.querySelectorAll("i").forEach(i=>i.style.width=`${i.dataset.w}%`)))}
const tally=arr=>Object.entries(arr.reduce((a,k)=>(a[k]=(a[k]||0)+1,a),{})).sort((a,b)=>b[1]-a[1]);
function renderReports(){bars("by-status",tally(cases.map(c=>c.status)));bars("by-workflow",tally(cases.map(c=>c.workflow)));const iss=tally(cases.flatMap(c=>c.issue_codes||[]));bars("by-issue",iss.length?iss:[["No issues",0]])}

function refresh(){setMetrics(false);greeting();fill($("dash-table"),attention());renderCases();if(view==="reports")renderReports();if(current)select(current,true)}
function show(v){
  if(!["dashboard","cases","reports","settings"].includes(v))v="dashboard";if(v===view)return;view=v;
  $$('[data-view]').forEach(el=>{const on=el.dataset.view.split(" ").includes(v);el.hidden=!on;el.classList.remove("in");if(on){void el.offsetWidth;el.classList.add("in")}});
  $$('[data-nav]').forEach(b=>b.dataset.nav===v?b.setAttribute("aria-current","page"):b.removeAttribute("aria-current"));
  if(v==="dashboard"){fill($("dash-table"),attention());setMetrics(true)}if(v==="cases")renderCases();if(v==="reports")renderReports();window.scrollTo({top:0});
}
function go(v){show(v);try{history.replaceState(null,"",`#${v}`)}catch{location.hash=v}}
$$('[data-nav]').forEach(b=>b.addEventListener("click",()=>go(b.dataset.nav)));addEventListener("hashchange",()=>show(location.hash.slice(1)));
document.addEventListener("keydown",e=>{if(e.metaKey||e.ctrlKey||e.altKey)return;if(["INPUT","TEXTAREA"].includes(e.target.tagName)){if(e.key==="Escape")e.target.blur();return}if(e.key==="/"){e.preventDefault();go("cases");$("q").focus()}else if(/^[1-4]$/.test(e.key))go(["dashboard","cases","reports","settings"][e.key-1])});

const mq=matchMedia("(prefers-color-scheme: dark)");
function theme(p){document.documentElement.dataset.mode=p==="system"?(mq.matches?"dark":"light"):p;$$('[data-theme-pick]').forEach(b=>b.setAttribute("aria-pressed",b.dataset.themePick===p));store.set("card-theme",p)}
$$('[data-theme-pick]').forEach(b=>b.addEventListener("click",()=>theme(b.dataset.themePick)));mq.addEventListener&&mq.addEventListener("change",()=>{if(store.get("card-theme")==="system")theme("system")});theme(store.get("card-theme")||"light");

$("upload-form").addEventListener("submit",async event=>{
  event.preventDefault();
  const file=$("pdf-file").files[0],status=$("upload-status"),button=$("analyze-btn");
  if(!file)return;
  if(!file.name.toLowerCase().endsWith(".pdf")){status.className="upload-status error";status.textContent="Choose a PDF file.";return}
  const form=new FormData();form.append("file",file);button.disabled=true;status.className="upload-status";status.textContent="Analyzing PDF with Resolve…";
  try{
    const data=await api("/analyze",{method:"POST",body:form});
    const c=data.case;const idx=cases.findIndex(x=>x.case_id===c.case_id);if(idx>=0)cases[idx]=c;else cases.unshift(c);current=c;
    status.className="upload-status success";status.textContent=`Analysis complete: ${c.status}.`;refresh();select(c);toast("Analysis complete");
  }catch(error){status.className="upload-status error";status.textContent=error.message}
  finally{button.disabled=false}
});

$("check-api").addEventListener("click",async()=>{const ok=await checkApi();toast(ok?"Resolve API is ready":"Resolve API is not ready")});
$("clear-cases").addEventListener("click",async()=>{
  if(!confirm("Clear live analyzed case history? Training data and the model will not be changed."))return;
  try{await api("/cases/clear",{method:"POST"});cases=[];current=null;$("case-detail").className="muted";$("case-detail").textContent="Analyze or select a case to see its details.";$("mark-reviewed").disabled=true;refresh();toast("Live case history cleared")}catch(error){toast(error.message)}
});

$("api-location").textContent=API_BASE;
(async function init(){greeting();show((location.hash||"").slice(1)||"dashboard");await checkApi();await loadCases()})();
