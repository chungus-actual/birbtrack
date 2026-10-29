// DOM building without innerHTML, formatting, and the API client.

export const SVGNS = "http://www.w3.org/2000/svg";

function setAttrs(el, attrs) {
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v == null || v === false) continue;
    if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
    else if (k === "style") for (const [p, val] of Object.entries(v)) el.style.setProperty(p, val);
    else el.setAttribute(k, v === true ? "" : String(v));
  }
}

function append(el, kids) {
  for (const k of kids.flat(Infinity)) {
    if (k == null || k === false) continue;
    el.append(k instanceof Node ? k : document.createTextNode(String(k)));
  }
}

export function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  setAttrs(el, attrs);
  append(el, kids);
  return el;
}

export function s(tag, attrs = {}, ...kids) {
  const el = document.createElementNS(SVGNS, tag);
  setAttrs(el, attrs);
  append(el, kids);
  return el;
}

export const secs = (hms) => {
  const [a, b, c] = hms.split(":").map(Number);
  return a * 3600 + b * 60 + (c || 0);
};

export function fmtTime(hms) {
  const [H, M] = hms.split(":").map(Number);
  return `${H % 12 || 12}:${String(M).padStart(2, "0")} ${H < 12 ? "AM" : "PM"}`;
}

export function fmtHour(hr) {
  if (hr === 0) return "midnight";
  if (hr === 12) return "noon";
  return `${hr % 12} ${hr < 12 ? "AM" : "PM"}`;
}

export const parseDay = (d) => {
  const [y, m, dd] = d.split("-").map(Number);
  return new Date(y, m - 1, dd);
};

export const fmtDay = (d, opts = { month: "short", day: "numeric", year: "numeric" }) =>
  parseDay(d).toLocaleDateString("en-US", opts);
export const longDay = (d) => fmtDay(d, { weekday: "long", month: "long", day: "numeric" });
export const fullDay = (d) => fmtDay(d, { weekday: "long", month: "long", day: "numeric", year: "numeric" });
export const num = (n) => Number(n).toLocaleString("en-US");
export const pct = (c) => `${Math.round(c * 100)}%`;
export const plural = (n, one, many = `${one}s`) => `${num(n)} ${n === 1 ? one : many}`;

export function ago(seconds) {
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
  const d = Math.floor(seconds / 86400);
  return d === 1 ? "yesterday" : `${d} days ago`;
}

export function isoWeek(day) {
  const d = parseDay(day);
  const t = new Date(Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()));
  const dow = t.getUTCDay() || 7;
  t.setUTCDate(t.getUTCDate() + 4 - dow);
  const y = t.getUTCFullYear();
  const wk = Math.ceil(((t - Date.UTC(y, 0, 1)) / 86400000 + 1) / 7);
  return `${y}-W${String(wk).padStart(2, "0")}`;
}

export class NotFound extends Error {}

export async function get(path) {
  const r = await fetch(path, { headers: { accept: "application/json" } });
  if (r.status === 404) throw new NotFound(path);
  if (!r.ok) throw new Error(`HTTP ${r.status}`);
  return r.json();
}

export const photo = (slug, size = 320) => `/media/bird/${slug}-${size}.jpg`;

export function names(sp, tag = "span") {
  return h(tag, { class: "names" },
    h("span", { class: "common" }, sp.common),
    h("span", { class: "sci" }, sp.sci));
}

export function chevron(dir) {
  return s("svg", { class: "chev", viewBox: "0 0 16 16", "aria-hidden": "true" },
    s("path", { d: dir === "left" ? "M10 3 L5 8 L10 13" : "M6 3 L11 8 L6 13" }));
}
