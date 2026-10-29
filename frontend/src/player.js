// Recordings: the spectrogram with a playhead that follows the audio, or just a play button.
// One recording plays at a time across the whole page.

import { h, s } from "./util.js";

let current = null;

function icon() {
  return s("svg", { viewBox: "0 0 24 24", class: "play-icon", "aria-hidden": "true" },
    s("path", { class: "i-play", d: "M7.5 4.5 L20 12 L7.5 19.5 Z" }),
    s("path", { class: "i-pause", d: "M6.5 4.5 H10.5 V19.5 H6.5 Z M13.5 4.5 H17.5 V19.5 H13.5 Z" }));
}

function wire(det, root, button, onProgress) {
  const audio = new Audio();
  audio.preload = "none";
  audio.src = `/media/clip/${det.id}.mp3`;
  const label = (playing) => button.setAttribute("aria-label",
    `${playing ? "Pause" : "Play"} the ${det.common} call from ${det.time.slice(0, 5)}`);
  label(false);
  const frame = () => {
    if (audio.paused) return;
    onProgress?.(audio.duration ? audio.currentTime / audio.duration : 0);
    requestAnimationFrame(frame);
  };
  const toggle = () => {
    if (audio.paused) {
      if (current && current !== audio) current.pause();
      current = audio;
      audio.play().catch(() => root.classList.add("failed"));
    } else {
      audio.pause();
    }
  };
  audio.addEventListener("play", () => { root.classList.add("playing"); label(true); frame(); });
  audio.addEventListener("pause", () => { root.classList.remove("playing"); label(false); });
  audio.addEventListener("ended", () => { onProgress?.(0); });
  audio.addEventListener("error", () => root.classList.add("failed"));
  button.addEventListener("click", toggle);
  return { toggle, audio };
}

export function player(det, { size = "md" } = {}) {
  const head = h("span", { class: "playhead" });
  const img = h("img", { src: `/media/spectro/${det.id}.png`, alt: `Spectrogram of the ${det.common} call`,
    loading: "lazy", decoding: "async" });
  const button = h("button", { type: "button", class: "play" }, icon());
  const root = h("figure", { class: `player ${size}` }, h("div", { class: "spectro" }, img, head), button);
  const { toggle } = wire(det, root, button, (p) => head.style.setProperty("--p", p.toFixed(4)));
  img.addEventListener("click", toggle);
  return root;
}

// onAudio(audio, button) lets the dial center hang its ring spectrogram on the clip
export function playButton(det, { onAudio } = {}) {
  const button = h("button", { type: "button", class: "play small" }, icon());
  const root = h("span", { class: "mini-player" }, button);
  const { audio } = wire(det, root, button);
  onAudio?.(audio, button);
  return root;
}
