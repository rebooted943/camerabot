"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  search: "", target: "", platform: "", in_range: "", alerted: false, sort: "last_seen",
};

// "live"  = FastAPI backend available (full features)
// "static"= GitHub Pages read-only snapshot (data.json)
let MODE = "live";
let SNAPSHOT = null; // static payload

// --------------------------------------------------------------------------- //
// helpers
// --------------------------------------------------------------------------- //
async function api(path, options = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...options });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

function toast(msg, kind = "ok") {
  const el = $("#toast");
  el.textContent = msg; el.className = `toast ${kind}`;
  setTimeout(() => el.classList.add("hidden"), 2600);
}

function money(v, currency = "EUR") {
  if (v === null || v === undefined) return "—";
  const sym = { EUR: "€", RON: "lei", USD: "$", GBP: "£" }[currency] || currency;
  return `${Math.round(v).toLocaleString()} ${sym}`;
}

function esc(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }

function timeAgo(unixSec) {
  if (!unixSec) return "";
  const diff = Date.now() / 1000 - unixSec;
  const mins = Math.floor(diff / 60);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m ago`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h ago`;
  return `${Math.floor(hrs / 24)}d ago`;
}

function applyStats(s) {
  $("#stat-targets").textContent = s.total_targets ?? "0";
  $("#stat-seen").textContent = s.total_seen ?? "0";
  $("#stat-inrange").textContent = s.total_in_range ?? "0";
  $("#stat-alerts").textContent = s.total_alerted ?? "0";
}

// --------------------------------------------------------------------------- //
// rendering
// --------------------------------------------------------------------------- //
function renderTarget(t, readonly) {
  const meta = [];
  if (t.mpb_floor) meta.push(`MPB floor ${money(t.mpb_floor)}`);
  if (t.channel) meta.push(`→ ${esc(t.channel)}`);
  if (readonly && t.price_label) meta.push(esc(t.price_label));
  const metaLine = meta.length ? `<div class="target-meta">${meta.join(" · ")}</div>` : "";
  if (readonly) {
    return `<div class="target-card"><div class="target-label">${esc(t.label)}</div>${metaLine}</div>`;
  }
  return `
    <div class="target-card" data-id="${esc(t.id)}">
      <div class="target-top">
        <div><div class="target-label">${esc(t.label)}</div>${metaLine}</div>
        <button class="btn danger" data-action="delete" title="Remove">✕</button>
      </div>
      <div class="target-range-form">
        <input type="number" min="0" step="1" class="t-min" placeholder="min" value="${t.price_min ?? ""}" />
        <span class="dash">–</span>
        <input type="number" min="0" step="1" class="t-max" placeholder="max" value="${t.price_max ?? ""}" />
        <button class="btn" data-action="save">Save</button>
      </div>
    </div>`;
}

function renderItem(it) {
  const thumb = it.image_url
    ? `<img class="item-thumb" src="${esc(it.image_url)}" loading="lazy" alt="" onerror="this.classList.add('placeholder');this.removeAttribute('src');this.textContent='📷'" />`
    : `<div class="item-thumb placeholder">📷</div>`;
  const badges = [];
  if (it.alerted) badges.push('<span class="badge alert">alerted</span>');
  if (it.in_range === 1) badges.push('<span class="badge in">in range</span>');
  else if (it.in_range === 0) badges.push('<span class="badge out">out of range</span>');
  badges.push(`<span class="badge plat">${esc(it.platform)}</span>`);
  const bench = [];
  if (it.mpb_price) bench.push(`MPB <b>${money(it.mpb_price)}</b>`);
  if (it.ebay_price) bench.push(`eBay <b>${money(it.ebay_price)}</b>`);
  if (it.f64_price) bench.push(`F64 <b>${money(it.f64_price)}</b>`);
  const benchLine = bench.length ? `<div class="item-bench">${bench.join(" · ")}</div>` : "";
  const gain = it.safe_gain != null ? `<div class="item-bench">risk-zero gain <b>${money(it.safe_gain)}</b></div>` : "";
  return `
    <article class="item-card">
      ${thumb}
      <div class="item-body">
        <div class="badges">${badges.join("")}</div>
        <div class="item-title">${esc(it.title || "(untitled)")}</div>
        <div class="item-price">${money(it.price, it.currency || "EUR")}</div>
        ${benchLine}${gain}
      </div>
      <div class="item-foot">
        <span class="item-target">${esc(it.target_label || "")} · ${timeAgo(it.last_seen)}</span>
        <a class="item-link" href="${esc(it.link)}" target="_blank" rel="noopener">Open ↗</a>
      </div>
    </article>`;
}

function renderItems(items, total) {
  const grid = $("#items");
  $("#items-meta").textContent = `${total} item(s) match your filters`;
  if (!items.length) { grid.innerHTML = ""; $("#empty").classList.remove("hidden"); return; }
  $("#empty").classList.add("hidden");
  grid.innerHTML = items.map(renderItem).join("");
}

// --------------------------------------------------------------------------- //
// LIVE mode data loaders
// --------------------------------------------------------------------------- //
async function loadStats() { try { applyStats(await api("/api/stats")); } catch (_) {} }

async function loadFilters() {
  try {
    const f = await api("/api/filters");
    fillFilterSelects(f.targets, f.platforms);
  } catch (_) {}
}

function fillFilterSelects(targets, platforms) {
  const tSel = $("#filter-target"), pSel = $("#filter-platform");
  const curT = tSel.value, curP = pSel.value;
  tSel.innerHTML = '<option value="">All targets</option>' + targets.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
  pSel.innerHTML = '<option value="">All platforms</option>' + platforms.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
  tSel.value = curT; pSel.value = curP;
}

async function loadTargets() {
  const wrap = $("#targets-list");
  try {
    const { targets } = await api("/api/targets");
    if (!targets.length) { wrap.innerHTML = '<p class="hint">No targets yet. Add one above.</p>'; return; }
    wrap.innerHTML = targets.map((t) => renderTarget(t, false)).join("");
    bindTargetActions();
  } catch (e) { wrap.innerHTML = `<p class="hint">Failed to load targets: ${esc(e.message)}</p>`; }
}

async function loadProviders() {
  const wrap = $("#providers-list");
  try {
    const { providers } = await api("/api/providers");
    wrap.innerHTML = providers.map((p) => `
      <div class="provider-row ${p.available ? "" : "disabled"}">
        <label>
          <input type="checkbox" data-name="${esc(p.name)}" ${p.enabled ? "checked" : ""} ${p.available ? "" : "disabled"} />
          ${esc(p.label)}
        </label>
        ${p.available ? "" : '<span class="provider-tag">needs setup</span>'}
      </div>`).join("");
    $$('#providers-list input[type="checkbox"]').forEach((cb) => cb.addEventListener("change", saveProviders));
  } catch (e) { wrap.innerHTML = `<p class="hint">${esc(e.message)}</p>`; }
}

async function saveProviders() {
  const all = $$('#providers-list input[type="checkbox"]');
  const enabled = all.filter((cb) => cb.checked).map((cb) => cb.dataset.name);
  // Empty selection => backend treats as "all"; guard against unchecking everything.
  const body = { enabled: enabled.length ? enabled : all.map((cb) => cb.dataset.name) };
  try { await api("/api/providers", { method: "POST", body: JSON.stringify(body) }); toast("Sources updated"); }
  catch (e) { toast(e.message, "err"); }
}

async function loadItems() {
  const params = new URLSearchParams();
  if (state.search) params.set("q", state.search);
  if (state.target) params.set("target", state.target);
  if (state.platform) params.set("platform", state.platform);
  if (state.in_range !== "") params.set("in_range", state.in_range);
  if (state.alerted) params.set("alerted", "true");
  params.set("sort", state.sort); params.set("limit", "200");
  try { const data = await api(`/api/items?${params.toString()}`); renderItems(data.items, data.total); }
  catch (e) { $("#items").innerHTML = `<p class="hint">Failed: ${esc(e.message)}</p>`; }
}

// --------------------------------------------------------------------------- //
// target CRUD (live only)
// --------------------------------------------------------------------------- //
function bindTargetActions() {
  $$(".target-card[data-id]").forEach((card) => {
    const id = card.dataset.id;
    card.querySelector('[data-action="delete"]').addEventListener("click", async () => {
      if (!confirm(`Remove target "${id}"?`)) return;
      try { await api(`/api/targets/${encodeURIComponent(id)}`, { method: "DELETE" }); toast("Target removed"); await Promise.all([loadTargets(), loadStats()]); }
      catch (e) { toast(e.message, "err"); }
    });
    card.querySelector('[data-action="save"]').addEventListener("click", async () => {
      const minV = card.querySelector(".t-min").value, maxV = card.querySelector(".t-max").value;
      const body = { clear_price_min: minV === "", clear_price_max: maxV === "", price_min: minV === "" ? null : Number(minV), price_max: maxV === "" ? null : Number(maxV) };
      try { await api(`/api/targets/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) }); toast("Price range saved"); }
      catch (e) { toast(e.message, "err"); }
    });
  });
}

// --------------------------------------------------------------------------- //
// Scan now (live only)
// --------------------------------------------------------------------------- //
let scanPoll = null;

async function startScan() {
  const mode = ($('input[name="scan-mode"]:checked') || {}).value || "all";
  const query = $("#scan-query").value.trim();
  if (mode === "query" && !query) { toast("Enter a query to scan", "err"); return; }
  const providers = $$('#providers-list input[type="checkbox"]').filter((c) => c.checked && !c.disabled).map((c) => c.dataset.name);
  try {
    await api("/api/scan", { method: "POST", body: JSON.stringify({ mode, query: query || null, providers: providers.length ? providers : null }) });
    $("#scan-now").disabled = true;
    pollScan();
  } catch (e) { toast(e.message, "err"); }
}

function renderScanStatus(s) {
  const el = $("#scan-status");
  el.classList.remove("hidden");
  if (s.state === "running") {
    el.className = "scan-status running";
    el.innerHTML = `<span class="spinner"></span>${esc(s.message || "running…")}`;
  } else if (s.state === "done") {
    el.className = "scan-status done";
    el.textContent = `✓ Done — scanned ${s.scanned}, new ${s.new}, alerts ${s.alerts}`;
  } else if (s.state === "error") {
    el.className = "scan-status error";
    el.textContent = `✕ ${s.message || "failed"}${s.error ? " — " + s.error : ""}`;
  } else { el.classList.add("hidden"); }
}

async function pollScan() {
  clearInterval(scanPoll);
  const tick = async () => {
    try {
      const s = await api("/api/scan");
      renderScanStatus(s);
      if (s.state !== "running") {
        clearInterval(scanPoll);
        $("#scan-now").disabled = false;
        await Promise.all([loadStats(), loadFilters(), loadItems()]);
      }
    } catch (_) { clearInterval(scanPoll); $("#scan-now").disabled = false; }
  };
  await tick();
  scanPoll = setInterval(tick, 2500);
}

// --------------------------------------------------------------------------- //
// STATIC mode (GitHub Pages)
// --------------------------------------------------------------------------- //
function enterStaticMode(data) {
  MODE = "static"; SNAPSHOT = data;
  const when = data.generated_at ? new Date(data.generated_at * 1000).toLocaleString() : "unknown";
  const banner = $("#banner");
  banner.classList.remove("hidden");
  banner.textContent = `Read-only online view · published from the last scan (${when}). Run the local dashboard to edit targets or scan on demand.`;
  // hide write controls
  $("#scan-section").classList.add("hidden");
  $("#add-form").classList.add("hidden");
  applyStats(data.stats || {});
  const tw = $("#targets-list");
  tw.innerHTML = (data.targets || []).map((t) => renderTarget(t, true)).join("") || '<p class="hint">No targets.</p>';
  fillFilterSelects((data.filters || {}).targets || [], (data.filters || {}).platforms || []);
  renderStaticItems();
}

function renderStaticItems() {
  let items = (SNAPSHOT.items || []).slice();
  if (state.search) items = items.filter((i) => (i.title || "").toLowerCase().includes(state.search.toLowerCase()));
  if (state.target) items = items.filter((i) => i.target_label === state.target);
  if (state.platform) items = items.filter((i) => i.platform === state.platform);
  if (state.in_range !== "") items = items.filter((i) => String(i.in_range) === (state.in_range === "true" ? "1" : "0"));
  if (state.alerted) items = items.filter((i) => i.alerted === 1);
  const cmp = { last_seen: (a, b) => b.last_seen - a.last_seen, price: (a, b) => a.price - b.price, safe_gain: (a, b) => (b.safe_gain || 0) - (a.safe_gain || 0) };
  items.sort(cmp[state.sort] || cmp.last_seen);
  renderItems(items, items.length);
}

// --------------------------------------------------------------------------- //
// wiring
// --------------------------------------------------------------------------- //
function onFilterChange() { MODE === "static" ? renderStaticItems() : loadItems(); }

let searchTimer;
$("#search").addEventListener("input", (e) => { clearTimeout(searchTimer); searchTimer = setTimeout(() => { state.search = e.target.value.trim(); onFilterChange(); }, 250); });
$("#filter-target").addEventListener("change", (e) => { state.target = e.target.value; onFilterChange(); });
$("#filter-platform").addEventListener("change", (e) => { state.platform = e.target.value; onFilterChange(); });
$("#filter-range").addEventListener("change", (e) => { state.in_range = e.target.value; onFilterChange(); });
$("#filter-alerted").addEventListener("change", (e) => { state.alerted = e.target.checked; onFilterChange(); });
$("#sort").addEventListener("change", (e) => { state.sort = e.target.value; onFilterChange(); });
$("#refresh").addEventListener("click", () => MODE === "static" ? location.reload() : refreshLive());

$$('input[name="scan-mode"]').forEach((r) => r.addEventListener("change", () => {
  $("#scan-query").classList.toggle("hidden", ($('input[name="scan-mode"]:checked') || {}).value !== "query");
}));
$("#scan-now").addEventListener("click", startScan);

$("#add-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const query = $("#add-query").value.trim();
  if (!query) return;
  const minV = $("#add-min").value, maxV = $("#add-max").value;
  const body = { query, price_min: minV === "" ? null : Number(minV), price_max: maxV === "" ? null : Number(maxV) };
  try {
    const r = await api("/api/targets", { method: "POST", body: JSON.stringify(body) });
    toast(r.message || "Target added");
    $("#add-query").value = ""; $("#add-min").value = ""; $("#add-max").value = "";
    await Promise.all([loadTargets(), loadStats(), loadFilters()]);
  } catch (e) { toast(e.message, "err"); }
});

async function refreshLive() {
  await Promise.all([loadStats(), loadFilters(), loadTargets(), loadProviders(), loadItems()]);
}

async function boot() {
  try {
    await api("/api/stats");
    MODE = "live";
    await refreshLive();
    // resume any scan already in progress
    try { const s = await api("/api/scan"); if (s.state === "running") { $("#scan-now").disabled = true; pollScan(); } } catch (_) {}
    setInterval(() => { if (MODE === "live") { loadStats(); loadItems(); } }, 30000);
  } catch (_) {
    // No backend -> try the static snapshot (GitHub Pages).
    try {
      const res = await fetch("data.json", { cache: "no-store" });
      if (!res.ok) throw new Error("no data");
      enterStaticMode(await res.json());
    } catch (e) {
      $("#items").innerHTML = `<p class="hint">No backend and no data.json found.</p>`;
    }
  }
}

boot();
