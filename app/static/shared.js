/* Albion Ava Mapper (c) 2026 ChanaMasala. All rights reserved. Free for personal use only.
   Copying, redistributing, reusing in other projects, or using with AI to train on, copy or rebuild
   this code needs written permission from the creator (Discord: @ChanaMasala). See LICENSE. */
"use strict";
/* Albion Ava Mapper: shared helpers for the main window and the overlay (search, zone card, Discord text). */

const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: { "Content-Type": "application/json", "X-AVA-App": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.error || `Request failed (${res.status})`);
  return data;
}

let toastTimer;
function toast(msg, isError = false) {
  $(".toast")?.remove();
  const t = document.createElement("div");
  t.className = "toast" + (isError ? " error" : "");
  t.textContent = msg;
  document.body.append(t);
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => t.remove(), isError ? 6000 : 2400);
}

// ------------------------------------------------------------ constants --
const CONN = {
  royal: { label: "Royal", color: "#60a5fa" },
  black: { label: "Black zone", color: "#e7e5e4" },
  hideout: { label: "Hideout", color: "#c084fc" },
  deep: { label: "Deeper", color: "#2dd4bf" },
  roads: { label: "Roads", color: "#a8a29e" },
};
const CHESTS = [
  { key: "gold_big", label: "big gold", cls: "c-gold big" },
  { key: "gold_small", label: "small gold", cls: "c-gold" },
  { key: "blue_big", label: "big blue", cls: "c-blue big" },
  { key: "blue_small", label: "small blue", cls: "c-blue" },
  { key: "green", label: "green", cls: "c-green" },
];
const RES_ICON = { Ore: "ORE", Wood: "WOOD", Fiber: "FIBER", Hide: "HIDE", Stone: "ROCK" };

// --------------------------------------------------------------- search --
/** Each zone name split into parts, e.g. "Setent - In - Qinsum" -> ["setent","in","qinsum"] */
function prepare(z) {
  z._parts = z.name.toLowerCase().split(" - ");
  z._flat = z._parts.join("");
}
/** Score how well the query matches a zone (0 = no match). "ce av" finds "Cetitos - Avixnum". */
function score(z, q) {
  if (!q) return 1;
  const flatQ = q.replace(/[\s-]+/g, "");
  if (z._flat === flatQ) return 1000;
  const tokens = q.split(/[\s-]+/).filter(Boolean);
  let i = 0, ok = true, pts = 0;
  for (const t of tokens) {
    while (i < z._parts.length && !z._parts[i].startsWith(t)) i++;
    if (i >= z._parts.length) { ok = false; break; }
    pts += t.length / z._parts[i].length;
    i++;
  }
  if (ok) return 100 + pts * 10 - z._parts.length;
  if (z._flat.includes(flatQ)) return 10;
  return 0;
}
function highlight(z, q) {
  const tokens = q.split(/[\s-]+/).filter(Boolean);
  let i = 0;
  return z.name.split(" - ").map((part) => {
    const t = tokens[i];
    if (t && part.toLowerCase().startsWith(t)) {
      i++;
      return `<mark>${esc(part.slice(0, t.length))}</mark>${esc(part.slice(t.length))}`;
    }
    return esc(part);
  }).join(" - ");
}

// ---------------------------------------------------------------- cards --
function chestItems(z) {
  return CHESTS.filter((c) => z.chests[c.key] > 0)
    .map((c) => `<span class="item"><span class="chest ${c.cls}"></span><b>${z.chests[c.key]}</b> ${c.label}</span>`).join("");
}
/** Gathering spots grouped by type and size, big ones first: [{type, size, n}] */
function gatherGroups(z) {
  const m = new Map();
  for (const g of z.gather) {
    const k = `${g.size}|${g.type}`;
    m.set(k, { type: g.type, size: g.size, n: (m.get(k)?.n || 0) + 1 });
  }
  return [...m.values()].sort((a, b) => (a.size !== b.size ? (a.size === "big" ? -1 : 1) : a.type.localeCompare(b.type)));
}
function gatherItems(z) {
  return gatherGroups(z).map((g) => {
    const icon = RES_ICON[g.type] ? `<img class="res-ico" src="/icon/res/${RES_ICON[g.type]}.png" alt="">` : "";
    return `<span class="item">${icon}${g.n > 1 ? `<b>${g.n}</b>` : ""}${esc(g.type)} <small class="${g.size === "big" ? "size-big" : ""}">${g.size}</small></span>`;
  }).join("");
}
function dungeonItems(z) {
  const d = z.dungeons;
  return [["solo", "solo"], ["group", "group"], ["elite", "elite"]].filter(([k]) => d[k] > 0)
    .map(([k, label]) => `<span class="item"><b>${d[k]}</b> ${label}</span>`).join("");
}
function nodesHtml(z) {
  const order = ["Ore", "Wood", "Fiber", "Hide", "Rock"];
  const types = Object.keys(z.res).sort((a, b) => order.indexOf(a) - order.indexOf(b));
  if (!types.length) return '<div class="none">No resource nodes listed.</div>';
  return types.map((t) => {
    const tiers = Object.entries(z.res[t]).sort((a, b) => a[0] - b[0]).map(([tier, n]) => `T${tier} ×${n}`).join(" · ");
    return `<div><b>${esc(t === "Rock" ? "Stone" : t)}</b><span class="t">${tiers}</span></div>`;
  }).join("");
}
/** Zone card. opts.saved: star filled; opts.actions: show copy/star buttons (default true). */
function card(z, q = "", opts = {}) {
  const conn = CONN[z.conn] || CONN.roads;
  const on = !!opts.saved;
  return `<article class="zone" style="--cc:${conn.color}" data-id="${z.id}">
    <div class="zone-head">
      <span class="tier" data-t="${z.tier}" title="Tier ${z.tier}">T${z.tier}</span>
      <div class="zone-title">
        <div class="zone-name">${q ? highlight(z, q) : esc(z.name)}</div>
        <div class="zone-conn"><span class="conn-dot"></span>${esc(z.connLabel)}</div>
      </div>
      <div class="zone-actions"${opts.actions === false ? " hidden" : ""}>
        <button class="icon-btn" data-show="${z.id}" title="Show in the overlay"><svg viewBox="0 0 24 24"><rect x="2" y="15" width="20" height="6" rx="1.5"/><path d="M12 3v8"/><path d="m8 7 4 4 4-4"/></svg></button>
        <button class="icon-btn" data-copy="${z.id}" title="Copy for Discord"><svg viewBox="0 0 24 24"><rect x="9" y="9" width="12" height="12" rx="2"/><path d="M5 15H4a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1h10a1 1 0 0 1 1 1v1"/></svg></button>
        <button class="icon-btn${on ? " on" : ""}" data-save="${z.id}" title="${on ? "Remove from saved" : "Save"}"><svg viewBox="0 0 24 24"><path d="m12 3 2.8 5.7 6.2.9-4.5 4.4 1.1 6.2L12 17.3 6.4 20.2l1.1-6.2L3 9.6l6.2-.9z"/></svg></button>
      </div>
    </div>
    <div class="zone-body">
      <div class="zrow"><span>Chests</span><div class="items">${chestItems(z) || '<span class="none">None</span>'}</div></div>
      <div class="zrow"><span>Gathering</span><div class="items">${gatherItems(z) || '<span class="none">None</span>'}</div></div>
      <div class="zrow"><span>Dungeons</span><div class="items">${dungeonItems(z) || '<span class="none">None</span>'}</div></div>
    </div>
    <details class="zone-foot">
      <summary><svg viewBox="0 0 24 24"><path d="m9 6 6 6-6 6"/></svg>Resource nodes by tier <span class="spacer"></span><span class="zone-id">${esc(z.id)}</span></summary>
      <div class="nodes">${nodesHtml(z)}</div>
    </details>
  </article>`;
}

/** Plain text for Discord. */
function discordText(z) {
  const chests = CHESTS.filter((c) => z.chests[c.key] > 0).map((c) => `${z.chests[c.key]} ${c.label}`).join(", ") || "none";
  const gather = gatherGroups(z).map((g) => `${g.n > 1 ? g.n + " " : ""}${g.size} ${g.type.toLowerCase()}`).join(", ") || "none";
  const d = z.dungeons;
  const dung = [["solo", d.solo], ["group", d.group], ["elite", d.elite]].filter(([, n]) => n).map(([k, n]) => `${n} ${k}`).join(", ") || "none";
  return `**${z.name}** (T${z.tier} · ${z.connLabel})\nChests: ${chests}\nGathering: ${gather}\nDungeons: ${dung}`;
}

