/* Katbook VIP console — vanilla JS client for the REST API.
 * No build step, no dependencies. API base URL + X-API-Key are entered in the
 * top bar and persisted in localStorage (this is an internal tool).
 */
"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);
const cfg = {
  base: localStorage.getItem("kvip_base") || "http://localhost:8000",
  key: localStorage.getItem("kvip_key") || "",
};
let vPage = 1;
let jobTimer = null;

// --------------------------------------------------------------- helpers ---
function toast(msg, isErr = false) {
  const t = $("#toast");
  t.textContent = msg;
  t.className = "toast show" + (isErr ? " err" : "");
  setTimeout(() => (t.className = "toast"), 3200);
}

async function api(path, { method = "GET", body, isForm = false } = {}) {
  const headers = {};
  if (cfg.key) headers["X-API-Key"] = cfg.key;
  if (body && !isForm) headers["Content-Type"] = "application/json";
  const res = await fetch(cfg.base.replace(/\/$/, "") + path, {
    method,
    headers,
    body: isForm ? body : body ? JSON.stringify(body) : undefined,
  });
  const text = await res.text();
  let data = null;
  try { data = text ? JSON.parse(text) : null; } catch { /* non-json */ }
  if (!res.ok) {
    const msg = data?.error?.message || data?.detail || `HTTP ${res.status}`;
    const err = new Error(msg);
    err.envelope = data?.error;
    throw err;
  }
  return data;
}

const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const fmtDur = (s) => (s == null ? "—" : `${Math.floor(s / 60)}:${String(Math.floor(s % 60)).padStart(2, "0")}`);
const badge = (st) => `<span class="badge b-${st}">${st}</span>`;

// ------------------------------------------------------------- connection ---
async function checkHealth() {
  const dot = $("#health");
  try {
    const h = await api("/health");
    dot.className = "dot ok";
    dot.title = `ok · ${h.version}`;
  } catch (e) {
    dot.className = "dot bad";
    dot.title = "unreachable: " + e.message;
  }
}

$("#cfg-save").onclick = () => {
  cfg.base = $("#cfg-base").value.trim() || cfg.base;
  cfg.key = $("#cfg-key").value.trim();
  localStorage.setItem("kvip_base", cfg.base);
  localStorage.setItem("kvip_key", cfg.key);
  toast("Saved connection settings");
  checkHealth();
};

// -------------------------------------------------------------------- tabs ---
$$(".tab").forEach((t) => t.onclick = () => {
  $$(".tab").forEach((x) => x.classList.remove("active"));
  $$(".panel").forEach((x) => x.classList.remove("active"));
  t.classList.add("active");
  $("#tab-" + t.dataset.tab).classList.add("active");
});

// ------------------------------------------------------------------ videos ---
function videoFilters() {
  const p = new URLSearchParams({ page: vPage, page_size: 25 });
  const map = { subject: "#f-subject", grade_level: "#f-grade", language: "#f-language" };
  for (const [k, sel] of Object.entries(map)) {
    const v = $(sel).value.trim();
    if (v) p.set(k, v);
  }
  if ($("#f-speech").value) p.set("has_speech", $("#f-speech").value);
  if ($("#f-status").value) p.set("status", $("#f-status").value);
  return p;
}

async function loadVideos() {
  try {
    const data = await api("/api/v1/videos?" + videoFilters().toString());
    const tb = $("#v-table tbody");
    tb.innerHTML = data.items.map((v) => `
      <tr data-id="${v.video_id}">
        <td class="src" title="${esc(v.source_path)}">${esc(v.source_path.split(/[\\/]/).pop())}</td>
        <td>${badge(v.status)}</td>
        <td>${esc(v.tagging_path ?? "—")}</td>
        <td>${esc(v.language ?? "—")}</td>
        <td>${fmtDur(v.duration_sec)}</td>
        <td>${v.segment_count}</td>
        <td>${v.is_duplicate ? "↳ dup" : ""}</td>
        <td><button class="btn ghost view" data-id="${v.video_id}">View</button></td>
      </tr>`).join("") || `<tr><td colspan="8" class="muted">No videos.</td></tr>`;
    $("#v-count").textContent = `${data.total} total`;
    $("#v-page").textContent = `page ${data.page} / ${Math.max(1, Math.ceil(data.total / data.page_size))}`;
    $$("#v-table .view").forEach((b) => b.onclick = () => showVideo(b.dataset.id));
  } catch (e) { toast(e.message, true); }
}

async function showVideo(id) {
  try {
    const v = await api("/api/v1/videos/" + id);
    const r = v.rollup || {};
    $("#drawer-body").innerHTML = `
      <h2>${esc(v.source_path.split(/[\\/]/).pop())}</h2>
      <div class="kv">
        <div>status</div><div>${badge(v.status)}</div>
        <div>video_id</div><div>${esc(v.video_id)}</div>
        <div>path</div><div>${esc(v.tagging_path ?? "—")} · lang ${esc(v.language ?? "—")}</div>
        <div>duration</div><div>${fmtDur(v.duration_sec)}</div>
        <div>subject</div><div>${esc(r.subject ?? "—")} · grade ${esc(r.grade ?? "—")}</div>
        <div>primary topic</div><div>${esc(r.primary_topic ?? "—")}</div>
        <div>duplicate</div><div>${v.is_duplicate ? "yes → " + esc(v.canonical_video_id) : "no"}</div>
        ${v.error_message ? `<div>error</div><div style="color:var(--danger)">${esc(v.error_message)}</div>` : ""}
      </div>
      <button class="btn ghost" id="soft-del">Soft-delete</button>
      <h3>Segments (${v.segments.length})</h3>
      ${v.segments.map((s) => `
        <div class="seg">
          <div class="top"><b>${esc(s.topic ?? "untitled")}</b>
            <span class="muted">${fmtDur(s.start_sec)}–${fmtDur(s.end_sec)} · conf ${s.confidence ?? "—"}</span></div>
          <div class="muted">${esc(s.subject ?? "")} · ${esc(s.grade_level ?? "")} · ${esc(s.content_type ?? "")}</div>
          <div>${esc(s.summary ?? "")}</div>
          <div class="tags">${(s.tags || []).map((t) => `<span class="chip">${esc(t)}</span>`).join("")}</div>
        </div>`).join("")}`;
    $("#drawer").classList.add("open");
    $("#soft-del").onclick = async () => {
      if (!confirm("Soft-delete this video? (content is retained; status flag only)")) return;
      try { await api("/api/v1/videos/" + id, { method: "DELETE" }); toast("Soft-deleted"); $("#drawer").classList.remove("open"); loadVideos(); }
      catch (e) { toast(e.message, true); }
    };
  } catch (e) { toast(e.message, true); }
}

$("#drawer-close").onclick = () => $("#drawer").classList.remove("open");
$("#drawer").onclick = (e) => { if (e.target.id === "drawer") $("#drawer").classList.remove("open"); };
$("#v-load").onclick = () => { vPage = 1; loadVideos(); };
$("#v-prev").onclick = () => { if (vPage > 1) { vPage--; loadVideos(); } };
$("#v-next").onclick = () => { vPage++; loadVideos(); };

// ------------------------------------------------------------------ search ---
$("#s-go").onclick = async () => {
  const q = $("#s-q").value.trim();
  if (!q) return;
  try {
    const p = new URLSearchParams({ q, mode: $("#s-mode").value, limit: $("#s-limit").value });
    const data = await api("/api/v1/search?" + p.toString());
    $("#s-meta").textContent = `${data.count} result(s) · mode=${data.mode}`;
    $("#s-results").innerHTML = data.results.map((h) => `
      <div class="card hit">
        <div>
          <div class="t">${esc(h.topic ?? "untitled")}</div>
          <div class="s">${esc(h.subject ?? "")} · ${esc(h.grade_level ?? "")} · ${fmtDur(h.start_sec)}–${fmtDur(h.end_sec)}
            · <span title="${esc(h.video_id)}">video ${esc(String(h.video_id).slice(0, 8))}</span> seg ${h.seg_index}</div>
          ${h.summary ? `<div class="muted">${esc(h.summary)}</div>` : ""}
        </div>
        <div class="score">${h.score.toFixed(3)}</div>
      </div>`).join("") || `<div class="muted">No matches.</div>`;
  } catch (e) { toast(e.message, true); }
};
$("#s-q").addEventListener("keydown", (e) => { if (e.key === "Enter") $("#s-go").click(); });

// ----------------------------------------------------------------- enqueue ---
const showOut = (o) => { $("#e-out").textContent = JSON.stringify(o, null, 2); };

$("#e-register").onclick = async () => {
  try { showOut(await api("/api/v1/videos", { method: "POST", body: { source_path: $("#e-path").value.trim(), force: $("#e-force").checked } })); toast("Registered"); }
  catch (e) { toast(e.message, true); }
};
$("#e-upload").onclick = async () => {
  const f = $("#e-file").files[0];
  if (!f) return toast("Choose a file first", true);
  const fd = new FormData(); fd.append("file", f); fd.append("force", "false");
  try { showOut(await api("/api/v1/videos/upload", { method: "POST", body: fd, isForm: true })); toast("Uploaded"); }
  catch (e) { toast(e.message, true); }
};
$("#e-batch").onclick = async () => {
  const body = {};
  if ($("#e-folder").value.trim()) body.folder = $("#e-folder").value.trim();
  if ($("#e-glob").value.trim()) body.glob = $("#e-glob").value.trim();
  try { showOut(await api("/api/v1/videos/batch", { method: "POST", body })); toast("Batch enqueued"); }
  catch (e) { toast(e.message, true); }
};

// -------------------------------------------------------------------- jobs ---
async function pollJob(id) {
  try {
    const j = await api("/api/v1/jobs/" + id);
    const pct = { start: 5, ingest_audio: 12, route: 20, extract_frames: 35, visual: 55, segmentation: 70, llm: 90, store: 98, done: 100 }[j.current_stage] || (j.state === "done" ? 100 : 10);
    $("#j-status").innerHTML = `
      ${badge(j.state)} <b>${esc(j.current_stage ?? "—")}</b>
      <span class="muted">· attempt ${j.attempts} · elapsed ${j.elapsed_sec ?? "—"}s</span>
      <div class="stage-row"><div class="stagebar"><span style="width:${pct}%"></span></div><span class="muted">${pct}%</span></div>
      ${j.error ? `<div style="color:var(--danger)">${esc(j.error)}</div>` : ""}`;
    $("#j-timings").textContent = JSON.stringify(j.stage_timings || {}, null, 2);
    if (j.state === "done" || j.state === "failed") { clearInterval(jobTimer); jobTimer = null; }
  } catch (e) {
    clearInterval(jobTimer); jobTimer = null;
    $("#j-status").innerHTML = `<span style="color:var(--danger)">${esc(e.message)}</span>`;
  }
}
$("#j-watch").onclick = () => {
  const id = $("#j-id").value.trim();
  if (!id) return;
  clearInterval(jobTimer);
  pollJob(id);
  jobTimer = setInterval(() => pollJob(id), 2500);
};
$("#j-stop").onclick = () => { clearInterval(jobTimer); jobTimer = null; toast("Stopped watching"); };

// -------------------------------------------------------------------- init ---
$("#cfg-base").value = cfg.base;
$("#cfg-key").value = cfg.key;
checkHealth();
loadVideos();
setInterval(checkHealth, 20000);
