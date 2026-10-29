import "@fontsource-variable/schibsted-grotesk";
import "@fontsource-variable/newsreader/wght-italic.css";
import "./style.css";

import {
  birdPage, birdsPage, dayPage, detectionPage, notFoundPage, todayPage, troublePage, weekPage,
} from "./pages.js";
import { NotFound } from "./util.js";

const routes = [
  [/^\/$/, "today", (ctx) => todayPage(ctx)],
  [/^\/day\/(\d{4}-\d{2}-\d{2})$/, "today", (ctx, m) => dayPage(ctx, m[1])],
  [/^\/birds$/, "birds", () => birdsPage()],
  [/^\/bird\/([a-z0-9-]{1,80})$/, "birds", (ctx, m) => birdPage(ctx, m[1])],
  [/^\/week\/(\d{4}-W\d{2}|this)$/, "week", (ctx, m) => weekPage(ctx, m[1])],
  [/^\/d\/(\d{1,11})$/, null, (ctx, m) => detectionPage(ctx, Number(m[1]))],
];

const main = document.getElementById("main");
let current = null;
let seq = 0;

async function render({ focus = false } = {}) {
  const path = location.pathname.replace(/\/+$/, "") || "/";
  const mine = ++seq;
  const ctx = { gone: () => mine !== seq };
  current?.dispose?.();
  current = null;
  let section = null;
  let page;
  main.setAttribute("aria-busy", "true");
  try {
    const hit = routes.find(([rx]) => rx.test(path));
    if (!hit) {
      page = notFoundPage();
    } else {
      section = hit[1] === "today" && path !== "/" ? null : hit[1];
      page = await hit[2](ctx, path.match(hit[0]));
    }
  } catch (e) {
    page = e instanceof NotFound ? notFoundPage() : troublePage();
    if (!(e instanceof NotFound)) console.error(e);
  }
  if (mine !== seq) {
    page.dispose?.();
    return;
  }
  current = page;
  document.title = page.title;
  main.replaceChildren(page.node);
  main.removeAttribute("aria-busy");
  document.querySelectorAll("[data-nav]").forEach((a) => {
    if (a.dataset.nav === section) a.setAttribute("aria-current", "page");
    else a.removeAttribute("aria-current");
  });
  if (focus) main.focus({ preventScroll: true });
}

document.addEventListener("click", (e) => {
  const a = e.target.closest("a[data-link]");
  if (!a || e.defaultPrevented || e.button !== 0 || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey) return;
  const url = new URL(a.href, location.href);
  if (url.origin !== location.origin) return;
  e.preventDefault();
  if (url.pathname === location.pathname) return;
  history.pushState({}, "", url.pathname);
  window.scrollTo(0, 0);
  render({ focus: true });
});

window.addEventListener("popstate", () => render());
render();
