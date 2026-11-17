"use strict";
/* Albion Ava Mapper overlay strip: display only (Gem Notifier style). Controls are in the main app and tray. */

let ZONES = [];
let current = null;        // zone shown
let closesAt = null;       // unix seconds when the portal closes (read from the tooltip)
let closesTotal = null;    // seconds left when it was read, for the progress bar
let lastSeq = -1;
let locked = null;
let keys = { read: "F8", move: "F9" };

const fmtClock = (iso) => (iso ? new Date(iso).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit", hour12: false }) : "");
function fmtLeft(sec) {
  const s = Math.max(0, Math.floor(sec)), h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), r = s % 60;
  return h ? `${h}:${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}` : `${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
}

function renderZone() {
  const tier = $("#tier");
  if (!current) {
    tier.textContent = "–";
    tier.removeAttribute("data-t");
    $("#zName").textContent = "No zone yet";
    $("#zName").classList.add("muted");
    $("#zSub").innerHTML = `Hover a portal, press <b>${esc(keys.read)}</b>`;
    $("#pChests").innerHTML = $("#pGather").innerHTML = $("#pDung").innerHTML = '<span class="none">–</span>';
    return;
  }
  const z = current;
  const conn = CONN[z.conn] || CONN.roads;
  tier.textContent = `T${z.tier}`;
  tier.dataset.t = z.tier;
  $("#zName").textContent = z.name;
  $("#zName").classList.remove("muted");
  $("#zSub").innerHTML = `<span class="dot" style="--cc:${conn.color}"></span><b>${esc(z.connLabel)}</b><span class="zid">${esc(z.id)}</span>`;

  const c = z.chests;
  const chest = (n, cls, label, big) => (n ? `<span class="pill ${cls}"><span class="chest${big ? " big" : ""}"></span><b>${n}</b>${label}</span>` : "");
  $("#pChests").innerHTML = [
    chest(c.gold_big, "gold", "big gold", true), chest(c.gold_small, "gold", "small gold"),
    chest(c.blue_big, "blue", "big blue", true), chest(c.blue_small, "blue", "small blue"),
    chest(c.green, "green", "green"),
  ].join("") || '<span class="none">No chests</span>';
  $("#pGather").innerHTML = gatherGroups(z).map((g) => {
    const icon = RES_ICON[g.type] ? `<img src="/icon/res/${RES_ICON[g.type]}.png" alt="">` : "";
    return `<span class="pill res${g.size === "big" ? " big" : ""}">${icon}${g.n > 1 ? `<b>${g.n}</b>` : ""}${esc(g.type)} <small>${g.size}</small></span>`;
  }).join("") || '<span class="none">No gathering</span>';
  const d = z.dungeons;
  $("#pDung").innerHTML = [["solo", d.solo], ["group", d.group], ["elite", d.elite]].filter(([, n]) => n)
    .map(([k, n]) => `<span class="pill dng"><b>${n}</b>${k}</span>`).join("") || '<span class="none">No dungeons</span>';
}

function renderRead(st) {
  const el = $("#zRead");
  const t = fmtClock(st.at);
  if (!st.at) el.innerHTML = "";
  else if (st.error) el.innerHTML = `<span class="err">ERROR</span> · see the app · ${t}`;
  else if (st.id && !st.text) el.innerHTML = `<span class="ok">PICKED</span> in the app · ${t}`;
  else if (st.id) el.innerHTML = `<span class="ok">READ</span> · ${Math.round(st.score * 100)}% match · ${t}`;
  else el.innerHTML = `<span class="warn">NO ZONE</span> near the mouse · ${t}`;
}

function renderPortal() {
  const box = $("#portal");
  if (!closesAt || !current) {
    box.removeAttribute("data-s");
    box.classList.remove("flash");
    $("#pStat").textContent = "No timer";
    $("#pTime").textContent = "--:--";
    $("#pBar").style.width = "0";
    $("#pAt").textContent = "read from the portal tooltip";
    return;
  }
  const left = closesAt - Date.now() / 1000;
  const s = left <= 0 ? "closed" : left < 900 ? "last" : left < 3600 ? "soon" : "ok";
  box.dataset.s = s;
  box.classList.toggle("flash", s === "last" && Math.floor(Date.now() / 1000) % 2 === 0);
  $("#pStat").textContent = { ok: "Open", soon: "Closing soon", last: "Last minutes", closed: "Closed" }[s];
  $("#pTime").textContent = left <= 0 ? "CLOSED" : fmtLeft(left);
  $("#pBar").style.width = `${Math.max(0, Math.min(100, (left / (closesTotal || left || 1)) * 100))}%`;
  $("#pAt").textContent = `closes at ${new Date(closesAt * 1000).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })}`;
}
setInterval(renderPortal, 1000);

function applyLock(isLocked) {
  locked = isLocked;
  const strip = $("#strip");
  strip.classList.toggle("unlocked", !locked);
  strip.classList.toggle("pywebview-drag-region", !locked);  // pywebview drags any element with this class
}

async function poll() {
  let st;
  try { st = await (await fetch("/api/overlay/state", { cache: "no-store" })).json(); } catch { return; }
  const hk = st.hotkeys || {};
  const k = { read: hk.read?.hotkey || keys.read, move: hk.move?.hotkey || keys.move };
  if (k.read !== keys.read || k.move !== keys.move) { keys = k; if (!current) renderZone(); }
  $("#hintKey").textContent = keys.move;
  if (st.locked !== locked) applyLock(st.locked);
  if (st.seq === lastSeq) return;
  lastSeq = st.seq;
  current = st.id ? ZONES.find((z) => z.id === st.id) || null : (st.error || st.at ? current : null);
  if (st.id) {
    closesAt = st.closesAt || null;
    closesTotal = closesAt ? closesAt - Date.now() / 1000 : null;
  } else if (!st.at) {
    closesAt = null;  // cleared from the app
  }
  renderZone();
  renderRead(st);
  renderPortal();
}

(async function boot() {
  try {
    ZONES = await (await fetch("/game/zones.json")).json();
  } catch {
    $("#zName").textContent = "No zone data yet";
    $("#zSub").textContent = "Open Albion Ava Mapper and download the zone data.";
    return;
  }
  renderZone();
  renderPortal();
  poll();
  setInterval(poll, 300);
})();
