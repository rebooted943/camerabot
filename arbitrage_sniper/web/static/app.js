"use strict";

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => Array.from(document.querySelectorAll(sel));

const state = {
  search: "",
  target: "",
  platform: "",
  in_range: "",
  alerted: false,
  sort: "last_seen",
};

// --------------------------------------------------------------------------- //
// helpers
// --------------------------------------------------------------------------- //
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (_) {}
    throw new Error(detail);
  }
  return res.status === 204 ? null : res.json();
}

function toast(msg, kind = "ok") {
  const el = $("#toast");
  el.textContent = msg;
  el.className = `toast ${kind}`;
  setTimeout(() => el.classList.add("hidden"), 2600);
}

function money(v, currency = "EUR") {
  if (v === null || v === undefined) return "—";
  const sym = { EUR: "€", RON: "lei", USD: "$", GBP: "£" }[currency] || currency;
  return `${Math.round(v).toLocaleString()} ${sym}`;
}

function esc(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

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

// --------------------------------------------------------------------------- //
// stats + filters
// --------------------------------------------------------------------------- //
async function loadStats() {
  try {
    const s = await api("/api/stats");
    $("#stat-targets").textContent = s.total_targets ?? "0";
    $("#stat-seen").textContent = s.total_seen ?? "0";
    $("#stat-inrange").textContent = s.total_in_range ?? "0";
    $("#stat-alerts").textContent = s.total_alerted ?? "0";
  } catch (e) { /* ignore */ }
}

async function loadFilters() {
  try {
    const f = await api("/api/filters");
    const tSel = $("#filter-target");
    const pSel = $("#filter-platform");
    const curT = tSel.value, curP = pSel.value;
    tSel.innerHTML = '<option value="">All targets</option>' +
      f.targets.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
    pSel.innerHTML = '<option value="">All platforms</option>' +
      f.platforms.map((p) => `<option value="${esc(p)}">${esc(p)}</option>`).join("");
    tSel.value = curT; pSel.value = curP;
  } catch (e) { /* ignore */ }
}

// --------------------------------------------------------------------------- //
// targets manager
// --------------------------------------------------------------------------- //
async function loadTargets() {
  const wrap = $("#targets-list");
  try {
    const { targets } = await api("/api/targets");
    if (!targets.length) {
      wrap.innerHTML = '<p class="hint">No targets yet. Add one above.</p>';
      return;
    }
    wrap.innerHTML = targets.map(renderTarget).join("");
    bindTargetActions();
  } catch (e) {
    wrap.innerHTML = `<p class="hint">Failed to load targets: ${esc(e.message)}</p>`;
  }
}

function renderTarget(t) {
  const meta = [];
  if (t.mpb_floor) meta.push(`MPB floor ${money(t.mpb_floor)}`);
  if (t.channel) meta.push(`→ ${esc(t.channel)}`);
  const metaLine = meta.length ? `<div class="target-meta">${meta.join(" · ")}</div>` : "";
  return `
    <div class="target-card" data-id="${esc(t.id)}">
      <div class="target-top">
        <div>
          <div class="target-label">${esc(t.label)}</div>
          ${metaLine}
        </div>
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

function bindTargetActions() {
  $$(".target-card").forEach((card) => {
    const id = card.dataset.id;
    card.querySelector('[data-action="delete"]').addEventListener("click", async () => {
      if (!confirm(`Remove target "${id}"?`)) return;
      try {
        await api(`/api/targets/${encodeURIComponent(id)}`, { method: "DELETE" });
        toast("Target removed");
        await Promise.all([loadTargets(), loadStats()]);
      } catch (e) { toast(e.message, "err"); }
    });
    card.querySelector('[data-action="save"]').addEventListener("click", async () => {
      const minV = card.querySelector(".t-min").value;
      const maxV = card.querySelector(".t-max").value;
      const body = {
        clear_price_min: minV === "",
        clear_price_max: maxV === "",
        price_min: minV === "" ? null : Number(minV),
        price_max: maxV === "" ? null : Number(maxV),
      };
      try {
        await api(`/api/targets/${encodeURIComponent(id)}`, {
          method: "PATCH", body: JSON.stringify(body),
        });
        toast("Price range saved");
      } catch (e) { toast(e.message, "err"); }
    });
  });
}

$("#add-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const query = $("#add-query").value.trim();
  if (!query) return;
  const minV = $("#add-min").value;
  const maxV = $("#add-max").value;
  const body = {
    query,
    price_min: minV === "" ? null : Number(minV),
    price_max: maxV === "" ? null : Number(maxV),
  };
  try {
    const r = await api("/api/targets", { method: "POST", body: JSON.stringify(body) });
    toast(r.message || "Target added");
    $("#add-query").value = ""; $("#add-min").value = ""; $("#add-max").value = "";
    await Promise.all([loadTargets(), loadStats(), loadFilters()]);
  } catch (e) { toast(e.message, "err"); }
});

// --------------------------------------------------------------------------- //
// items viewer
// --------------------------------------------------------------------------- //
async function loadItems() {
  const grid = $("#items");
  const params = new URLSearchParams();
  if (state.search) params.set("q", state.search);
  if (state.target) params.set("target", state.target);
  if (state.platform) params.set("platform", state.platform);
  if (state.in_range !== "") params.set("in_range", state.in_range);
  if (state.alerted) params.set("alerted", "true");
  params.set("sort", state.sort);
  params.set("limit", "200");

  try {
    const data = await api(`/api/items?${params.toString()}`);
    $("#items-meta").textContent = `${data.total} item(s) match${data.total === 1 ? "es" : ""} your filters`;
    if (!data.items.length) {
      grid.innerHTML = "";
      $("#empty").classList.remove("hidden");
      return;
    }
    $("#empty").classList.add("hidden");
    grid.innerHTML = data.items.map(renderItem).join("");
  } catch (e) {
    grid.innerHTML = `<p class="hint">Failed to load items: ${esc(e.message)}</p>`;
  }
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
  const gain = it.safe_gain != null
    ? `<div class="item-bench">risk-zero gain <b>${money(it.safe_gain)}</b></div>` : "";

  return `
    <article class="item-card">
      ${thumb}
      <div class="item-body">
        <div class="badges">${badges.join("")}</div>
        <div class="item-title">${esc(it.title || "(untitled)")}</div>
        <div class="item-price">${money(it.price, it.currency || "EUR")}</div>
        ${benchLine}
        ${gain}
      </div>
      <div class="item-foot">
        <span class="item-target">${esc(it.target_label || "")} · ${timeAgo(it.last_seen)}</span>
        <a class="item-link" href="${esc(it.link)}" target="_blank" rel="noopener">Open ↗</a>
      </div>
    </article>`;
}

// --------------------------------------------------------------------------- //
// wiring
// --------------------------------------------------------------------------- //
let searchTimer;
$("#search").addEventListener("input", (e) => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => { state.search = e.target.value.trim(); loadItems(); }, 250);
});
$("#filter-target").addEventListener("change", (e) => { state.target = e.target.value; loadItems(); });
$("#filter-platform").addEventListener("change", (e) => { state.platform = e.target.value; loadItems(); });
$("#filter-range").addEventListener("change", (e) => { state.in_range = e.target.value; loadItems(); });
$("#filter-alerted").addEventListener("change", (e) => { state.alerted = e.target.checked; loadItems(); });
$("#sort").addEventListener("change", (e) => { state.sort = e.target.value; loadItems(); });
$("#refresh").addEventListener("click", () => refreshAll());

async function refreshAll() {
  await Promise.all([loadStats(), loadFilters(), loadTargets(), loadItems()]);
}

refreshAll();
setInterval(() => { loadStats(); loadItems(); }, 30000);
