// Live spectrograms: while a call plays it paints itself, time along one axis, pitch along the
// other, loudness as opacity. From the dial center it paints a ring around the bird (time
// clockwise from the top, like the dial, pitch outward); on a species page it paints a band
// across the photo (time left to right, pitch upward).

const VIEW = 1200;            // the dial's viewBox span (-100..1100)
const R0 = 192, R1 = 404;     // ring radii in dial units: from the disc edge across the dimmed lanes
const F_LO = 1000, F_HI = 12000;
const TAU = Math.PI * 2;
const UNIT = 255 / 68;        // the floor and margin below were tuned in byte steps of a 68 dB range
const PEAK0 = 20 * UNIT;      // full strength takes 20 dB over the band's floor, so noise alone stays faint

let ctx = null;

function audioContext() {
  if (!ctx) ctx = new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === "suspended") ctx.resume();
  return ctx;
}

function rgb(color) {
  const probe = document.createElement("span");
  probe.style.color = color;
  document.body.append(probe);
  const m = getComputedStyle(probe).color.match(/\d+(\.\d+)?/g) || [255, 255, 255];
  probe.remove();
  return m.slice(0, 3).map(Number);
}

const ink = ([r, g, b], level) => `rgba(${r}, ${g}, ${b}, ${Math.min(1, Math.pow(level, 1.4)).toFixed(3)})`;

// host gets the canvas (and .listening while it plays). fit(canvas) sizes it and returns its
// context; paint(g, p0, p1, levels, color) draws the stretch of the clip from p0 to p1 (0..1),
// one level (0..1) per pitch band.
function live({ host, audio, button, colorOf, cls, steps, fit, paint }) {
  let analyser = null, bins = null, canvas = null, g = null, raf = 0, last = null, color = [255, 255, 255];
  let peak = PEAK0, floor = null, n = 0;
  let fadeTimer = 0;

  const setup = () => {
    const ac = audioContext();
    if (!analyser) {
      const src = ac.createMediaElementSource(audio);
      analyser = ac.createAnalyser();
      analyser.fftSize = 2048;
      analyser.smoothingTimeConstant = 0.45;
      src.connect(analyser);
      analyser.connect(ac.destination);
      // decibels, not bytes: bytes clip at a fixed floor, and a quiet yard mic sits under it
      bins = new Float32Array(analyser.frequencyBinCount);
    }
  };

  const ensureCanvas = () => {
    clearTimeout(fadeTimer);
    if (!canvas) {
      canvas = document.createElement("canvas");
      canvas.className = cls;
      canvas.setAttribute("aria-hidden", "true");
      host.append(canvas);
    }
    g = fit(canvas);
    canvas.classList.remove("fading");
    color = rgb(colorOf());
    last = null;
    peak = PEAK0;
    floor = null;
    n = 0;
  };

  const frame = () => {
    raf = requestAnimationFrame(frame);
    // the first frames still hold the silence before the clip, which would set the floor far too low
    if (!audio.duration || !analyser || audio.currentTime < 0.12) return;
    analyser.getFloatFrequencyData(bins);
    const p = audio.currentTime / audio.duration;
    const p0 = last ?? 0;
    if (p - p0 < 0.0003) return;
    last = p;
    const hz = ctx.sampleRate / analyser.fftSize;
    const lo = Math.floor(F_LO / hz), hi = Math.min(bins.length - 1, Math.ceil(F_HI / hz));
    const per = (hi - lo) / steps;
    // each pitch band against its own noise floor (a running median: it steps toward every
    // reading), then the whole call against its loudest rise, so wind and hum sit at zero, only
    // the song paints, and quiet recordings still paint
    const levels = new Float32Array(steps).fill(-200);
    let any = -200;
    for (let k = 0; k < steps; k++) {
      for (let b = Math.floor(lo + k * per); b < lo + (k + 1) * per; b++) levels[k] = Math.max(levels[k], bins[b]);
      levels[k] *= UNIT;
      any = Math.max(any, levels[k]);
    }
    if (any <= -200 * UNIT) return;   // the decoder hasn't started: nothing to measure yet
    if (!floor) floor = Float32Array.from(levels);
    // quick to settle in the first half second, then slow enough that a held note isn't absorbed;
    // the first frames only teach the floor (a clip opens on lead-in before the call)
    const step = 0.4 + 4 * Math.max(0, 1 - n / 30);
    for (let k = 0; k < steps; k++) floor[k] += levels[k] > floor[k] ? step : -step;
    if (n++ < 8) return;
    for (let k = 0; k < steps; k++) {
      levels[k] = Math.max(0, levels[k] - floor[k] - 5);
      peak = Math.max(peak, levels[k]);
    }
    for (let k = 0; k < steps; k++) levels[k] = (levels[k] / peak - 0.12) / 0.88;
    paint(g, p0, p, levels, color);
  };

  const stop = (fade) => {
    cancelAnimationFrame(raf);
    host.classList.remove("listening");
    if (fade && canvas) {
      fadeTimer = setTimeout(() => canvas.classList.add("fading"), 2600);
    }
  };

  button.addEventListener("click", () => {
    try {
      setup();
    } catch {
      /* no Web Audio: the call still plays, just without the painting */
    }
  });
  audio.addEventListener("play", () => {
    if (!analyser) return;
    if (audio.currentTime < 0.05 || !canvas) ensureCanvas();
    host.classList.add("listening");
    cancelAnimationFrame(raf);
    raf = requestAnimationFrame(frame);
  });
  audio.addEventListener("pause", () => stop(false));
  audio.addEventListener("ended", () => stop(true));
}

function sized(canvas, w, hgt) {
  const dpr = Math.min(2, window.devicePixelRatio || 1);
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(hgt * dpr);
  return { g: canvas.getContext("2d"), dpr };
}

export function ringSpectrogram(dialBox, audio, button, colorOf) {
  const steps = 72, thick = (R1 - R0) / steps;
  live({
    host: dialBox, audio, button, colorOf, cls: "ring-spectro", steps,
    fit: (canvas) => {
      const size = dialBox.clientWidth;
      const { g, dpr } = sized(canvas, size, size);
      const k = (dpr * size) / VIEW;
      g.setTransform(k, 0, 0, k, 100 * k, 100 * k);
      g.lineWidth = thick + 0.6;
      return g;
    },
    paint: (g, p0, p1, levels, color) => {
      const a0 = p0 * TAU - TAU / 4, a1 = p1 * TAU - TAU / 4;
      levels.forEach((level, k) => {
        if (level <= 0.03) return;
        g.strokeStyle = ink(color, level);
        g.beginPath();
        g.arc(500, 500, R0 + (k + 0.5) * thick, a0 - 0.004, a1 + 0.004);
        g.stroke();
      });
    },
  });
}

export function bandSpectrogram(hero, audio, button, colorOf) {
  const steps = 144;
  let w = 0, hgt = 0;
  live({
    host: hero, audio, button, colorOf, cls: "band-spectro", steps,
    fit: (canvas) => {
      const { g } = sized(canvas, canvas.clientWidth, canvas.clientHeight);
      w = canvas.width;
      hgt = canvas.height;
      return g;
    },
    // whole device pixels, edge to edge: overlapping translucent rects would leave a mesh
    paint: (g, p0, p1, levels, color) => {
      const x0 = Math.round(p0 * w), x1 = Math.round(p1 * w);
      if (x1 <= x0) return;
      levels.forEach((level, k) => {
        if (level <= 0.03) return;
        const y0 = Math.round(hgt * (1 - (k + 1) / steps)), y1 = Math.round(hgt * (1 - k / steps));
        g.fillStyle = ink(color, level);
        g.fillRect(x0, y0, x1 - x0, y1 - y0);
      });
    },
  });
}

// the bird's own color, lifted to glow on the dark shade: the most vivid hue in the middle of the
// frame, discounted by how much of the frame's edge it fills (sky and leaves reach the edges, the
// bird rarely does). One hue, not an average: red and blue average to grey.
export function photoColor(img) {
  try {
    const n = 40;
    const c = document.createElement("canvas");
    c.width = c.height = n;
    const g = c.getContext("2d", { willReadFrequently: true });
    g.drawImage(img, 0, 0, n, n);
    const px = g.getImageData(0, 0, n, n).data;
    const hues = Array.from({ length: 24 }, () => [0, 0, 0, 0]);   // weight, r, g, b
    const edge = new Float32Array(24);
    for (let i = 0; i < n * n; i++) {
      const [r, gr, b] = [px[i * 4], px[i * 4 + 1], px[i * 4 + 2]];
      const max = Math.max(r, gr, b), d = max - Math.min(r, gr, b);
      if (d < 24) continue;
      const hue = max === r ? (((gr - b) / d) % 6 + 6) % 6 : max === gr ? (b - r) / d + 2 : (r - gr) / d + 4;
      const x = (i % n) / n - 0.5, y = Math.floor(i / n) / n - 0.5;
      const k = Math.floor(hue * 4) % 24, chroma = (d / 255) ** 2;
      const wt = chroma * Math.exp(-(x * x + y * y) / 0.125);
      const bin = hues[k];
      bin[0] += wt; bin[1] += r * wt; bin[2] += gr * wt; bin[3] += b * wt;
      if (Math.max(Math.abs(x), Math.abs(y)) > 0.4) edge[k] += chroma;
    }
    const near = (i) => [-1, 0, 1].map((o) => hues[(i + o + 24) % 24]);
    const edgeAll = edge.reduce((t, v) => t + v, 0) || 1;
    const score = (i) => near(i).reduce((t, h) => t + h[0], 0)
      * (1 - [-1, 0, 1].reduce((t, o) => t + edge[(i + o + 24) % 24], 0) / edgeAll);
    const best = hues.reduce((bi, _, i) => (score(i) > score(bi) ? i : bi), 0);
    const pick = near(best), total = pick.reduce((t, h) => t + h[0], 0);
    if (total < 0.5) return null;
    const [r, gr, b] = [1, 2, 3].map((j) => pick.reduce((t, h) => t + h[j], 0) / total / 255);
    const max = Math.max(r, gr, b), min = Math.min(r, gr, b), l = (max + min) / 2, d = max - min;
    if (d < 0.33) return null;   // a drab bird glows white rather than an invented orange
    const sat = d / (1 - Math.abs(2 * l - 1) || 1);
    const hue = (max === r ? ((gr - b) / d) % 6 : max === gr ? (b - r) / d + 2 : (r - gr) / d + 4) * 60;
    return `hsl(${((hue + 360) % 360).toFixed(0)} ${(Math.max(sat, 0.62) * 100).toFixed(0)}% ${(Math.min(0.8, Math.max(l, 0.68)) * 100).toFixed(0)}%)`;
  } catch {
    return null;
  }
}
