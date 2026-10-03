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
let processingTimer = null;
let processingStartedAt = null;

let MAX_UPLOAD_MB = 100;
let COMPRESSION_TARGET_MB = 0.35;
const TRANSPORT_TOLERANCE = 1.15;

const PDFJS_WORKER = "vendor/pdf.worker.min.js?v=1";

const mb = bytes => bytes / (1024 * 1024);
const sizeLabel = bytes => `${mb(bytes).toFixed(mb(bytes)>=10?1:2)} MB`;

function log(...args){console.log("[R'Solv]", new Date().toISOString(), ...args)}
function logError(...args){console.error("[R'Solv]", new Date().toISOString(), ...args)}
function toast(message){const t=$("toast");t.textContent=message;t.classList.add("on");clearTimeout(toastTimer);toastTimer=setTimeout(()=>t.classList.remove("on"),2400)}
function count(el,to){const t0=performance.now();(function f(t){const p=Math.min((t-t0)/500,1);el.textContent=Math.round(to*(1-Math.pow(1-p,3)));if(p<1)requestAnimationFrame(f)})(t0)}
function cls(status){if(status==="No Detected Exception")return "b-ok";if(status==="Needs Attention")return "b-bad";return "b-warn"}
function attention(){return cases.filter(c=>c.status!=="No Detected Exception")}
function humanReview(){return cases.filter(c=>c.review_status==="awaiting_review")}
function reviewLabel(status){
  return ({
    not_required:"Not Required",
    awaiting_review:"Awaiting Review",
    follow_up_required:"Follow-up Required",
    ready_to_continue:"Ready to Continue"
  })[status] || "Awaiting Review";
}
function reviewClass(status){
  if(status==="ready_to_continue") return "b-ok";
  if(status==="follow_up_required") return "b-bad";
  if(status==="awaiting_review") return "b-warn";
  return "b-neutral";
}
function humanLabel(c){return reviewLabel(c.review_status)}
function scoreLabel(score){return typeof score==="number" ? `${Math.round(score*100)}%` : "—"}
function titleCase(value){return String(value||"").replace(/_/g," ").replace(/\b\w/g,c=>c.toUpperCase())}

async function api(path, options={}){
  log("API request", options.method || "GET", path);
  const started=performance.now();
  try{
    const response = await fetch(`${API_BASE}${path}`, options);
    let body = {};
    try{body = await response.json()}catch{body={}}
    log("API response", response.status, path, `${Math.round(performance.now()-started)}ms`);
    if(!response.ok){throw new Error(body?.error?.message || `Request failed (${response.status})`)}
    return body;
  }catch(error){
    logError("API failure", path, error);
    throw error;
  }
}

function setProcessing(stage, percent, detail){
  $("processing-stage").textContent = stage;
  $("processing-progress").style.width = `${Math.max(0, Math.min(100, percent))}%`;
  if(detail) $("processing-file").innerHTML = detail;
}

function startProcessing(file){
  processingStartedAt=Date.now();
  $("processing-elapsed").textContent="0s";
  $("processing-panel").hidden=false;
  setProcessing("Preparing PDF", 2, `${esc(file.name)} · ${esc(sizeLabel(file.size))}`);
  clearInterval(processingTimer);
  processingTimer=setInterval(()=>{
    const seconds=Math.floor((Date.now()-processingStartedAt)/1000);
    $("processing-elapsed").textContent=`${seconds}s`;
  },500);
  log("Processing UI started", {name:file.name,size:file.size});
}

function stopProcessing(delay=0){
  const finish=()=>{
    clearInterval(processingTimer);
    processingTimer=null;
    if(processingStartedAt){
      log("Processing UI stopped", `${((Date.now()-processingStartedAt)/1000).toFixed(1)}s`);
    }
    processingStartedAt=null;
    $("processing-panel").hidden=true;
    $("processing-progress").style.width="0%";
  };
  delay ? setTimeout(finish, delay) : finish();
}

function updateUploadPolicy(){
  $("file-help").textContent = `PDF only · up to ${MAX_UPLOAD_MB} MB · browser transport target ~${COMPRESSION_TARGET_MB} MB`;
  $("upload-policy").textContent = `Before upload, R'Solv creates a best-effort transport copy targeting about ${COMPRESSION_TARGET_MB} MB. C.A.R.D. analyzes that small copy. Maximum source file: ${MAX_UPLOAD_MB} MB.`;
}

async function checkApi(){
  const el=$("connection");
  el.className="connection";el.textContent="Checking R'Solv API…";
  try{
    const data=await api("/health");
    const ready=data.status==="ready";
    if(Number(data.max_upload_mb)) MAX_UPLOAD_MB=Number(data.max_upload_mb);
    if(Number(data.compression_target_mb)) COMPRESSION_TARGET_MB=Number(data.compression_target_mb);
    updateUploadPolicy();
    el.classList.add(ready?"ok":"bad");
    el.textContent=ready?"R'Solv API ready":"R'Solv API needs configuration";
    log("Health", data);
    return ready;
  }catch(error){
    updateUploadPolicy();
    el.classList.add("bad");el.textContent="R'Solv API offline";
    return false;
  }
}

async function loadCases(){
  try{
    const data=await api("/cases");
    cases=Array.isArray(data.cases)?data.cases:[];
    log("Loaded live cases", cases.length);
    if(current){current=cases.find(c=>c.case_id===current.case_id)||null}
    refresh();
  }catch(error){
    logError("Could not load live cases", error);
    cases=[];refresh();
  }
}

/* ---------- Browser-side PDF compression ---------- */

function requireCompressionLibraries(){
  if(!window.pdfjsLib){
    throw new Error("PDF preparation library did not load. Refresh the page and try again.");
  }
  if(!window.jspdf || !window.jspdf.jsPDF){
    throw new Error("PDF compression library did not load. Refresh the page and try again.");
  }
  window.pdfjsLib.GlobalWorkerOptions.workerSrc = PDFJS_WORKER;
}

async function buildRasterPdf(pdf, profile, attemptIndex, attemptCount, progressCallback){
  const {jsPDF} = window.jspdf;
  let out = null;
  const pages = pdf.numPages;

  for(let pageNumber=1; pageNumber<=pages; pageNumber++){
    const page = await pdf.getPage(pageNumber);
    const originalViewport = page.getViewport({scale:1});
    const renderViewport = page.getViewport({scale:profile.scale});

    const canvas=document.createElement("canvas");
    canvas.width=Math.max(1,Math.floor(renderViewport.width));
    canvas.height=Math.max(1,Math.floor(renderViewport.height));
    const ctx=canvas.getContext("2d",{alpha:false});
    ctx.fillStyle="#ffffff";
    ctx.fillRect(0,0,canvas.width,canvas.height);

    await page.render({
      canvasContext:ctx,
      viewport:renderViewport,
      background:"#ffffff"
    }).promise;

    const imageData=canvas.toDataURL("image/jpeg",profile.quality);
    const orientation=originalViewport.width>originalViewport.height ? "landscape" : "portrait";

    if(!out){
      out=new jsPDF({
        unit:"pt",
        format:[originalViewport.width,originalViewport.height],
        orientation,
        compress:true,
        putOnlyUsedFonts:true,
      });
    }else{
      out.addPage([originalViewport.width,originalViewport.height],orientation);
    }

    out.addImage(
      imageData,
      "JPEG",
      0,
      0,
      originalViewport.width,
      originalViewport.height,
      undefined,
      "FAST"
    );

    canvas.width=1;
    canvas.height=1;

    const withinAttempt=pageNumber/pages;
    const base=8+(attemptIndex/attemptCount)*42;
    const span=42/attemptCount;
    progressCallback(Math.min(52,base+withinAttempt*span));
  }

  return out.output("blob");
}

async function preparePdfForUpload(file, progressCallback){
  const targetBytes = Math.round(COMPRESSION_TARGET_MB*1024*1024);

  if(file.size<=targetBytes){
    log("Compression skipped; source already at or below transport target", {
      originalBytes:file.size,
      targetBytes
    });
    return {
      blob:file,
      filename:file.name,
      mode:"original",
      originalBytes:file.size,
      transportBytes:file.size,
      targetReached:true,
    };
  }

  requireCompressionLibraries();

  progressCallback(5);
  log("Browser PDF compression started", {
    filename:file.name,
    originalMB:mb(file.size).toFixed(2),
    targetMB:COMPRESSION_TARGET_MB
  });

  const source=await file.arrayBuffer();
  const pdf=await window.pdfjsLib.getDocument({data:source}).promise;
  log("PDF loaded in browser", {pages:pdf.numPages});

  // Each pass trades resolution for size. We stop as soon as the target is reached.
  const profiles=[
    {scale:1.15,quality:.68,label:"high"},
    {scale:1.00,quality:.58,label:"medium-high"},
    {scale:.88,quality:.48,label:"medium"},
    {scale:.76,quality:.40,label:"compact"},
    {scale:.65,quality:.32,label:"small"},
    {scale:.55,quality:.26,label:"smaller"},
    {scale:.48,quality:.22,label:"minimum"},
  ];

  let best=null;

  for(let i=0;i<profiles.length;i++){
    const profile=profiles[i];
    setProcessing(
      `Compressing PDF · ${profile.label}`,
      8+(i/profiles.length)*42,
      `${esc(file.name)} · original <strong>${esc(sizeLabel(file.size))}</strong> · target <strong>~${esc(COMPRESSION_TARGET_MB)} MB</strong>`
    );

    const blob=await buildRasterPdf(pdf,profile,i,profiles.length,progressCallback);

    log("Compression pass complete", {
      profile:profile.label,
      scale:profile.scale,
      quality:profile.quality,
      outputMB:mb(blob.size).toFixed(2)
    });

    if(!best || blob.size<best.blob.size){
      best={blob,profile};
    }

    if(blob.size<=targetBytes*TRANSPORT_TOLERANCE){
      break;
    }
  }

  if(!best){
    throw new Error("R'Solv could not prepare this PDF for upload.");
  }

  const transportName=file.name.replace(/\.pdf$/i,"")+"_transport.pdf";
  const reached=best.blob.size<=targetBytes*TRANSPORT_TOLERANCE;

  log("Browser PDF compression complete", {
    originalMB:mb(file.size).toFixed(2),
    transportMB:mb(best.blob.size).toFixed(2),
    targetMB:COMPRESSION_TARGET_MB,
    profile:best.profile.label,
    targetReached:reached,
  });

  setProcessing(
    reached ? "PDF prepared for upload" : "Using smallest readable transport copy",
    54,
    `${esc(file.name)} · <strong>${esc(sizeLabel(file.size))}</strong> → <strong>${esc(sizeLabel(best.blob.size))}</strong>`
  );

  return {
    blob:best.blob,
    filename:transportName,
    mode:"browser_raster",
    originalBytes:file.size,
    transportBytes:best.blob.size,
    targetReached:reached,
  };
}

/* ---------- Real upload progress ---------- */

function uploadAnalyze(formData, onUploadProgress){
  return new Promise((resolve,reject)=>{
    const xhr=new XMLHttpRequest();
    const started=performance.now();

    xhr.open("POST",`${API_BASE}/analyze`,true);
    xhr.responseType="json";

    xhr.upload.onprogress=event=>{
      if(event.lengthComputable){
        const fraction=event.loaded/event.total;
        onUploadProgress(fraction);
        log("Upload progress", `${Math.round(fraction*100)}%`);
      }
    };

    xhr.upload.onload=()=>{
      log("Browser upload complete; waiting for C.A.R.D. analysis");
      setProcessing("Upload complete · C.A.R.D. is analyzing",82,$("processing-file").innerHTML);
    };

    xhr.onerror=()=>{
      const error=new Error("Network error while uploading the PDF.");
      logError("Upload failed",error);
      reject(error);
    };

    xhr.ontimeout=()=>{
      reject(new Error("The upload timed out."));
    };

    xhr.onload=()=>{
      const body=xhr.response || {};
      log("API response",xhr.status,"/analyze",`${Math.round(performance.now()-started)}ms`);
      if(xhr.status>=200 && xhr.status<300){
        resolve(body);
      }else{
        reject(new Error(body?.error?.message || `Request failed (${xhr.status})`));
      }
    };

    xhr.send(formData);
  });
}

/* ---------- Existing dashboard behavior ---------- */

function setMetrics(anim=false){
  const values=[cases.length,attention().length,humanReview().length];
  ["reviewed-count","attention-count","human-count"].forEach((id,i)=>anim?count($(id),values[i]):($(id).textContent=values[i]));
}
function greeting(){
  const h=new Date().getHours(),g=h<12?"Good morning":h<18?"Good afternoon":"Good evening",n=attention().length;
  $("sub").textContent=cases.length?`${g}. ${n} case${n===1?"":"s"} currently need${n===1?"s":""} attention.`:`${g}. Upload a beneficiary claim package to run the live R'Solv analysis pipeline.`;
}

function fill(tableBody,list){
  tableBody.innerHTML="";
  if(!list.length){tableBody.innerHTML='<tr><td colspan="5" class="empty">No analyzed cases to display.</td></tr>';return}
  list.forEach((c,i)=>{
    const tr=document.createElement("tr");tr.dataset.id=c.case_id;tr.style.animationDelay=`${i*30}ms`;
    if(current&&current.case_id===c.case_id)tr.classList.add("sel");
    tr.innerHTML=`<td><button class="rowbtn" type="button">${esc(c.case_id)}</button></td><td>${esc(c.workflow)}</td><td>${esc(c.client||"—")}</td><td><span class="badge ${cls(c.status)}">${esc(c.status)}</span></td><td>${c.issues?.length||0}</td>`;
    tr.querySelector("button").addEventListener("click",()=>select(c));tableBody.appendChild(tr);
  });
}

const match=(f,c)=>f==="All"?true:f==="Needs Attention"?c.status==="Needs Attention":f==="Awaiting Human Review"?c.review_status==="awaiting_review":f==="Follow-up Required"?c.review_status==="follow_up_required":f==="Ready to Continue"?c.review_status==="ready_to_continue":f==="No Detected Exception"?c.status==="No Detected Exception":f==="Unable to Determine"?c.status==="Unable to Determine":true;
const val=(c,k)=>k==="issues"?(c.issues?.length||0):c[k];
function renderCases(){
  const q=$("q").value.trim().toLowerCase();
  let list=cases.filter(c=>match(filter,c)&&(!q||[c.case_id,c.client,c.workflow,c.account_number].join(" ").toLowerCase().includes(q)));
  if(sort.k)list=[...list].sort((a,b)=>(val(a,sort.k)>val(b,sort.k)?1:val(a,sort.k)<val(b,sort.k)?-1:0)*sort.dir);
  fill($("case-table"),list);
  $$("th[data-col]").forEach(th=>th.setAttribute("aria-sort",th.dataset.col===sort.k?(sort.dir===1?"ascending":"descending"):"none"));
}
function setFilter(f){filter=f;$$("#filters .chip").forEach(x=>x.setAttribute("aria-pressed",x.textContent===f));renderCases()}
["All","Needs Attention","Awaiting Human Review","Follow-up Required","Ready to Continue","No Detected Exception","Unable to Determine"].forEach(f=>{const b=document.createElement("button");b.type="button";b.className="chip";b.textContent=f;b.setAttribute("aria-pressed",f==="All");b.onclick=()=>setFilter(f);$("filters").appendChild(b)});
$$('.sort').forEach(b=>b.addEventListener("click",()=>{sort=sort.k===b.dataset.sort?{k:sort.k,dir:-sort.dir}:{k:b.dataset.sort,dir:1};renderCases()}));
$("q").addEventListener("input",renderCases);
$$('[data-goto]').forEach(b=>b.addEventListener("click",()=>{setFilter(b.dataset.goto);go("cases")}));

function findingsHtml(c){
  const findings=c.findings||[];
  if(!findings.length)return '<p class="muted">No exception was detected by the implemented deterministic checks.</p>';
  return `<div class="findings-list">${findings.map(f=>`<div class="finding"><b>${esc(f.code||"Finding")}</b><p>${esc(f.message||"")}</p>${f.recommended_action?`<p><strong>Next action:</strong> ${esc(f.recommended_action)}</p>`:""}</div>`).join("")}</div>`;
}
function factsHtml(facts){
  const entries=Object.entries(facts||{}).filter(([,v])=>v!==null&&v!==undefined&&v!=="");
  if(!entries.length)return '<p class="muted">No structured document facts available.</p>';
  return `<div class="facts">${entries.map(([k,v])=>`<div class="fact"><b>${esc(titleCase(k))}</b><span>${esc(v)}</span></div>`).join("")}</div>`;
}
function notesHtml(items,review=false){
  if(!items?.length)return "";
  return `<div class="notes-list">${items.map(item=>{
    const field=typeof item==="object"?(item.label||titleCase(item.field||"Note")):"Note";
    const reason=typeof item==="object"?(item.reason||item.message||"") : item;
    return `<div class="note-card ${review?"review":""}"><span class="note-label">${esc(field)}</span><div class="note-copy"><p>${esc(reason)}</p></div></div>`;
  }).join("")}</div>`;
}
function evidenceHtml(items){
  if(!items?.length)return '<p class="muted">No document evidence snippets were returned.</p>';
  return `<div class="evidence-list">${items.map(item=>{
    if(typeof item!=="object")return `<div class="evidence-item"><p>${esc(item)}</p></div>`;
    const field=item.field||item.label||"Evidence";
    const value=item.value||item.evidence||item.text||item.quote||item.reason||JSON.stringify(item);
    return `<div class="evidence-item"><b>${esc(titleCase(field))}</b><p>${esc(value)}</p></div>`;
  }).join("")}</div>`;
}


function disagreementHtml(c){
  if(c.ml?.agreement!==false) return "";
  return `<div class="signal-disagreement"><div><strong>Signal disagreement</strong><p>Deterministic rules returned <b>${esc(c.status)}</b>, while the experimental ML signal returned <b>${esc(titleCase(c.ml?.prediction||"unknown"))}</b>. The deterministic requirement remains authoritative and the disagreement is surfaced for human review.</p></div></div>`;
}

function traceHtml(trace){
  if(!trace?.length) return "";
  return `<div class="trace-list">${trace.map(t=>`
    <div class="trace-card">
      <strong>${esc(t.code||"Decision trace")}</strong>
      <div class="trace-flow">
        <div class="trace-node"><b>Document evidence</b><p>${esc(t.evidence||"No direct snippet was captured.")}</p></div>
        <div class="trace-arrow">→</div>
        <div class="trace-node"><b>Structured fact</b><p>${esc(titleCase(t.field))}: ${esc(t.fact_value)}</p></div>
        <div class="trace-arrow">→</div>
        <div class="trace-node rule"><b>Rule</b><p>${esc(t.rule)}</p></div>
        <div class="trace-arrow">→</div>
        <div class="trace-node result"><b>Result</b><p>${esc(t.result)}</p></div>
      </div>
    </div>`).join("")}</div>`;
}

function resolutionHtml(items){
  if(!items?.length) return '<p class="muted">No automatic resolution preview is available for this finding.</p>';
  return `<div class="resolution-list">${items.map(item=>`
    <div class="resolution-card">
      <div class="resolution-copy">
        <b>${esc(item.title)}</b>
        <p>${esc(item.current_label)}: <strong>${esc(item.current_value)}</strong></p>
        <p>${esc(item.change_description)}</p>
        <p class="muted">${esc(item.effect)}</p>
      </div>
    </div>`).join("")}</div>`;
}

function reviewHistoryHtml(c){
  const events=c.review_history||[];
  if(!events.length) return '<p class="muted">No human review actions have been recorded yet.</p>';
  return events.slice().reverse().map(e=>`
    <div class="review-event">
      <strong>${esc(reviewLabel(e.review_status))}</strong>
      ${e.note?`<span>${esc(e.note)}</span>`:""}
      <small>${esc(new Date(e.timestamp).toLocaleString())}</small>
    </div>`).join("");
}

function updateReviewPanel(c){
  const panel=$("human-review-panel");
  panel.hidden=false;

  $("detail-review-badge").innerHTML=`<span class="badge ${reviewClass(c.review_status)}">${esc(reviewLabel(c.review_status))}</span>`;
  $("review-note").value="";
  $("review-history").innerHTML=reviewHistoryHtml(c);

  const buttons=$$("#review-actions [data-review-action]");
  buttons.forEach(btn=>{
    const target=btn.dataset.reviewAction;
    if(c.review_status==="not_required"){
      btn.hidden=target!=="awaiting_review";
      if(target==="awaiting_review") btn.textContent="Send to Human Review";
    } else if(c.review_status==="awaiting_review"){
      btn.hidden=target==="awaiting_review";
    } else {
      btn.hidden=target!=="awaiting_review";
      if(target==="awaiting_review") btn.textContent="Return to Review Queue";
    }
  });

  $("review-help").textContent =
    c.review_status==="not_required"
      ? "C.A.R.D. did not require human review, but a reviewer can still send the case to the queue."
      : c.review_status==="awaiting_review"
        ? "Choose the human review outcome. This does not change the underlying deterministic finding."
        : "This case has a recorded human review outcome. Return it to the queue if another review is needed.";
}

function select(c,quiet=false){
  current=c;
  $$('tr[data-id]').forEach(r=>r.classList.toggle("sel",r.dataset.id===c.case_id));
  const d=$("case-detail");d.className="";
  const agreement=c.ml?.agreement===true?"Agrees with rules":c.ml?.agreement===false?"Differs from rules":"Not comparable";
  const summary=c.summary||c.reason||"R'Solv completed the case analysis.";
  const next=c.summary_next_step||c.recommended_actions?.[0]||"No additional action was generated.";
  const transport=c.upload||{};
  d.innerHTML=`
    <div class="summary-card">
      <div class="summary-icon">R</div>
      <div class="summary-copy">
        <h3>Case summary</h3>
        <p>${esc(summary)}</p>
        ${next?`<p><strong>Suggested next step:</strong> ${esc(next)}</p>`:""}
      </div>
    </div>
    <div class="kv">
      <div><b>Case</b>${esc(c.case_id)}</div>
      <div><b>Workflow</b>${esc(c.workflow)}</div>
      <div><b>Beneficiary / Entity</b>${esc(c.client||"—")}</div>
      <div><b>Account</b>${esc(c.account_number||"—")}</div>
      <div><b>Status</b><span class="badge ${cls(c.status)}">${esc(c.status)}</span></div>
      <div><b>Human review</b><span class="badge ${reviewClass(c.review_status)}">${esc(humanLabel(c))}</span></div>
      <div><b>ML signal</b>${esc(scoreLabel(c.ml?.model_score))}</div>
      <div><b>ML vs rules</b>${esc(agreement)}</div>
    </div>
    ${transport.transport_mb?`<div class="transport-stats"><span>Source: <strong>${esc(transport.original_mb)} MB</strong></span><span>Uploaded: <strong>${esc(transport.transport_mb)} MB</strong></span><span>Mode: <strong>${esc(titleCase(transport.compression_mode||"original"))}</strong></span></div>`:""}
    ${disagreementHtml(c)}
    <div class="detail-section"><h3>Findings and next action</h3>${findingsHtml(c)}</div>
    ${c.decision_trace?.length?`<div class="detail-section"><h3>Evidence → Fact → Rule → Result</h3>${traceHtml(c.decision_trace)}</div>`:""}
    <div class="detail-section"><h3>What would clear this implemented exception?</h3>${resolutionHtml(c.resolution_preview)}</div>
    <div class="detail-section"><h3>Document facts</h3>${factsHtml(c.extraction)}</div>
    ${c.uncertainties?.length?`<div class="detail-section"><h3>Review notes</h3>${notesHtml(c.uncertainties,true)}</div>`:""}
    ${c.document_notes?.length?`<div class="detail-section"><h3>Document notes</h3>${notesHtml(c.document_notes,false)}</div>`:""}
    ${transport.download_url?`<div class="detail-section"><h3>Transport PDF</h3><p><a class="text-link" href="${esc(API_BASE+transport.download_url)}">Download uploaded transport copy →</a></p></div>`:""}
    <details><summary>Document evidence</summary>${evidenceHtml(c.evidence||[])}</details>
    <details><summary>Model note</summary><p class="muted">${esc(c.ml?.score_note||"Experimental model signal.")}</p></details>`;
  updateReviewPanel(c);
  if(!quiet){$("detail-card").scrollIntoView({behavior:reduce()?"auto":"smooth",block:"nearest"})}
}

async function submitReview(reviewStatus){
  if(!current) return;
  const note=$("review-note").value.trim();

  try{
    const data=await api(`/cases/${encodeURIComponent(current.case_id)}/review`,{
      method:"POST",
      headers:{"Content-Type":"application/json"},
      body:JSON.stringify({review_status:reviewStatus,note})
    });

    const idx=cases.findIndex(c=>c.case_id===data.case.case_id);
    if(idx>=0) cases[idx]=data.case;
    current=data.case;
    refresh();
    select(current,true);
    toast(`Human review: ${reviewLabel(reviewStatus)}`);
  }catch(error){
    toast(error.message);
  }
}

$$("[data-review-action]").forEach(btn=>{
  btn.addEventListener("click",()=>submitReview(btn.dataset.reviewAction));
});

function bars(id,map){const el=$(id),max=Math.max(1,...map.map(m=>m[1]));el.innerHTML="";map.forEach(([k,v])=>el.insertAdjacentHTML("beforeend",`<div class="bar-row"><span>${esc(k)}</span><div class="bar"><i data-w="${v/max*100}"></i></div><b>${v}</b></div>`));requestAnimationFrame(()=>requestAnimationFrame(()=>el.querySelectorAll("i").forEach(i=>i.style.width=`${i.dataset.w}%`)))}
const tally=arr=>Object.entries(arr.reduce((a,k)=>(a[k]=(a[k]||0)+1,a),{})).sort((a,b)=>b[1]-a[1]);
function renderReports(){bars("by-status",tally(cases.map(c=>c.status)));bars("by-workflow",tally(cases.map(c=>c.workflow)));const iss=tally(cases.flatMap(c=>c.issue_codes||[]));bars("by-issue",iss.length?iss:[["No issues",0]])}

function refresh(){setMetrics(false);greeting();fill($("dash-table"),attention());renderCases();if(view==="reports")renderReports();if(current)select(current,true)}
function show(v){
  if(!["dashboard","cases","reports","info","settings"].includes(v))v="dashboard";if(v===view)return;view=v;
  $$('[data-view]').forEach(el=>{const on=el.dataset.view.split(" ").includes(v);el.hidden=!on;el.classList.remove("in");if(on){void el.offsetWidth;el.classList.add("in")}});
  $$('[data-nav]').forEach(b=>b.dataset.nav===v?b.setAttribute("aria-current","page"):b.removeAttribute("aria-current"));
  if(v==="dashboard"){fill($("dash-table"),attention());setMetrics(true)}if(v==="cases")renderCases();if(v==="reports")renderReports();window.scrollTo({top:0});
}
function go(v){show(v);try{history.replaceState(null,"",`#${v}`)}catch{location.hash=v}}
$$('[data-nav]').forEach(b=>b.addEventListener("click",()=>go(b.dataset.nav)));addEventListener("hashchange",()=>show(location.hash.slice(1)));
document.addEventListener("keydown",e=>{if(e.metaKey||e.ctrlKey||e.altKey)return;if(["INPUT","TEXTAREA"].includes(e.target.tagName)){if(e.key==="Escape")e.target.blur();return}if(e.key==="/"){e.preventDefault();go("cases");$("q").focus()}else if(/^[1-5]$/.test(e.key))go(["dashboard","cases","reports","info","settings"][e.key-1])});

const mq=matchMedia("(prefers-color-scheme: dark)");
function theme(p){document.documentElement.dataset.mode=p==="system"?(mq.matches?"dark":"light"):p;$$('[data-theme-pick]').forEach(b=>b.setAttribute("aria-pressed",b.dataset.themePick===p));store.set("rsolv-theme",p)}
$$('[data-theme-pick]').forEach(b=>b.addEventListener("click",()=>theme(b.dataset.themePick)));mq.addEventListener&&mq.addEventListener("change",()=>{if(store.get("rsolv-theme")==="system")theme("system")});theme(store.get("rsolv-theme")||"light");

function validateChosenFile(){
  const file=$("pdf-file").files[0],status=$("upload-status"),button=$("analyze-btn");
  if(!file){$("file-label").textContent="Choose a beneficiary PDF";status.className="upload-status";status.textContent="";button.disabled=false;return false}
  log("File selected", {name:file.name,size:file.size,type:file.type});
  $("file-label").textContent=file.name;
  if(!file.name.toLowerCase().endsWith(".pdf")){status.className="upload-status error";status.textContent="R'Solv accepts PDF files only.";button.disabled=true;return false}
  const fileMB=mb(file.size);
  if(fileMB>MAX_UPLOAD_MB){status.className="upload-status error";status.textContent=`This PDF is ${sizeLabel(file.size)}. The current source-file limit is ${MAX_UPLOAD_MB} MB.`;button.disabled=true;return false}
  if(fileMB>COMPRESSION_TARGET_MB){status.className="upload-status warning";status.textContent=`${sizeLabel(file.size)} · R'Solv will create a small transport copy before upload.`}
  else{status.className="upload-status";status.textContent=`${sizeLabel(file.size)} · already within the transport target`}
  button.disabled=false;return true
}
$("pdf-file").addEventListener("change",validateChosenFile);

$("upload-form").addEventListener("submit",async event=>{
  event.preventDefault();
  const file=$("pdf-file").files[0],status=$("upload-status"),button=$("analyze-btn");
  if(!validateChosenFile()||!file)return;

  button.disabled=true;
  status.className="upload-status";
  status.textContent="Preparing PDF locally…";
  startProcessing(file);

  try{
    const prepared=await preparePdfForUpload(file,percent=>{
      $("processing-progress").style.width=`${Math.max(0,Math.min(55,percent))}%`;
    });

    status.textContent=`Prepared ${sizeLabel(prepared.transportBytes)} upload copy. Uploading…`;
    setProcessing(
      "Uploading PDF to R'Solv",
      56,
      `${esc(file.name)} · <strong>${esc(sizeLabel(prepared.originalBytes))}</strong> → <strong>${esc(sizeLabel(prepared.transportBytes))}</strong>`
    );

    const form=new FormData();
    form.append("file",prepared.blob,prepared.filename);
    form.append("original_filename",file.name);
    form.append("original_size_bytes",String(prepared.originalBytes));
    form.append("compression_mode",prepared.mode);
    form.append("compression_target_mb",String(COMPRESSION_TARGET_MB));

    log("Submitting prepared PDF", {
      original:file.name,
      originalMB:mb(prepared.originalBytes).toFixed(2),
      transportMB:mb(prepared.transportBytes).toFixed(2),
      mode:prepared.mode
    });

    const data=await uploadAnalyze(form,fraction=>{
      const percent=56+Math.round(fraction*24);
      setProcessing(
        `Uploading PDF · ${Math.round(fraction*100)}%`,
        percent,
        `${esc(file.name)} · <strong>${esc(sizeLabel(prepared.originalBytes))}</strong> → <strong>${esc(sizeLabel(prepared.transportBytes))}</strong>`
      );
    });

    setProcessing("Analysis complete",100,`${esc(file.name)} · case returned by C.A.R.D.`);
    const c=data.case;
    log("Analysis complete", {case_id:c.case_id,status:c.status,issues:c.issue_codes,model:c.ml,request_id:data.request_id});

    const idx=cases.findIndex(x=>x.case_id===c.case_id);
    if(idx>=0)cases[idx]=c;else cases.unshift(c);
    current=c;

    status.className="upload-status success";
    status.textContent=`Analysis complete: ${c.status}. Uploaded ${sizeLabel(prepared.transportBytes)} instead of ${sizeLabel(prepared.originalBytes)}.`;
    refresh();
    select(c);
    toast("Analysis complete");
    stopProcessing(700);

  }catch(error){
    logError("Analysis failed",error);
    status.className="upload-status error";
    status.textContent=error.message;
    stopProcessing();
  }finally{
    button.disabled=false;
  }
});

$("check-api").addEventListener("click",async()=>{const ok=await checkApi();toast(ok?"R'Solv API is ready":"R'Solv API is not ready")});
$("clear-cases").addEventListener("click",async()=>{
  if(!confirm("Clear live analyzed case history? Training data and the model will not be changed."))return;
  try{await api("/cases/clear",{method:"POST"});cases=[];current=null;$("case-detail").className="muted";$("case-detail").textContent="Analyze or select a case to see its details.";$("human-review-panel").hidden=true;refresh();toast("Live case history cleared")}catch(error){toast(error.message)}
});

$("api-location").textContent=API_BASE;
updateUploadPolicy();
log("Frontend initialized", {API_BASE, compressionTargetMB:COMPRESSION_TARGET_MB});
(async function init(){greeting();show((location.hash||"").slice(1)||"dashboard");await checkApi();await loadCases()})();
