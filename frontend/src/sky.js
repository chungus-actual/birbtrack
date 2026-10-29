// The sky over the yard at a given moment, as three gradient stops (top, middle, horizon),
// keyed to that day's real sunrise and sunset.

import { secs } from "./util.js";

const NIGHT = ["#05070f", "#0b1230", "#18214d"];
const KEYS = [
  [-80, NIGHT],
  [-45, ["#0a0f2a", "#1f2658", "#433578"]],
  [-18, ["#1b2759", "#6a4a8a", "#e58467"]],
  [0, ["#36508a", "#c4849c", "#f7b267"]],
  [80, ["#6b9bd0", "#a9c7e6", "#f2dcb6"]],
  [null, ["#3f86d0", "#86b6e6", "#d5e7f3"]], // midday
  [-80, ["#5687c3", "#a0bddc", "#f1d2a2"]], // relative to sunset from here on
  [0, ["#3a4884", "#b4627c", "#f39a52"]],
  [22, ["#1b2150", "#5a3d78", "#b0546a"]],
  [70, NIGHT],
];

const hex = (c) => [1, 3, 5].map((i) => parseInt(c.slice(i, i + 2), 16));
const mix = (a, b, t) => {
  const A = hex(a), B = hex(b);
  return `#${A.map((v, i) => Math.round(v + (B[i] - v) * t).toString(16).padStart(2, "0")).join("")}`;
};
const lum = (c) => {
  const [r, g, b] = hex(c).map((v) => {
    v /= 255;
    return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
};

export function skyAt(t, sunrise, sunset) {
  if (!sunrise || !sunset) return { stops: NIGHT, bright: false };
  const rise = secs(sunrise), set = secs(sunset);
  const noon = (rise + set) / 2;
  const times = KEYS.map(([m], i) => (m === null ? noon : (i < 5 ? rise : set) + m * 60));
  let stops = NIGHT;
  if (t > times[0] && t < times[times.length - 1]) {
    for (let i = 0; i < times.length - 1; i++) {
      if (t >= times[i] && t <= times[i + 1]) {
        const k = (t - times[i]) / (times[i + 1] - times[i]);
        stops = KEYS[i][1].map((c, j) => mix(c, KEYS[i + 1][1][j], k));
        break;
      }
    }
  }
  return { stops, bright: lum(stops[1]) > 0.28 };
}

export function yardNow(tz) {
  return secs(new Intl.DateTimeFormat("en-GB", { timeZone: tz, hour: "2-digit", minute: "2-digit",
    second: "2-digit", hourCycle: "h23" }).format(new Date()));
}

export function paint(el, sky) {
  el.style.setProperty("--sky-top", sky.stops[0]);
  el.style.setProperty("--sky-mid", sky.stops[1]);
  el.style.setProperty("--sky-low", sky.stops[2]);
  el.classList.toggle("bright", sky.bright);
  el.classList.toggle("dark", !sky.bright);
}

// put the sky's glow where the sun (or moon) sits on the dial rim
export function glowFrom(hero, dialBox, orb) {
  if (!orb?.dataset.x) return;
  const hr = hero.getBoundingClientRect(), dr = dialBox.getBoundingClientRect();
  if (!hr.width || !dr.width) return;
  const x = dr.left + Number(orb.dataset.x) * dr.width - hr.left;
  const y = dr.top + Number(orb.dataset.y) * dr.height - hr.top;
  hero.style.setProperty("--glow-x", `${((x / hr.width) * 100).toFixed(1)}%`);
  hero.style.setProperty("--glow-y", `${((y / hr.height) * 100).toFixed(1)}%`);
}
