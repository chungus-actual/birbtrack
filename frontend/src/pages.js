// The pages. Each takes its route params and returns { node, title, dispose? }.
// Copy is data, never narration: the charts and layout have to explain themselves.
// Layout vocabulary: .hero (full-bleed inside the frame) and .cell / .cells (framed rows).

import { dayBars, hourBars, meter, strip, yearMatrix } from "./charts.js";
import { dial, laneClass } from "./dial.js";
import { player, playButton } from "./player.js";
import { glowFrom, paint, skyAt, yardNow } from "./sky.js";
import { bandSpectrogram, photoColor, ringSpectrogram } from "./viz.js";
import { rangeMap } from "./map.js";
import {
  chevron, fmtDay, fmtHour, fmtTime, get, h, isoWeek, names, num, parseDay, pct, photo, plural, secs,
} from "./util.js";

const SITE = "birbTrack";
const short = (d) => fmtDay(d, { month: "short", day: "numeric" });

function link(href, ...kids) {
  return h("a", { href, "data-link": true }, ...kids);
}

function pager(prev, next, label) {
  return h("nav", { class: "pager", "aria-label": label },
    prev ? h("a", { href: prev.href, "data-link": true, class: "pill", rel: "prev" }, chevron("left"), prev.text)
      : h("span"),
    next ? h("a", { href: next.href, "data-link": true, class: "pill", rel: "next" }, next.text, chevron("right"))
      : h("span"));
}

const badge = (kind, text) => h("span", { class: `badge ${kind}` }, text);
const hidden = (tag, text, id) => h(tag, { class: "vh", id }, text);
const cell = (attrs, ...kids) => h("section", { ...attrs, class: `cell ${attrs.class || ""}` }, ...kids);
const cells = (cls, ...kids) => h("section", { class: `cells ${cls}` }, ...kids);
const pane = (...kids) => h("div", { class: "pane" }, ...kids);

function birdImg(sp, size, cls = "") {
  return sp.photo
    ? h("img", { src: photo(sp.slug, size), alt: "", class: `bird-img ${cls}`, loading: "lazy", decoding: "async" })
    : h("span", { class: `bird-img none ${cls}`, "aria-hidden": "true" });
}

// ---------------------------------------------------------------- a day (and today)

// ring: { box, colorOf(sci) } so a call played here paints around the disc
function centerLatest(center, d, lastEver, ring) {
  const det = d.latest || lastEver;
  center.classList.toggle("has-photo", Boolean(det?.photo));
  if (!det) {
    center.replaceChildren(h("p", { class: "center-quiet" }, "Quiet"));
    return;
  }
  // the bird fills the disc; name and time sit on a shade at the bottom
  const play = det.clip ? playButton(det, {
    onAudio: (audio, button) => ring && ringSpectrogram(ring.box, audio, button, () => ring.colorOf(det.sci)),
  }) : null;
  const bg = det.photo ? h("img", { src: photo(det.slug, 320), alt: "", class: "center-bg", decoding: "async" }) : null;
  if (bg && play) {
    bg.classList.add("tappable");
    bg.addEventListener("click", () => play.querySelector("button").click());
  }
  center.replaceChildren(...[
    bg,
    h("div", { class: "center-cap" },
      h("div", { class: "center-row" },
        play,
        link(`/d/${det.id}`, h("span", { class: "center-name" }, det.common))),
      h("p", { class: "center-time" }, d.latest ? fmtTime(det.time) : `${short(det.day)}, ${fmtTime(det.time)}`)),
  ].filter(Boolean));
}

// the hovered ring's bird fills the disc, edged in its lane color
function centerReadout(center, sp, hour) {
  center.classList.toggle("has-photo", sp.photo);
  const count = h("p", { class: `center-count${sp.hourly[hour] ? "" : " zero"}` }, num(sp.hourly[hour]));
  const name = h("span", { class: "center-name" }, sp.common);
  const time = h("p", { class: "center-time" }, fmtHour(hour));
  center.replaceChildren(...(sp.photo
    ? [h("img", { src: photo(sp.slug, 320), alt: "", class: "center-bg", decoding: "async" }),
       h("span", { class: `center-edge ${laneClass(sp._i)}`, "aria-hidden": "true" }),
       h("div", { class: "center-cap readout" }, name, time, count)]
    : [h("span", { class: `center-chip ${laneClass(sp._i)}` }), name, time, count]));
}

// restart a one-shot CSS animation
function replay(el, cls) {
  el.classList.remove(cls);
  void el.offsetWidth;
  el.classList.add(cls);
}

// the new bird fades in over the one it replaces
function crossfade(center, old) {
  const img = center.querySelector(".center-bg");
  if (!old || !img || old.src === img.src) return;
  old.classList.remove("tappable", "arriving");
  old.classList.add("leaving");
  img.classList.add("arriving");
  img.before(old);
  setTimeout(() => old.remove(), 1000);
}

function rollCall(d, D) {
  const lanes = () => {
    const byLane = d.species.map(() => []);
    for (const [t, i] of d.points) byLane[i].push(t);
    return byLane;
  };
  const byLane = lanes();
  const list = h("ol", { class: "roll", "aria-labelledby": "roll-title" });
  const rows = d.species.map((sp, i) => {
    const flags = [];
    if (sp.lifer) flags.push(badge("lifer", "New yard bird"));
    if (sp.back_after) flags.push(badge("back", `Back after ${sp.back_after} days`));
    const count = h("span", { class: "roll-count", "aria-label": plural(sp.count, "call") }, num(sp.count));
    const bars = strip(byLane[i], laneClass(i), d.sunrise, d.sunset);
    const row = h("li", { class: `roll-row ${laneClass(i)}` },
      link(`/bird/${sp.slug}`,
        h("span", { class: "chip", "aria-hidden": "true" }),
        h("span", { class: "roll-names" }, names(sp), flags.length ? h("span", { class: "flags" }, flags) : null),
        bars, count));
    row.addEventListener("pointerenter", () => D.focus(i));
    row.addEventListener("pointerleave", () => D.focus(null));
    row.addEventListener("focusin", () => D.focus(i));
    row.addEventListener("focusout", () => D.focus(null));
    list.append(row);
    return { row, count, bars };
  });
  // a call: counts tick over, and the caller's row lights up
  const refresh = (sci) => {
    const now = lanes();
    d.species.forEach((sp, i) => {
      const r = rows[i];
      if (r.count.textContent !== num(sp.count)) {
        r.count.textContent = num(sp.count);
        r.count.setAttribute("aria-label", plural(sp.count, "call"));
        replay(r.count, "tick");
        const bars = strip(now[i], laneClass(i), d.sunrise, d.sunset);
        r.bars.replaceWith(bars);
        r.bars = bars;
      }
      if (sp.sci === sci) replay(r.row, "lit");
    });
  };
  return { el: cell({ class: "roll-cell" }, hidden("h2", "Species", "roll-title"), list), refresh };
}

function dayView(d, { lastEver, status } = {}) {
  d.species.forEach((sp, i) => { sp._i = i; });
  const center = h("div", { class: "dial-center" });
  const keyTime = () => (d.is_today ? yardNow(d.tz) : (d.latest ? secs(d.latest.time) : null));
  const ring = {
    box: null,
    colorOf: (sci) => {
      const i = d.species.findIndex((sp) => sp.sci === sci);
      const el = i >= 0 ? ring.box.querySelector(`.lane.${laneClass(i)}`) : null;
      return (el && getComputedStyle(el).getPropertyValue("--k").trim())
        || getComputedStyle(ring.box).getPropertyValue("--hero-ink").trim() || "#ffffff";
    },
  };
  // while a call plays the disc keeps its bird
  const D = dial(d, {
    keyTime,
    onHover: (hit) => {
      if (dialBox.classList.contains("listening")) return;
      if (hit) centerReadout(center, d.species[hit.i], hit.hour);
      else centerLatest(center, d, lastEver, ring);
    },
  });
  const day = parseDay(d.date);
  const dialBox = h("div", { class: "dial" }, D.el, center);
  ring.box = dialBox;
  // a mouse on the dial or a call playing holds it still (mice only: a tap leaves :hover stuck)
  let hovering = false;
  dialBox.addEventListener("pointerenter", (e) => { hovering = e.pointerType === "mouse"; });
  dialBox.addEventListener("pointerleave", () => { hovering = false; });
  const busy = () => hovering || dialBox.classList.contains("listening");
  centerLatest(center, d, lastEver, ring);
  const tally = h("p", { class: "tally" });
  const caption = h("p", { class: "dial-caption" });
  const fill = () => {
    tally.hidden = !d.total;
    tally.replaceChildren(h("span", {}, plural(d.species_count, "species", "species")),
      h("span", {}, plural(d.total, "call")));
    const shown = d.latest || lastEver;
    caption.hidden = !shown;
    caption.replaceChildren(...(shown ? [link(`/d/${shown.id}`, shown.common),
      h("span", {}, d.latest ? fmtTime(shown.time) : `${short(shown.day)}, ${fmtTime(shown.time)}`)] : []));
  };
  fill();
  const hero = h("section", { class: "hero sky" },
    h("span", { class: "grain", "aria-hidden": "true" }),
    h("div", { class: "sky-in" },
      h("div", { class: "day-type" },
        h("h1", { class: "giant" },
          h("span", { class: "giant-1" }, day.toLocaleDateString("en-US", { weekday: "long" })),
          h("span", { class: "giant-2" }, day.toLocaleDateString("en-US",
            d.is_today ? { month: "long", day: "numeric" } : { month: "long", day: "numeric", year: "numeric" }))),
        tally,
        status || null,
        pager(d.prev ? { href: `/day/${d.prev}`, text: short(d.prev) } : null,
          d.next ? { href: `/day/${d.next}`, text: short(d.next) } : (!d.is_today ? { href: "/", text: "Today" } : null),
          "Other days")),
      h("div", { class: "dial-wrap" }, dialBox, caption)));
  // the sky is painted for the hero's moment, and its glow comes from the sun on the dial rim
  const repaint = () => {
    paint(hero, skyAt(keyTime() ?? 6 * 3600, d.sunrise, d.sunset));
    D.refresh();
    requestAnimationFrame(() => glowFrom(hero, dialBox, D.orb));
  };
  repaint();
  const timer = d.is_today ? setInterval(repaint, 60000) : null;
  const onResize = () => glowFrom(hero, dialBox, D.orb);
  window.addEventListener("resize", onResize);
  const roll = d.species.length ? rollCall(d, D) : null;
  const node = h("div", { class: "day" }, hero, roll?.el);

  // the newest call takes the disc once nothing holds it
  let centerTimer = 0;
  const showLatest = () => {
    clearTimeout(centerTimer);
    if (busy()) {
      centerTimer = setTimeout(showLatest, 1000);
      return;
    }
    const old = center.querySelector(".center-bg");
    centerLatest(center, d, lastEver, ring);
    crossfade(center, old);
  };
  // a call into lanes already drawn lands in place; a new species or a new day needs a new view
  const update = (fresh, det) => {
    if (fresh.date !== d.date || fresh.species.length !== d.species.length
      || fresh.species.some((sp, i) => sp.sci !== d.species[i].sci)) return false;
    fresh.species.forEach((sp, i) => { sp._i = i; });
    Object.assign(d, fresh);
    lastEver = det;
    fill();
    D.add(d.points);
    D.land(det.id);
    roll?.refresh(det.sci);
    showLatest();
    return true;
  };
  // the first view after new lanes: they draw themselves in, and the call lands
  const arrive = (det, before, old) => {
    d.species.forEach((sp, i) => { if (!before.has(sp.sci)) D.grow(i, { lifer: sp.lifer }); });
    D.land(det.id);
    roll?.refresh(det.sci);
    crossfade(center, old);
  };
  return {
    node, busy, update, arrive,
    species: () => new Set(d.species.map((sp) => sp.sci)),
    centerImg: () => center.querySelector(".center-bg"),
    dispose: () => {
      clearInterval(timer);
      clearTimeout(centerTimer);
      window.removeEventListener("resize", onResize);
      D.dispose();
    },
  };
}

export async function todayPage(ctx) {
  const [d, o] = await Promise.all([get("/api/day/today"), get("/api/overview")]);
  const root = h("div", { class: "page" });
  const status = h("p", { class: "status" }, h("span", { class: "status-dot", "aria-hidden": "true" }), h("span", {}, "Live"));
  let view = dayView(d, { lastEver: o.latest, status });
  root.append(view.node);

  // calls heard while the tab is in the background are counted in its title
  let unseen = 0;
  const title = () => { document.title = unseen ? `(${unseen}) ${SITE}` : SITE; };
  const seen = () => {
    if (document.hidden || !unseen) return;
    unseen = 0;
    title();
  };
  document.addEventListener("visibilitychange", seen);

  const es = new EventSource("/api/live");
  es.addEventListener("open", () => status.classList.add("on"));
  es.addEventListener("error", () => status.classList.remove("on"));
  // a call into the drawn lanes lands at once; one that adds a lane waits until nothing is
  // playing or under the mouse, then the view is redrawn around it
  let waiting = null, held = 0, seq = 0;
  const land = async () => {
    held = 0;
    if (ctx.gone() || !waiting) return;
    const det = waiting, mine = ++seq;
    waiting = null;
    const fresh = await get("/api/day/today").catch(() => null);
    if (!fresh || ctx.gone() || mine !== seq) return;
    if (view.update(fresh, det)) return;
    if (view.busy()) {
      waiting = waiting || det;
      held = setTimeout(land, 1000);
      return;
    }
    const before = view.species(), old = view.centerImg();
    view.dispose();
    view = dayView(fresh, { lastEver: det, status });
    root.replaceChildren(view.node);
    view.arrive(det, before, old);
  };
  es.addEventListener("detection", (e) => {
    waiting = JSON.parse(e.data);
    if (document.hidden) {
      unseen++;
      title();
    }
    if (!held) land();
  });
  return {
    node: root, title: SITE,
    dispose: () => {
      es.close();
      clearTimeout(held);
      document.removeEventListener("visibilitychange", seen);
      view.dispose();
    },
  };
}

export async function dayPage(ctx, day) {
  const d = await get(`/api/day/${day}`);
  const view = dayView(d);
  return { node: h("div", { class: "page" }, view.node), title: `${fmtDay(day)} | ${SITE}`, dispose: view.dispose };
}

// ---------------------------------------------------------------- the yard list

const SORTS = {
  count: ["Most heard", (a, b) => b.count - a.count],
  new: ["Newest", (a, b) => (b.first > a.first ? 1 : b.first < a.first ? -1 : b.yard_number - a.yard_number)],
  name: ["A to Z", (a, b) => a.common.localeCompare(b.common)],
};

export async function birdsPage() {
  const data = await get("/api/species");
  let sort = "count";
  let lately = false;
  const grid = h("ol", { class: "tiles" });
  const empty = cell({ class: "empty-cell", hidden: true }, h("p", { class: "empty" }, "Nothing in the last 30 days."));
  const render = () => {
    const rows = data.species.filter((sp) => !lately || sp.recent > 0).sort(SORTS[sort][1]);
    empty.hidden = rows.length > 0;
    grid.replaceChildren(...rows.map((sp) => h("li", { class: "tile" },
      link(`/bird/${sp.slug}`, birdImg(sp, 320, "tile-photo"),
        h("span", { class: "tile-text" }, names(sp), h("span", { class: "tile-count" }, num(sp.count)))))));
  };
  const sortGroup = h("div", { class: "seg", role: "radiogroup", "aria-label": "Sort" },
    Object.entries(SORTS).map(([key, [label]]) => {
      const b = h("button", { type: "button", role: "radio", "aria-checked": String(key === sort) }, label);
      b.addEventListener("click", () => {
        sort = key;
        sortGroup.querySelectorAll("button").forEach((x) => x.setAttribute("aria-checked", String(x === b)));
        render();
      });
      return b;
    }));
  const toggle = h("button", { type: "button", class: "toggle", "aria-pressed": "false" }, "Last 30 days");
  toggle.addEventListener("click", () => {
    lately = !lately;
    toggle.setAttribute("aria-pressed", String(lately));
    render();
  });
  render();
  return {
    title: `Birds | ${SITE}`,
    node: h("div", { class: "page birds" },
      cell({ class: "head-cell" },
        h("h1", { class: "giant" }, h("span", { class: "giant-1" }, num(data.total)), h("span", { class: "giant-2" }, "species")),
        h("div", { class: "controls" }, sortGroup, toggle)),
      empty,
      h("section", { class: "tiles-wrap" }, grid)),
  };
}

// ---------------------------------------------------------------- one species

// the hero photo is contained, so where it starts depends on its shape: fade in from there.
// On phones the photo stacks above the name, and the call overlays the photo, so its height is
// published too.
function featherFrom(img) {
  if (img.tagName !== "IMG") return img;
  const fit = () => {
    const hero = img.parentElement;
    if (!hero || !img.naturalWidth) return;
    const W = hero.clientWidth, H = hero.clientHeight;
    const left = Math.max(0, 1 - (H * img.naturalWidth) / img.naturalHeight / W);
    hero.style.setProperty("--photo-left", `${(left * 100).toFixed(1)}%`);
    hero.style.setProperty("--photo-h", `${img.clientHeight}px`);
  };
  img.addEventListener("load", () => {
    fit();
    new ResizeObserver(fit).observe(img.parentElement);
  });
  return img;
}

function aboutPane(sp) {
  const a = sp.about || {};
  // Wikidata sizes proved unreliable (a 3.4 g Western Tanager) and BirdNET's rarity is per week,
  // so the facts are only the ones that hold
  const facts = [
    ["Family", sp.family],
    ["Status", a.status],
  ].filter(([, v]) => v);
  const ext = [["eBird", sp.links?.ebird], ["All About Birds", sp.links?.allaboutbirds], ["Wikipedia", sp.links?.wikipedia]]
    .filter(([, href]) => href);
  const text = (a.intro || a.summary || "").split("\n").filter(Boolean);
  return pane(
    text.length ? h("div", { class: "summary" }, text.map((t) => h("p", {}, t))) : null,
    facts.length ? h("dl", { class: "facts" }, facts.map(([k, v]) => h("div", {}, h("dt", {}, k), h("dd", {}, v)))) : null,
    ext.length ? h("p", { class: "ext" }, ext.map(([label, href]) => h("a", { href, rel: "noopener" }, label))) : null);
}

function stat(value, label, href) {
  return h("div", { class: "pane stat" },
    h("dt", {}, label),
    h("dd", {}, href ? link(href, value) : value));
}

export async function birdPage(ctx, slug) {
  const sp = await get(`/api/species/${slug}`);
  const peak = sp.hourly.indexOf(Math.max(...sp.hourly));
  const tint = skyAt(peak * 3600 + 1800, "06:00:00", "19:00:00").stops[2];
  const img = featherFrom(birdImg(sp, 900, "photo-hero-img"));
  const shade = h("div", { class: "photo-shade" },
    h("h1", { class: "giant" }, sp.common),
    h("p", { class: "sci big" }, sp.sci));
  const hero = h("section", { class: "hero photo-hero", style: { "--shade-tint": tint } },
    // the photo is never cropped: it sits whole over a blurred copy of itself
    sp.photo ? h("img", { src: photo(sp.slug, 900), alt: "", class: "photo-hero-bg", "aria-hidden": "true" }) : null,
    img,
    h("span", { class: "grain", "aria-hidden": "true" }),
    shade,
    sp.credit ? h("p", { class: "credit" }, `${sp.credit.by}, ${sp.credit.license}`) : null);
  // the clearest recording plays from the hero and paints across the photo in the photo's color
  const call = sp.best[0];
  if (call) {
    let color = null;
    const tone = () => (color ||= img.complete && img.naturalWidth ? photoColor(img) : null) || "#f3f5f8";
    hero.append(h("p", { class: "hero-call" },
      link(`/d/${call.id}`, `${fmtDay(call.day)}, ${fmtTime(call.time)}`),
      playButton(call, { onAudio: (audio, button) => bandSpectrogram(hero, audio, button, tone) })));
  }
  const node = h("div", { class: "page bird" },
    hero,
    h("dl", { class: "cells four" },
      stat(num(sp.count), "Calls"),
      stat(num(sp.days), "Days"),
      stat(fmtDay(sp.first), "First heard", sp.first_id ? `/d/${sp.first_id}` : null),
      stat(`No. ${sp.yard_number}`, "Yard list")),
    sp.fact ? cell({}, h("p", { class: "fact" }, sp.fact)) : null,
    cells("two range-about",
      pane(h("h2", {}, "Range"), rangeMap(sp, sp.tz)),
      aboutPane(sp)),
    cells("two",
      pane(h("h2", {}, "Day"), hourBars(sp.hourly, { label: `${sp.common} calls per hour` })),
      pane(h("h2", {}, "Year"), yearMatrix(sp.year), yearMatrix(sp.year, { months: true }))),
    sp.best.length ? cells("three",
      sp.best.map((det) => pane(player(det),
        h("p", { class: "best-meta" }, link(`/d/${det.id}`, `${fmtDay(det.day)}, ${fmtTime(det.time)}`),
          h("span", {}, pct(det.confidence)))))) : null,
    cell({},
      h("h2", {}, "Latest"),
      h("ol", { class: "det-list" }, sp.recent.map((det) => detRow(det, { date: true })))));
  return { node, title: `${sp.common} | ${SITE}` };
}

function detRow(det, { date = false, name = false } = {}) {
  return h("li", { class: "det-row" },
    det.clip ? playButton(det) : h("span", { class: "mini-player" }),
    link(`/d/${det.id}`, name ? h("span", { class: "det-name" }, det.common) : null,
      h("span", { class: "det-when" }, date ? `${fmtDay(det.day)}, ${fmtTime(det.time)}` : fmtTime(det.time))),
    h("span", { class: "det-conf" }, pct(det.confidence)));
}

// ---------------------------------------------------------------- one detection

export async function detectionPage(ctx, id) {
  const det = await get(`/api/detection/${id}`);
  const node = h("div", { class: "page detection" },
    cell({ class: "head-cell" },
      det.lifer ? badge("lifer", "New yard bird") : null,
      h("h1", { class: "giant" }, det.common),
      h("p", { class: "sci big" }, det.sci),
      h("p", { class: "when-line" },
        h("span", {}, fmtTime(det.time)),
        link(`/day/${det.day}`, fmtDay(det.day, { weekday: "long", month: "long", day: "numeric", year: "numeric" })),
        h("span", { class: "conf" }, pct(det.confidence)))),
    det.clip ? h("section", { class: "hero spectro-hero" }, player(det, { size: "lg" })) : null,
    cells("two",
      pane(link(`/bird/${det.slug}`, birdImg(det, 320, "det-photo")),
        h("h2", {}, link(`/bird/${det.slug}`, det.common)),
        det.fact ? h("p", { class: "fact small" }, det.fact) : null),
      det.nearby.length ? pane(h("h2", {}, "Nearby"),
        h("ol", { class: "det-list" }, det.nearby.map((n) => detRow(n, { name: true })))) : null),
    cell({ class: "pager-cell" },
      pager(det.prev ? { href: `/d/${det.prev}`, text: "Previous" } : null,
        det.next ? { href: `/d/${det.next}`, text: "Next" } : null, `Other ${det.common} calls`)));
  return { node, title: `${det.common}, ${fmtDay(det.day)} | ${SITE}` };
}

// ---------------------------------------------------------------- a week

const weekNo = (key) => Number(key.split("W")[1]);
const range = (w) => `${fmtDay(w.start, { month: "short", day: "numeric" })} to ${fmtDay(w.end)}`;

function weekHead(w, ...kids) {
  return cell({ class: "head-cell" },
    h("h1", { class: "giant" }, h("span", { class: "giant-2" }, "Week"), h("span", { class: "giant-1" }, String(w.number))),
    h("p", { class: "sub" }, range(w)), ...kids);
}

export async function weekPage(ctx, key) {
  const w = await get(`/api/week/${key}`);
  if (!w.total) {
    const o = await get("/api/overview");
    const back = o.latest ? isoWeek(o.latest.day) : null;
    return {
      title: `Week ${w.number} | ${SITE}`,
      node: h("div", { class: "page week" },
        weekHead(w, h("p", { class: "empty" }, "Quiet so far.")),
        back ? cell({ class: "pager-cell" }, pager({ href: `/week/${back}`, text: `Week ${weekNo(back)}` }, null, "Other weeks")) : null),
    };
  }
  const top = w.species[0]?.count || 1;
  const award = (title, a, line) => pane(h("h3", {}, title),
    a ? link(`/bird/${a.slug}`, a.common) : null, a ? h("p", {}, line) : null);
  const birdList = (title, list, extra) => list.length ? pane(h("h3", {}, title),
    h("ul", { class: "mini-list" }, list.map((sp) => h("li", {}, link(`/bird/${sp.slug}`, sp.common),
      extra ? h("span", {}, extra(sp)) : null)))) : null;
  const change = w.total_change ? h("span", { class: "delta" },
    `${w.total_change > 0 ? "+" : "−"}${Math.abs(w.total_change)}%`) : null;
  const news = [birdList("New yard birds", w.lifers), birdList("New this week", w.new_vs_last_week),
    birdList("Back", w.returning, (sp) => `${sp.days_away} days`)].filter(Boolean);
  const node = h("div", { class: "page week" },
    weekHead(w, h("p", { class: "tally" },
      h("span", {}, plural(w.species_count, "species", "species")),
      h("span", {}, plural(w.total, "call"), change ? " " : null, change))),
    cells("two", pane(dayBars(w.daily)), pane(hourBars(w.hourly))),
    cells("three awards",
      award("Early bird", w.early_bird, w.early_bird && `${fmtTime(w.early_bird.time)}, ${fmtDay(w.early_bird.day, { weekday: "long" })}`),
      award("Night owl", w.night_owl, w.night_owl && `${fmtTime(w.night_owl.time)}, ${fmtDay(w.night_owl.day, { weekday: "long" })}`),
      award("Most loyal", w.most_loyal, w.most_loyal && `${w.most_loyal.days} of 7 days`)),
    cell({},
      hidden("h2", "Species"),
      h("ol", { class: "rank" }, w.species.map((sp) => h("li", {},
        link(`/bird/${sp.slug}`, names(sp)), meter(sp.count, top), h("span", { class: "rank-count" }, num(sp.count)))))),
    news.length ? cells(news.length === 3 ? "three" : news.length === 2 ? "two" : "one", news) : null,
    w.spotlight ? cells("two spotlight",
      w.spotlight.photo ? pane(link(`/bird/${w.spotlight.slug}`, birdImg(w.spotlight, 900, "spot-photo"))) : null,
      pane(h("h2", { class: "spot-name" }, link(`/bird/${w.spotlight.slug}`, w.spotlight.common)),
        h("p", { class: "fact" }, w.spotlight.fact))) : null,
    cell({ class: "pager-cell" },
      pager(w.prev ? { href: `/week/${w.prev}`, text: `Week ${weekNo(w.prev)}` } : null,
        w.next ? { href: `/week/${w.next}`, text: `Week ${weekNo(w.next)}` } : null, "Other weeks")));
  return { node, title: `Week ${w.number} | ${SITE}` };
}

// ---------------------------------------------------------------- not found / trouble

export function notFoundPage() {
  return {
    title: `Not found | ${SITE}`,
    node: h("div", { class: "page" }, cell({ class: "head-cell" },
      h("h1", { class: "giant" }, "Not found"),
      h("p", { class: "links" }, link("/", "Today"), link("/birds", "Birds")))),
  };
}

export function troublePage() {
  return {
    title: SITE,
    node: h("div", { class: "page" }, cell({ class: "head-cell" },
      h("h1", { class: "giant" }, "Can't reach the log"),
      h("p", { class: "empty" }, "Reload to try again."))),
  };
}
