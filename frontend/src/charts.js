// Small time charts. Every one of them reads left to right as midnight to midnight,
// or January to December, so the time axis means the same thing everywhere on the site.

import { fmtHour, h, s, secs } from "./util.js";

const f = (n) => n.toFixed(1);

// one tick per call across a day, for a roll-call row; daylight shaded like the dial
export function strip(times, cls, sunrise, sunset) {
  const W = 288, H = 22;
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: `strip ${cls}`, "aria-hidden": "true",
    preserveAspectRatio: "none" });
  if (sunrise && sunset) {
    const x0 = (secs(sunrise) / 86400) * W, x1 = (secs(sunset) / 86400) * W;
    svg.append(s("rect", { x: f(x0), y: 0, width: f(x1 - x0), height: H, class: "day" }));
  }
  for (let hr = 6; hr < 24; hr += 6) svg.append(s("line", { x1: hr * 12, x2: hr * 12, y1: 0, y2: H, class: "grid" }));
  for (const t of times) {
    const x = f((t / 86400) * W);
    svg.append(s("line", { x1: x, x2: x, y1: 4, y2: H - 4, class: "tick" }));
  }
  return svg;
}

// calls per hour, 24 bars
export function hourBars(hourly, { label } = {}) {
  const W = 480, H = 150, base = 124, gap = 4, bw = W / 24 - gap;
  const top = Math.max(1, ...hourly);
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "bars", role: "img", "aria-label": label || "Calls per hour" });
  hourly.forEach((n, hr) => {
    const bh = n ? Math.max(3, (n / top) * (base - 8)) : 0;
    const x = hr * (bw + gap) + gap / 2;
    svg.append(s("rect", { x: f(x), y: f(base - bh), width: f(bw), height: f(bh), rx: 2.5, class: n === top ? "bar peak" : "bar" },
      s("title", {}, `${fmtHour(hr)}: ${n.toLocaleString("en-US")}`)));
  });
  svg.append(s("line", { x1: 0, x2: W, y1: base + 0.5, y2: base + 0.5, class: "axis" }));
  for (const hr of [0, 6, 12, 18]) {
    svg.append(s("text", { x: f(hr * (bw + gap) + gap / 2), y: H - 6, class: "axis-label" },
      hr === 0 ? "12 AM" : hr === 12 ? "Noon" : fmtHour(hr)));
  }
  return svg;
}

// detections per day, labelled bars (the week page)
export function dayBars(daily) {
  const W = 480, H = 170, base = 132, gap = 14, bw = (W - gap * 6) / 7;
  const top = Math.max(1, ...daily.map((d) => d.count));
  const svg = s("svg", { viewBox: `0 0 ${W} ${H}`, class: "bars days", role: "img", "aria-label": "Calls per day" });
  daily.forEach((d, i) => {
    const bh = d.count ? Math.max(3, (d.count / top) * (base - 24)) : 0;
    const x = i * (bw + gap);
    const name = new Date(`${d.day}T12:00:00`).toLocaleDateString("en-US", { weekday: "short" });
    svg.append(s("rect", { x: f(x), y: f(base - bh), width: f(bw), height: f(bh), rx: 4,
      class: d.count === top ? "bar peak" : "bar" }));
    svg.append(s("text", { x: f(x + bw / 2), y: f(base - bh - 7), "text-anchor": "middle", class: "bar-value" },
      d.count.toLocaleString("en-US")));
    svg.append(s("text", { x: f(x + bw / 2), y: H - 12, "text-anchor": "middle", class: "axis-label" }, name));
  });
  svg.append(s("line", { x1: 0, x2: W, y1: base + 0.5, y2: base + 0.5, class: "axis" }));
  return svg;
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const MONTH_START = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];

// weeks (or months, on phones) of the year across, hours of the day down
export function yearMatrix(year, { months = false } = {}) {
  let cols = 53, cell = 9, gap = 1.5, left = 34, topPad = 18;
  let data = year;
  if (months) {
    cols = 12; cell = 18; gap = 3; left = 40; topPad = 24;
    data = {};
    for (const [key, n] of Object.entries(year)) {
      const [w, hr] = key.split(":").map(Number);
      const m = Math.max(0, MONTH_START.findLastIndex((d) => d <= w * 7 + 3));
      data[`${m}:${hr}`] = (data[`${m}:${hr}`] || 0) + n;
    }
  }
  const W = left + cols * (cell + gap), H = topPad + 24 * (cell + gap) + 4;
  const peak = Math.max(1, ...Object.values(data));
  const svg = s("svg", { viewBox: `0 0 ${f(W)} ${f(H)}`, class: `matrix ${months ? "months" : "weeks"}`, role: "img",
    "aria-label": "When this bird is heard, by time of year and hour of the day" });
  MONTHS.forEach((m, i) => {
    const x = months ? left + i * (cell + gap) + cell / 2 : left + (MONTH_START[i] / 7) * (cell + gap);
    svg.append(s("text", { x: f(x), y: months ? 14 : 11, class: "axis-label",
      "text-anchor": months ? "middle" : "start" }, months ? m[0] : m));
  });
  for (const [hr, text] of [[0, "12a"], [6, "6a"], [12, "12p"], [18, "6p"]]) {
    svg.append(s("text", { x: 0, y: f(topPad + hr * (cell + gap) + cell - 1), class: "axis-label" }, text));
  }
  for (let c = 0; c < cols; c++) {
    for (let hr = 0; hr < 24; hr++) {
      const n = data[`${c}:${hr}`] || 0;
      const x = left + c * (cell + gap), y = topPad + hr * (cell + gap);
      const level = n ? Math.min(5, 1 + Math.floor((Math.log(n) / Math.log(peak + 1)) * 5)) : 0;
      svg.append(s("rect", { x: f(x), y: f(y), width: cell, height: cell, rx: months ? 2.5 : 1.5, class: `m${level}` }));
    }
  }
  return svg;
}

export function meter(value, top) {
  return h("span", { class: "meter", "aria-hidden": "true" },
    h("span", { style: { "--w": `${Math.max(2, (value / Math.max(1, top)) * 100)}%` } }));
}
