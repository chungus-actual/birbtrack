// The day as a 24-hour dial: midnight at the top, one ring per species (first heard innermost),
// one hairline tick per call, daylight shaded from sunrise to sunset, and the sun (or moon) on
// the rim at the hero's moment: now on today, the latest call on a past day. Today's calls from
// the last few minutes burn brighter behind the hand and cool as they age.

import { s, secs } from "./util.js";

const C = 500;
const R_IN = 196;
const R_MAX = 420;
const R_BACK = 444;
const R_LABEL = 486;
const R_ORB = R_BACK + 30;
const DAY = 86400;
const GLOW = 15 * 60;   // how long a call stays warm

const angle = (t) => (t / DAY) * Math.PI * 2 - Math.PI / 2;
const at = (t, r) => [C + r * Math.cos(angle(t)), C + r * Math.sin(angle(t))];
const f = (n) => n.toFixed(1);

function sector(t0, t1, r0, r1) {
  if (t1 < t0) t1 += DAY;
  const large = t1 - t0 > DAY / 2 ? 1 : 0;
  const [x0, y0] = at(t0, r1), [x1, y1] = at(t1, r1), [x2, y2] = at(t1, r0), [x3, y3] = at(t0, r0);
  return `M${f(x0)} ${f(y0)} A${r1} ${r1} 0 ${large} 1 ${f(x1)} ${f(y1)} L${f(x2)} ${f(y2)} ` +
    `A${r0} ${r0} 0 ${large} 0 ${f(x3)} ${f(y3)} Z`;
}

function radial(t, r0, r1, cls) {
  const [x0, y0] = at(t, r0), [x1, y1] = at(t, r1);
  return s("line", { x1: f(x0), y1: f(y0), x2: f(x1), y2: f(y1), class: cls });
}

export function laneClass(i) {
  return `k${i % 12}`;
}

// keyTime(): seconds after midnight, yard time, for the sun marker (and the hand when live)
export function dial(day, { onHover, keyTime } = {}) {
  const n = day.species.length;
  const lane = n ? Math.min(26, (R_MAX - R_IN) / n) : (R_MAX - R_IN) / 12;
  const ring = (i) => [R_IN + i * lane, R_IN + (i + 1) * lane];
  const label = () => (day.total
    ? `${day.species_count} species and ${day.total} calls, placed by the time they were heard around a 24-hour clock`
    : "No calls yet on this day");
  const svg = s("svg", { viewBox: "-100 -100 1200 1200", class: "dial-svg", role: "img", "aria-label": label() });

  svg.append(s("defs", {},
    s("radialGradient", { id: "dial-sun-halo" },
      s("stop", { offset: "0", "stop-color": "#ffd27a", "stop-opacity": "0.55" }),
      s("stop", { offset: "1", "stop-color": "#ffd27a", "stop-opacity": "0" })),
    s("radialGradient", { id: "dial-moon-halo" },
      s("stop", { offset: "0", "stop-color": "#dfe6f2", "stop-opacity": "0.35" }),
      s("stop", { offset: "1", "stop-color": "#dfe6f2", "stop-opacity": "0" }))));

  const orb = s("g", { class: "dial-orb" });
  svg.append(orb);

  svg.append(s("circle", { cx: C, cy: C, r: R_BACK, class: "dial-night" }));
  if (day.sunrise && day.sunset) {
    svg.append(s("path", { d: sector(secs(day.sunrise), secs(day.sunset), R_IN - 16, R_BACK), class: "dial-day" }));
  }
  const hourWedge = s("path", { d: "", class: "dial-hour" });
  svg.append(hourWedge);

  const guides = s("g", { class: `dial-guides${n ? "" : " empty"}` });
  const rings = n || 12;
  for (let i = 0; i <= rings; i++) {
    if (!n || i % 4 === 0 || i === rings) guides.append(s("circle", { cx: C, cy: C, r: R_IN + i * lane }));
  }
  svg.append(guides);

  const hours = s("g", { class: "dial-hours" });
  for (let hr = 0; hr < 24; hr++) {
    const major = hr % 6 === 0;
    hours.append(radial(hr * 3600, R_BACK + 6, R_BACK + (major ? 28 : 14), major ? "major" : "minor"));
  }
  for (const [text, hr, anchor, base] of [["Midnight", 0, "middle", "auto"], ["6 AM", 6, "start", "middle"],
    ["Noon", 12, "middle", "hanging"], ["6 PM", 18, "end", "middle"]]) {
    const [x, y] = at(hr * 3600, R_LABEL);
    hours.append(s("text", { x: f(x), y: f(y), "text-anchor": anchor, "dominant-baseline": base, class: "dial-label" }, text));
  }
  for (const key of ["sunrise", "sunset"]) {
    if (day[key]) hours.append(radial(secs(day[key]), R_MAX + 4, R_BACK, "dial-sun"));
  }
  svg.append(hours);

  const lanes = s("g", { class: "dial-lanes" });
  const groups = day.species.map((sp, i) => {
    const g = s("g", { class: `lane ${laneClass(i)}` });
    lanes.append(g);
    return g;
  });
  const byId = new Map();
  const tick = (t, i, id) => {
    if (byId.has(id) || !groups[i]) return;
    const [r0, r1] = ring(i);
    const pad = lane * 0.18;
    groups[i].append(radial(t, r0 + pad, r1 - pad, "tick"));
    byId.set(id, [t, (r0 + r1) / 2, i]);
  };
  for (const [t, i, id] of day.points) tick(t, i, id);
  svg.append(lanes);

  const fresh = s("g", { class: "dial-fresh", "aria-hidden": "true" });
  svg.append(fresh);
  let focused = null;
  const warm = () => {
    const now = day.is_today && keyTime ? keyTime() : null;
    if (now == null) return;
    const kids = [];
    for (const [t, , i] of byId.values()) {
      const age = Math.max(0, now - t);
      if (age > GLOW) continue;
      const [r0, r1] = ring(i);
      const pad = lane * 0.18;
      kids.push(s("g", { class: `warm ${laneClass(i)}${i === focused ? " on" : ""}`, "data-lane": i,
        style: { "--heat": (1 - age / GLOW).toFixed(3) } },
      radial(t, r0, r1, "halo"), radial(t, r0 + pad, r1 - pad, "core")));
    }
    fresh.replaceChildren(...kids);
  };
  warm();

  const hand = day.is_today ? s("g", { class: "dial-now" }) : null;
  if (hand) svg.append(hand);

  const place = () => {
    const t = keyTime ? keyTime() : null;
    if (t == null || !day.sunrise || !day.sunset) {
      orb.replaceChildren();
      return;
    }
    const lit = t >= secs(day.sunrise) && t <= secs(day.sunset);
    const [x, y] = at(t, R_ORB);
    orb.replaceChildren(
      s("circle", { cx: f(x), cy: f(y), r: 70, fill: `url(#${lit ? "dial-sun-halo" : "dial-moon-halo"})` }),
      s("circle", { cx: f(x), cy: f(y), r: 11, class: lit ? "orb sun" : "orb moon" }));
    orb.dataset.x = String((x + 100) / 1200);
    orb.dataset.y = String((y + 100) / 1200);
    if (hand) hand.replaceChildren(radial(t, R_IN - 2, R_ORB - 14, ""));
  };
  place();
  const timer = day.is_today ? setInterval(() => { place(); warm(); }, 15000) : null;

  const focus = (i) => {
    focused = i;
    svg.classList.toggle("focus", i != null);
    groups.forEach((g, j) => g.classList.toggle("on", j === i));
    for (const w of fresh.children) w.classList.toggle("on", Number(w.dataset.lane) === i);
  };

  if (onHover && n) {
    const point = svg.createSVGPoint();
    let lastHour = null, lastHit = "";
    const report = (hit) => {
      const key = hit ? `${hit.i}:${hit.hour}` : "";
      if (key !== lastHit) onHover(hit);
      lastHit = key;
    };
    const clear = () => {
      focus(null);
      hourWedge.setAttribute("d", "");
      lastHour = null;
      report(null);
    };
    svg.addEventListener("pointermove", (e) => {
      point.x = e.clientX;
      point.y = e.clientY;
      const m = svg.getScreenCTM();
      if (!m) return;
      const p = point.matrixTransform(m.inverse());
      const dx = p.x - C, dy = p.y - C;
      const r = Math.hypot(dx, dy);
      const i = Math.floor((r - R_IN) / lane);
      if (r < R_IN || i < 0 || i >= n) {
        clear();
        return;
      }
      let t = ((Math.atan2(dy, dx) + Math.PI / 2) / (Math.PI * 2)) * DAY;
      if (t < 0) t += DAY;
      const hour = Math.floor(t / 3600);
      if (hour !== lastHour) {
        hourWedge.setAttribute("d", sector(hour * 3600, (hour + 1) * 3600, R_IN, R_MAX));
        lastHour = hour;
      }
      focus(i);
      report({ i, hour });
    });
    svg.addEventListener("pointerleave", clear);
  }

  const pulse = (id) => {
    const hit = byId.get(id);
    if (!hit) return;
    const [t, r, i] = hit;
    const [x, y] = at(t, r);
    const ripple = s("circle", { cx: f(x), cy: f(y), r: 26, class: `ripple ${laneClass(i)}` });
    svg.append(ripple);
    setTimeout(() => ripple.remove(), 2200);
  };

  // calls heard after the dial was drawn
  const add = (points) => {
    for (const [t, i, id] of points) tick(t, i, id);
    svg.setAttribute("aria-label", label());
    warm();
  };

  // a call lands: a ripple where it fell and the hand flashes its lane's color
  let flashTimer = 0;
  const land = (id) => {
    pulse(id);
    const hit = byId.get(id);
    if (!hit || !hand) return;
    hand.setAttribute("class", `dial-now flash ${laneClass(hit[2])}`);
    clearTimeout(flashTimer);
    flashTimer = setTimeout(() => hand.setAttribute("class", "dial-now"), 1400);
  };

  // a species' first call of the day: its ring draws itself around the dial from that call
  const grow = (i, { lifer = false } = {}) => {
    if (!groups[i]) return;
    const [r0, r1] = ring(i);
    let start = DAY;
    for (const [t, , j] of byId.values()) if (j === i) start = Math.min(start, t);
    const c = s("circle", { cx: C, cy: C, r: f((r0 + r1) / 2), pathLength: 1, "stroke-width": f(lane * (lifer ? 0.9 : 0.6)),
      class: `grow ${lifer ? "lifer" : laneClass(i)}`, transform: `rotate(${f((start / DAY) * 360 - 90)} ${C} ${C})` });
    fresh.after(c);
    setTimeout(() => c.remove(), 3400);
  };

  return {
    el: svg, orb, focus, pulse, add, land, grow, refresh: place,
    dispose: () => { clearInterval(timer); clearTimeout(flashTimer); },
  };
}
