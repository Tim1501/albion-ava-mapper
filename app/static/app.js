"use strict";
/* Albion Ava Mapper: main window. Shared helpers are in shared.js. */

const PAGE = 60;

// ---------------------------------------------------------------- state --
let ZONES = [];
let META = null;
let saved = new Set();
const filters = { tier: 0, conn: "", loot: "" };
let sortBy = "loot";
const loot = (z) => { const c = z.chests; return c.gold_big * 1000 + c.gold_small * 600 + c.blue_big * 60 + c.blue_small * 30 + c.green; };
const chestCount = (z) => Object.values(z.chests).reduce((a, b) => a + b, 0);
const gatherScore = (z) => z.gather.reduce((n, g) => n + (g.size === "big" ? 2 : 1), 0);
const SORTS = {
  loot: (a, b) => loot(b) - loot(a),
  chests: (a, b) => chestCount(b) - chestCount(a) || loot(b) - loot(a),
  gather: (a, b) => gatherScore(b) - gatherScore(a),
  name: () => 0,
};
let shown = PAGE;

// --------------------------------------------------------------- render --
function renderFilters() {
  const pill = (attr, v, label, active, count) => `<button class="pill-tab${active ? " active" : ""}" data-${attr}="${v}">${label}${count !== undefined ? `<span class="count">${count}</span>` : ""}</button>`;
  $("#tierFilter").innerHTML = [0, 4, 6, 8].map((t) => pill("tier", t, t ? `T${t}` : "All tiers", filters.tier === t, t ? ZONES.filter((z) => z.tier === t).length : undefined)).join("");
  $("#connFilter").innerHTML = [["", "Any connection"], ...Object.entries(CONN).map(([k, c]) => [k, c.label])]
    .map(([k, label]) => pill("conn", k, k ? `<span class="conn-dot" style="--cc:${CONN[k].color}"></span>${label}` : label, filters.conn === k, k ? ZONES.filter((z) => z.conn === k).length : undefined)).join("");
  $("#lootFilter").innerHTML = [["", "Any chests"], ["gold", "Has gold"], ["blue", "Has blue"]]
    .map(([k, label]) => pill("loot", k, label, filters.loot === k)).join("");
}

function matches(z) {
  if (filters.tier && z.tier !== filters.tier) return false;
  if (filters.conn && z.conn !== filters.conn) return false;
  if (filters.loot === "gold" && !(z.chests.gold_big + z.chests.gold_small)) return false;
  if (filters.loot === "blue" && !(z.chests.blue_big + z.chests.blue_small)) return false;
  return true;
}

function renderResults() {
  const q = $("#search").value.trim().toLowerCase();
  let list = ZONES.filter(matches).map((z) => [z, score(z, q)]).filter(([, s]) => s > 0);
  if (q) list.sort((a, b) => b[1] - a[1] || a[0].name.localeCompare(b[0].name));
  else list.sort((a, b) => SORTS[sortBy](a[0], b[0]) || a[0].name.localeCompare(b[0].name));
  const total = list.length;
  list = list.slice(0, shown).map(([z]) => z);
  $("#resultsTitle").textContent = q ? `Results for “${$("#search").value.trim()}”` : "All zones";
  $("#resultsSub").textContent = `${total} zone${total === 1 ? "" : "s"}${filters.tier || filters.conn || filters.loot ? " match your filters" : ""}`;
  $("#results").innerHTML = list.length ? list.map((z) => card(z, q, { saved: saved.has(z.id) })).join("")
    : `<div class="empty"><b>No zone matches.</b><br>Try fewer letters, like the start of each word: “se in qi”.</div>`;
  $("#btnMore").hidden = total <= shown;
}

function renderSaved() {
  const list = ZONES.filter((z) => saved.has(z.id));
  $("#savedGrid").innerHTML = list.length ? list.map((z) => card(z, "", { saved: true })).join("")
    : '<div class="empty"><b>No saved zones yet.</b><br>Press the star on any zone card to keep it here.</div>';
  $("#navCount").textContent = saved.size || "";
}

function renderStats() {
  const sum = (k) => ZONES.reduce((n, z) => n + z.chests[k], 0);
  const date = META?.versionDate ? new Date(META.versionDate).toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" }) : "—";
  $("#heroStats").innerHTML = `
    <span class="hero-stat"><b>${ZONES.length}</b>zones</span>
    <span class="hero-stat"><b>${sum("gold_big") + sum("gold_small")}</b>gold chests</span>
    <span class="hero-stat"><b>${sum("blue_big") + sum("blue_small")}</b>blue chests</span>
    <span class="hero-stat"><b>${sum("green")}</b>green chests</span>`;
  $("#stripItems").innerHTML = `
    <span class="strip-item"><i></i>Game data <b>${date}</b></span>
    <span class="strip-item">Zones <b>${ZONES.length}</b></span>
    <span class="strip-item">Saved <b>${saved.size}</b></span>`;
}

let SETTINGS = null;
const HOTKEY_FIELDS = [  // [input id, hint id, settings field, status name]
  ["#hotkeyInput", "#hotkeyHint", "hotkey", "read", "Hover a portal on the map and press it to read the zone."],
  ["#moveHotkeyInput", "#moveHotkeyHint", "moveHotkey", "move", "Unlocks the overlay so you can drag it; press again to lock."],
];
async function renderSettings() {
  SETTINGS = await api("GET", "/api/settings");
  $("#regionSelect").value = SETTINGS.region;
  for (const [inp, hintId, field, name, help] of HOTKEY_FIELDS) {
    $(inp).value = SETTINGS[field];
    const hs = (SETTINGS.hotkeyStatus || {})[name] || {};
    const hint = $(hintId);
    hint.classList.toggle("hk-bad", hs.ok === false);
    hint.textContent = hs.ok === false ? `${hs.hotkey} couldn't be registered (another program uses it). Pick a different key.` : help;
  }
  const ov = SETTINGS.overlay;
  const btn = $("#btnOverlay");
  btn.textContent = ov.visible ? "Hide overlay" : "Show overlay";
  $("#btnLock").textContent = ov.locked ? `Unlock to move (${SETTINGS.moveHotkey})` : `Lock in place (${SETTINGS.moveHotkey})`;
  $("#btnLock").classList.toggle("warn-btn", !ov.locked);
  ["#btnOverlay", "#btnLock", "#btnReset"].forEach((b) => ($(b).disabled = !SETTINGS.overlayAvailable));
  $("#ovState").innerHTML = !SETTINGS.overlayAvailable ? '<span class="st bad">Not available</span>'
    : `<span class="st ${ov.visible ? "ok" : ""}">${ov.visible ? "Visible" : "Hidden"}</span><span class="st ${ov.locked ? "" : "warn"}">${ov.locked ? "Locked · click-through" : "Unlocked · drag it"}</span>`;
  $("#ovDot").hidden = !(ov.visible && !ov.locked);
  $("#btnTray").disabled = !SETTINGS.trayAvailable;
  document.querySelectorAll(".size-opt").forEach((o) => { o.classList.toggle("on", o.dataset.size === (ov.size || "l")); o.disabled = !SETTINGS.overlayAvailable; });
  if (!SETTINGS.overlayAvailable) $("#captureHint").textContent = "The overlay needs Microsoft Edge WebView2, which isn't available.";
}

// ---- Overlay page: live mirror of what the strip shows -------------------------
let OV = null;
let ovTimer = null;
const fmtLeft = (sec) => {
  const t = Math.max(0, Math.floor(sec)), h = Math.floor(t / 3600), m = Math.floor((t % 3600) / 60), r = t % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
};
function ovZone() { return OV && OV.id ? ZONES.find((z) => z.id === OV.id) : null; }
function renderPortalLine() {
  const el = $("#ovPortalLine");
  if (!OV || !OV.closesAt || !ovZone()) { el.hidden = true; return; }
  const left = OV.closesAt - Date.now() / 1000;
  const cls = left <= 0 ? "bad" : left < 900 ? "bad" : left < 3600 ? "warn" : "ok";
  el.hidden = false;
  el.innerHTML = `Portal ${left <= 0 ? '<b class="bad">closed</b>' : `closes in <b class="${cls}">${fmtLeft(left)}</b>`} · at ${new Date(OV.closesAt * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })}`;
}
let ovSeq = -1;
async function pollOverlay() {
  try { OV = await api("GET", "/api/overlay/state"); } catch { return; }
  renderPortalLine();
  if (OV.seq === ovSeq) return;
  ovSeq = OV.seq;
  const z = ovZone();
  const t = OV.at ? new Date(OV.at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "";
  let how = "";
  if (OV.error) how = `<span class="bad">Couldn't read the screen: ${esc(OV.error)}</span>`;
  else if (z && OV.text) how = `Read “${esc(OV.text)}” · ${Math.round(OV.score * 100)}% match · ${t}`;
  else if (z) how = `Picked here · ${t}`;
  else if (OV.at) how = `<span class="warn">No zone name found near the mouse</span> · ${t}`;
  $("#ovNow").innerHTML = (z ? card(z, "", { saved: saved.has(z.id) }) : `<div class="empty"><b>Nothing showing yet.</b><br>Hover a portal on the map and press ${esc(SETTINGS?.hotkey || "F8")}, or pick a zone on the right.</div>`)
    + (how ? `<p class="ov-how">${how}</p>` : "");
  const captured = !!OV.lines.length || (!!OV.at && !z && !OV.error) || (!!OV.text);
  $("#ovRead").hidden = !captured;
  if (captured) {
    $("#ovReadLines").innerHTML = OV.lines.length ? OV.lines.map((l) => `<div>${esc(l)}</div>`).join("") : '<div class="muted">No text found.</div>';
    $("#ovReadShot").src = `/capture/last.jpg?${OV.seq}`;
    if (!z) $("#ovRead").open = true;
  }
}
function renderOverlayPage() {
  renderSettings();
  ovSeq = -1;
  pollOverlay();
  clearInterval(ovTimer);
  ovTimer = setInterval(() => { if ($("#view-overlay").classList.contains("active")) pollOverlay(); else clearInterval(ovTimer); }, 700);
}

// pick a zone to show in the overlay
let pickSel = 0;
function pickSuggest() {
  const q = $("#ovPickSearch").value.trim().toLowerCase();
  const box = $("#ovPick");
  if (!q) { box.hidden = true; return; }
  const list = ZONES.map((z) => [z, score(z, q)]).filter(([, s]) => s > 0).sort((a, b) => b[1] - a[1]).slice(0, 6).map(([z]) => z);
  pickSel = 0;
  box.innerHTML = list.map((z, i) => `<button data-show="${z.id}" class="${i === 0 ? "sel" : ""}"><span class="t">T${z.tier}</span>${highlight(z, q)}</button>`).join("") || '<div class="muted">No zone matches.</div>';
  box.hidden = false;
}
$("#ovPickSearch").addEventListener("input", pickSuggest);
$("#ovPickSearch").addEventListener("keydown", (e) => {
  const btns = $$("#ovPick button");
  if ((e.key === "ArrowDown" || e.key === "ArrowUp") && btns.length) {
    e.preventDefault();
    pickSel = (pickSel + (e.key === "ArrowDown" ? 1 : -1) + btns.length) % btns.length;
    btns.forEach((b, i) => b.classList.toggle("sel", i === pickSel));
  } else if (e.key === "Enter" && btns[pickSel]) btns[pickSel].click();
  else if (e.key === "Escape") { e.target.value = ""; $("#ovPick").hidden = true; }
});
async function showInOverlay(id) {
  try {
    await api("POST", "/api/overlay/pick", { id });
    if (SETTINGS && !SETTINGS.overlay.visible) await api("POST", "/api/overlay/show");
    toast(`${ZONES.find((z) => z.id === id)?.name} is on the overlay`);
  } catch (err) { toast(err.message, true); }
  $("#ovPickSearch").value = "";
  $("#ovPick").hidden = true;
  if ($("#view-overlay").classList.contains("active")) { ovSeq = -1; pollOverlay(); renderSettings(); }
}

async function saveSetting(changes) {
  try { await api("PUT", "/api/settings", changes); toast("Saved"); }
  catch (err) { toast(err.message, true); }
  renderSettings();
}

// hotkey boxes: click one, then press a key combination
for (const [inp, , field] of HOTKEY_FIELDS) {
  const el = $(inp);
  el.addEventListener("focus", () => { el.classList.add("listening"); el.value = "Press a key…"; });
  el.addEventListener("blur", () => { el.classList.remove("listening"); if (SETTINGS) el.value = SETTINGS[field]; });
  el.addEventListener("keydown", (e) => {
    e.preventDefault();
    if (["Control", "Shift", "Alt", "Meta"].includes(e.key)) return;
    if (e.key === "Escape") { el.blur(); return; }
    const key = e.key.length === 1 ? e.key.toUpperCase() : e.key;
    if (!/^(F([1-9]|1[0-9]|2[0-4])|[A-Z0-9]|Insert|Home|End|PageUp|PageDown|Pause|ScrollLock|`)$/.test(key)) { toast(`${key} can't be used as a hotkey`, true); return; }
    if (/^[A-Z0-9`]$/.test(key) && !e.ctrlKey && !e.altKey) { toast("Use F1–F12, or add Ctrl/Alt for letter keys, so it doesn't block typing in game.", true); return; }
    const combo = [e.ctrlKey && "Ctrl", e.altKey && "Alt", e.shiftKey && "Shift", key].filter(Boolean).join("+");
    el.blur();
    saveSetting({ [field]: combo });
  });
}
$("#regionSelect").addEventListener("change", (e) => saveSetting({ region: e.target.value }));

async function renderData() {
  renderSettings();
  const meta = await api("GET", "/api/meta");
  const m = meta.game || {};
  const fmt = (iso) => (iso ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "—");
  $("#dataKv").innerHTML = `
    <div><span>Zones</span><b>${m.zones ?? "—"}</b></div>
    <div><span>Game data version</span><b>${fmt(m.versionDate)}</b></div>
    <div><span>Last updated</span><b>${fmt(m.built)}</b></div>`;
  if (meta.job.running) watchJob("#dataProgress");
}

// ------------------------------------------------------------ navigation --
function goto(tab) {
  $$(".nav button").forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${tab}`));
  if (tab === "saved") renderSaved();
  if (tab === "data") renderData();
  if (tab === "overlay") renderOverlayPage();
  if (tab === "zones") setTimeout(() => $("#search").focus(), 30);
  window.scrollTo(0, 0);
}

// ------------------------------------------------------------------ jobs --
let jobTimer = null;
function watchJob(el) {
  const box = $(el);
  box.hidden = false;
  box.classList.remove("error");
  $$("#btnUpdate, #btnSetup").forEach((b) => (b.disabled = true));
  clearInterval(jobTimer);
  const tick = async () => {
    let j;
    try { j = await api("GET", "/api/job"); } catch { return; }
    box.querySelector("i").style.width = `${Math.round((j.progress || 0) * 100)}%`;
    box.querySelector("span").textContent = j.error ? `Failed: ${j.error}` : j.text;
    if (!j.running) {
      clearInterval(jobTimer);
      $$("#btnUpdate, #btnSetup").forEach((b) => (b.disabled = false));
      if (j.error) { box.classList.add("error"); toast(j.error, true); return; }
      await loadZones();
      if (el === "#setupProgress") start();
      else renderData();
      toast(j.text);
    }
  };
  tick();
  jobTimer = setInterval(tick, 600);
}

// ------------------------------------------------------------------ boot --
async function loadZones() {
  const [zones, meta] = await Promise.all([fetch("/game/zones.json").then((r) => r.json()), fetch("/game/meta.json").then((r) => r.json())]);
  zones.forEach(prepare);
  ZONES = zones;
  META = meta;
}

function start() {
  document.querySelector(".nav").hidden = false;
  renderFilters();
  renderStats();
  renderResults();
  renderSaved();
  renderSettings().catch(() => {});
  goto("zones");
}

function showVersion(meta) {
  $("#appVer").textContent = `v${meta.version}`;
  const u = meta.update, b = $("#btnUpdateApp");
  b.hidden = !u;
  if (u) b.textContent = `Update to v${u.version}`;
}

async function checkHotkeys() {
  let st;
  try { st = await api("GET", "/api/overlay/state"); } catch { return; }
  const bad = Object.values(st.hotkeys || {}).filter((h) => h.ok === false).map((h) => h.hotkey);
  $("#hkWarn").hidden = !bad.length;
  if (!bad.length) return;
  $("#hkWarnTitle").textContent = `${bad.join(" and ")} ${bad.length > 1 ? "aren't" : "isn't"} working right now`;
  $("#hkWarnText").textContent = (st.staleCopy
    ? "An older copy of Albion Ava Mapper still seems to be running and holding the keys. Quit it from its tray icon (or end \"Albion Ava Mapper\" / \"pythonw\" in Task Manager), then start the app again. "
    : "Another program is using the key. Close it, or pick a different key on the Overlay page. ")
    + "If it still doesn't work, right-click Albion Ava Mapper and choose Run as administrator. The app keeps retrying every few seconds.";
}
setInterval(checkHotkeys, 5000);

async function boot() {
  checkHotkeys();
  const meta = await api("GET", "/api/meta");
  showVersion(meta);
  setTimeout(() => api("GET", "/api/meta").then(showVersion).catch(() => {}), 12000);  // the update check runs in the background
  if (!meta.game) {
    document.querySelector(".nav").hidden = true;
    $$(".view").forEach((v) => v.classList.toggle("active", v.id === "view-setup"));
    if (meta.job.running) watchJob("#setupProgress");
    return;
  }
  saved = new Set(await api("GET", "/api/saved"));
  await loadZones();
  start();
}

// ---------------------------------------------------------------- events --
$("#search").addEventListener("input", () => { shown = PAGE; renderResults(); });
$("#sortSelect").addEventListener("change", (e) => {
  sortBy = e.target.value;
  try { localStorage.setItem("sortBy", sortBy); } catch { /* not saved: fine */ }
  shown = PAGE;
  renderResults();
});
try { const v = localStorage.getItem("sortBy"); if (v && SORTS[v]) { sortBy = v; $("#sortSelect").value = v; } } catch { /* first run */ }

document.addEventListener("click", async (e) => {
  const t = e.target.closest("button, [data-goto]");
  if (!t) return;
  if (t.dataset.goto) { e.preventDefault(); goto(t.dataset.goto); return; }
  if (t.dataset.tab) { goto(t.dataset.tab); return; }
  if (t.dataset.tier !== undefined) { filters.tier = Number(t.dataset.tier); shown = PAGE; renderFilters(); renderResults(); return; }
  if (t.dataset.conn !== undefined) { filters.conn = t.dataset.conn; shown = PAGE; renderFilters(); renderResults(); return; }
  if (t.dataset.loot !== undefined) { filters.loot = t.dataset.loot; shown = PAGE; renderFilters(); renderResults(); return; }
  if (t.dataset.copy) {
    const z = ZONES.find((x) => x.id === t.dataset.copy);
    try { await navigator.clipboard.writeText(discordText(z)); toast(`Copied ${z.name}. Paste it in Discord.`); }
    catch (err) { toast(`Couldn't copy: ${err.message}`, true); }
    return;
  }
  if (t.dataset.show) { showInOverlay(t.dataset.show); return; }
  if (t.dataset.size && t.classList.contains("size-opt")) {
    try {
      await api("POST", "/api/overlay/size", { size: t.dataset.size });
      await renderSettings();
      toast(`Overlay size: ${{ l: "Big", m: "Medium", s: "Small" }[t.dataset.size]}`);
    } catch (err) { toast(err.message, true); }
    return;
  }
  if (t.dataset.save) {
    const id = t.dataset.save;
    saved.has(id) ? saved.delete(id) : saved.add(id);
    try { saved = new Set(await api("PUT", "/api/saved", { ids: [...saved] })); } catch (err) { toast(err.message, true); }
    $$(`[data-save="${id}"]`).forEach((b) => { b.classList.toggle("on", saved.has(id)); b.title = saved.has(id) ? "Remove from saved" : "Save"; });
    if ($("#view-saved").classList.contains("active")) renderSaved();
    $("#navCount").textContent = saved.size || "";
    renderStats();
    return;
  }
  switch (t.id) {
    case "btnMore": shown += PAGE; renderResults(); break;
    case "btnUpdate":
    case "btnSetup":
      try { await api("POST", "/api/update-data"); watchJob(t.id === "btnSetup" ? "#setupProgress" : "#dataProgress"); }
      catch (err) { toast(err.message, true); }
      break;
    case "btnOverlay":
      try { await api("POST", SETTINGS?.overlay.visible ? "/api/overlay/hide" : "/api/overlay/show"); } catch (err) { toast(err.message, true); }
      renderSettings();
      break;
    case "btnLock":
      try { await api("POST", "/api/overlay/lock", { locked: !SETTINGS.overlay.locked }); } catch (err) { toast(err.message, true); }
      await renderSettings();
      toast(SETTINGS.overlay.locked ? "Overlay locked: clicks go through it" : "Overlay unlocked: drag it where you want");
      break;
    case "btnReset":
      try { await api("POST", "/api/overlay/reset"); toast("Overlay moved back to the middle of the bottom bar"); } catch (err) { toast(err.message, true); }
      break;
    case "btnOvCopy": {
      const z = ovZone();
      if (!z) { toast("Nothing on the overlay to copy yet", true); break; }
      const extra = OV.closesAt && OV.closesAt > Date.now() / 1000 ? `\nPortal closes <t:${OV.closesAt}:R>` : "";
      try { await navigator.clipboard.writeText(discordText(z) + extra); toast(`Copied ${z.name}. Paste it in Discord.`); }
      catch (err) { toast(`Couldn't copy: ${err.message}`, true); }
      break;
    }
    case "btnOvClear":
      await api("POST", "/api/overlay/clear").catch(() => {});
      ovSeq = -1; pollOverlay();
      break;
    case "btnTray":
      try {
        await api("POST", "/api/minimize");
        document.body.innerHTML = '<div style="display:grid;place-items:center;height:100vh;color:#a8a29e;font:15px Inter;text-align:center">Albion Ava Mapper is running in the tray.<br>Click its icon in the “show hidden icons” area to open it again.</div>';
      } catch (err) { toast(err.message, true); }
      break;
    case "btnTestCapture": {
      await api("POST", "/api/capture", { delay: 3 });
      let n = 3;
      const hint = $("#captureHint");
      const tick = () => { hint.textContent = n > 0 ? `Move your mouse over a portal tooltip… ${n}` : "Read. See “Showing now”."; n--; if (n >= -1) setTimeout(tick, 1000); };
      tick();
      break;
    }
    case "btnUpdateApp":
      api("POST", "/api/open-release").then(() => toast("The download page opened in your browser. Unzip it over this folder; your data stays.")).catch((err) => toast(err.message, true));
      break;
    case "btnDonate":
    case "btnDonateFoot":
      api("POST", "/api/donate").then(() => toast("Thank you! The PayPal page opened in your browser.")).catch((err) => toast(err.message, true));
      break;
    case "btnDiscord":
      try { await navigator.clipboard.writeText("ChanaMasala"); toast("Copied ChanaMasala. Paste it in Discord to report a bug."); }
      catch (err) { toast(`Couldn't copy: ${err.message}`, true); }
      break;
    case "btnOpenData": api("POST", "/api/open-folder").catch((err) => toast(err.message, true)); break;
    case "btnQuit":
      api("POST", "/api/shutdown").catch(() => {});
      document.body.innerHTML = '<div style="display:grid;place-items:center;height:100vh;color:#a8a29e;font:15px Inter">Albion Ava Mapper has stopped. You can close this window.</div>';
      break;
  }
});

document.addEventListener("keydown", (e) => {
  if (e.key === "/" && document.activeElement !== $("#search") && $("#view-zones").classList.contains("active")) {
    e.preventDefault();
    $("#search").focus();
    $("#search").select();
  }
  if (e.key === "Escape" && document.activeElement === $("#search")) { $("#search").value = ""; shown = PAGE; renderResults(); }
});

// clock in the strip
function tickClock() {
  const d = new Date();
  $("#clockDay").textContent = d.toLocaleDateString(undefined, { weekday: "short" });
  $("#clockTime").textContent = d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false });
}
setInterval(tickClock, 1000);
tickClock();

// keep-alive so the server knows the window is open, and stops after it closes
const ping = () => fetch("/api/ping", { cache: "no-store" }).catch(() => {});
ping();
setInterval(ping, 5000);
window.addEventListener("pagehide", () => {
  fetch("/api/bye", { method: "POST", keepalive: true, headers: { "X-AVA-App": "1" } }).catch(() => {});
});

boot().catch((e) => toast(e.message, true));
