// Where a bird is likely, month by month: BirdNET's geomodel over the station's region as a soft
// heatmap clipped to land, with the yard marked. The month strip scrubs the year; months the bird was
// actually heard in the yard carry a dot.

import { h, s } from "./util.js";

const MONTHS = ["January", "February", "March", "April", "May", "June", "July", "August", "September",
  "October", "November", "December"];
let basemap = null;

const json = (url) => fetch(url).then((r) => (r.ok || r.status === 202 ? r.json() : Promise.reject(r.status)));

function decode(b64) {
  const bin = atob(b64);
  const out = new Uint8Array(bin.length);
  for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
  return out;
}

export function rangeMap(sp, tz) {
  const root = h("figure", { class: "range" });
  const slot = h("div", { class: "range-map" });
  const strip = h("div", { class: "range-months", role: "group", "aria-label": "Month" });
  root.append(slot, strip);

  (async () => {
    let data;
    try {
      [basemap, data] = await Promise.all([basemap || json("/api/map"), json(`/api/species/${sp.slug}/range`)]);
    } catch {
      root.remove();
      return;
    }
    if (!data.months) {
      slot.append(h("p", { class: "empty" }, "Mapping the range…"));
      return;
    }
    const months = data.months.map(decode);
    const uid = `r${Math.random().toString(36).slice(2, 8)}`;
    const svg = s("svg", { viewBox: `0 0 ${basemap.w} ${basemap.h}`, class: "range-svg", role: "img",
      "aria-label": `Where the ${sp.common} is likely to be, by month, across ${basemap.name}` });
    svg.append(s("defs", {},
      s("clipPath", { id: `${uid}-land` }, s("path", { d: basemap.land })),
      s("filter", { id: `${uid}-soft`, x: "-10%", y: "-10%", width: "120%", height: "120%" },
        s("feGaussianBlur", { stdDeviation: (basemap.spacing * 0.44).toFixed(1) }))));
    svg.append(s("path", { d: basemap.land, class: "range-land" }));
    const heat = s("g", { class: "range-heat", "clip-path": `url(#${uid}-land)` });
    const blobs = s("g", { filter: `url(#${uid}-soft)` });
    // one soft blob per sample point, sized to overlap its neighbours
    const r = (basemap.spacing * 0.74).toFixed(1);
    const dots = basemap.points.map(([x, y]) => {
      const c = s("circle", { cx: x, cy: y, r });
      blobs.append(c);
      return c;
    });
    heat.append(blobs);
    svg.append(heat,
      s("path", { d: basemap.lakes, class: "range-lakes" }),
      s("path", { d: basemap.borders, class: "range-borders" }),
      s("path", { d: basemap.land, class: "range-coast" }),
      s("circle", { cx: basemap.home[0], cy: basemap.home[1], r: 9, class: "range-home" }));
    slot.append(svg);

    const show = (m) => {
      const v = months[m];
      dots.forEach((c, i) => {
        const a = v[i] / 255;
        c.setAttribute("opacity", a < 0.03 ? "0" : Math.min(1, a ** 0.75 * 1.15).toFixed(3));
      });
      strip.querySelectorAll("button.mo").forEach((b, i) => b.setAttribute("aria-pressed", String(i === m)));
    };

    const heard = new Set(sp.heard_months || []);
    MONTHS.forEach((name, m) => {
      const b = h("button", { type: "button", "aria-label": name, "aria-pressed": "false",
        class: heard.has(m) ? "mo heard" : "mo" }, name[0]);
      b.addEventListener("click", () => { stopTour(); show(m); });
      b.addEventListener("pointerenter", () => { if (!touring) show(m); });
      strip.append(b);
    });
    let touring = null;
    const stopTour = () => {
      clearInterval(touring);
      touring = null;
      tour.setAttribute("aria-pressed", "false");
    };
    const tour = h("button", { type: "button", class: "range-tour", "aria-label": "Play the year", "aria-pressed": "false" },
      s("svg", { viewBox: "0 0 24 24", "aria-hidden": "true" }, s("path", { d: "M7.5 4.5 L20 12 L7.5 19.5 Z" })));
    tour.addEventListener("click", () => {
      if (touring) return stopTour();
      let m = 0;
      show(m);
      tour.setAttribute("aria-pressed", "true");
      touring = setInterval(() => {
        m += 1;
        if (m > 11) return stopTour();
        show(m);
      }, 650);
    });
    strip.prepend(tour);

    const now = Number(new Intl.DateTimeFormat("en-US", { timeZone: tz || undefined, month: "numeric" })
      .format(new Date())) - 1;
    show(now);
  })();
  return root;
}
