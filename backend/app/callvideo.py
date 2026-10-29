"""Call videos for Discord: the bird's photo with its call painting across it as a spectrogram, a
playhead sweeping in time with the sound. Discord plays a video in the post but offers an mp3 only
as a download. Needs ffmpeg; without it a post keeps the still spectrogram.
"""

import asyncio
import colorsys
import logging
import math
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import httpx

from . import bng

log = logging.getLogger("birbtrack.callvideo")
FFMPEG, FFPROBE = shutil.which("ffmpeg"), shutil.which("ffprobe")
W, H, FPS = 1280, 720, 30
BAND_Y, BAND_H = 392, 296         # the band across the lower photo
SW, SH = W // 2, BAND_H // 2      # the spectrum is read at half size and drawn up: bolder, like the site's coarse band
F_LO, F_HI = 1000, 12000          # as on the site: wind and traffic live below 1 kHz
DRANGE = 120                      # dB across the 0..255 the spectrum comes in: wide, so a quiet clip's floor isn't clipped
DB = 255 / DRANGE
AHEAD = 0.3                       # the call still to come, at this strength
NIGHT = "0x1B2150"                # behind a bird with no photo
WHITE = (243, 245, 248)           # the ink for a drab bird, as on the site
_gate = asyncio.Semaphore(1)


def run(args: list, data: bytes | None = None) -> bytes:
    return subprocess.run(args, input=data, capture_output=True, check=True, timeout=120).stdout


def band(clip: Path) -> bytes:
    """The call as alpha, a byte per pixel: each pitch row against its own noise floor (its median),
    then the whole call against its loudest rise, so hum stays dark and a quiet call still shows."""
    raw = run([FFMPEG, "-v", "error", "-i", str(clip), "-filter_complex",
               f"showspectrumpic=s={SW}x{SH}:legend=0:color=intensity:scale=log:fscale=lin"
               f":start={F_LO}:stop={F_HI}:drange={DRANGE},format=gray",
               "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "gray", "-"])
    if len(raw) != SW * SH:
        raise ValueError(f"spectrum came back {len(raw)} bytes")
    margin = round(3 * DB)
    rows = []
    for i in range(SH):
        r = raw[i * SW:(i + 1) * SW]
        floor = sorted(r)[SW // 2] + margin
        rows.append(r.translate(bytes(max(0, v - floor) for v in range(256))))
    hist, seen, top = Counter(b"".join(rows)), 0, 0
    for v in range(255, 0, -1):
        seen += hist[v]
        if seen > SW * SH / 400:    # the loudest 400th, so one click doesn't set the scale
            top = v
            break
    peak = max(top, 20 * DB)        # a call needs 20 dB over the floor to paint at full strength
    ink = bytes(round(255 * min(1, max(0, (v / peak - 0.12) / 0.88))) for v in range(256))
    return b"".join(r.translate(ink) for r in rows)


def bird_color(photo: Path) -> tuple[int, int, int]:
    """viz.js photoColor: the most vivid hue in the middle of the frame, discounted by how much of
    the frame's edge it fills, lifted to glow on the dark shade; white for a drab bird."""
    n = 40
    px = run([FFMPEG, "-v", "error", "-i", str(photo), "-vf", f"scale={n}:{n}:flags=area",
              "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"])
    if len(px) != n * n * 3:
        return WHITE
    hues = [[0.0, 0.0, 0.0, 0.0] for _ in range(24)]   # weight, r, g, b
    edge = [0.0] * 24
    for i in range(n * n):
        r, g, b = px[i * 3:i * 3 + 3]
        hi, d = max(r, g, b), max(r, g, b) - min(r, g, b)
        if d < 24:
            continue
        hue = ((g - b) / d) % 6 if hi == r else (b - r) / d + 2 if hi == g else (r - g) / d + 4
        x, y = (i % n) / n - 0.5, (i // n) / n - 0.5
        k, chroma = math.floor(hue * 4) % 24, (d / 255) ** 2
        wt = chroma * math.exp(-(x * x + y * y) / 0.125)
        hues[k][0] += wt
        hues[k][1] += r * wt
        hues[k][2] += g * wt
        hues[k][3] += b * wt
        if max(abs(x), abs(y)) > 0.4:
            edge[k] += chroma
    near = lambda i: [hues[(i + o) % 24] for o in (-1, 0, 1)]
    edge_all = sum(edge) or 1
    score = lambda i: sum(h[0] for h in near(i)) * (1 - sum(edge[(i + o) % 24] for o in (-1, 0, 1)) / edge_all)
    best = max(range(24), key=lambda i: (score(i), -i))
    pick = near(best)
    total = sum(h[0] for h in pick)
    if total < 0.5:
        return WHITE
    r, g, b = (sum(h[j] for h in pick) / total / 255 for j in (1, 2, 3))
    l, d = (max(r, g, b) + min(r, g, b)) / 2, max(r, g, b) - min(r, g, b)
    if d < 0.33:
        return WHITE
    sat = d / ((1 - abs(2 * l - 1)) or 1)
    h, _, _ = colorsys.rgb_to_hls(r, g, b)
    return tuple(round(c * 255) for c in colorsys.hls_to_rgb(h, min(0.8, max(l, 0.68)), min(1, max(sat, 0.62))))


def render(clip: bytes, photo: Path | None) -> bytes:
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        call, alpha, out = tmp / "call.mp3", tmp / "band.raw", tmp / "call.mp4"
        call.write_bytes(clip)
        alpha.write_bytes(band(call))
        dur = float(run([FFPROBE, "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(call)]))
        x = f"floor({W}*t/{dur:.3f})"
        still = f"settb=AVTB,loop=loop=-1:size=1,setpts=N/{FPS}/TB"
        ink = "0x%02X%02X%02X" % (bird_color(photo) if photo else WHITE)
        # the photo shaded toward the bottom, easing in, so the ink reads over any of it
        s = f"clip((Y-170)/{BAND_Y + 60 - 170},0,1)"
        shade = f"255*0.9*{s}*{s}*(3-2*{s})"
        graph = (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},format=rgba[ph];"
            f"color=black:s={W}x{H}:d=1,format=rgba,geq=r=0:g=0:b=0:a='{shade}'[sh];"
            f"[ph][sh]overlay=format=rgb,split[bg1][bg2];"
            f"color={ink}:s={W}x{BAND_H}:d=1,format=rgba,split[w1][w2];"
            # drawn up from half size, with a soft glow so a call reads at Discord's preview size
            f"[1:v]format=gray,scale={W}:{BAND_H}:flags=bicubic,split[sharp][wide];"
            f"[wide]gblur=sigma=6,lut=c0='min(255,val*1.8)'[glow];"
            f"[sharp][glow]blend=all_mode=lighten,split[a1][a2];[a2]lut=c0=val*{AHEAD}[a3];"
            f"[w1][a1]alphamerge[k1];[w2][a3]alphamerge[k2];"
            # played: full ink; ahead: faint ink, cropped to what's right of the playhead
            f"[bg1][k1]overlay=0:{BAND_Y}:format=rgb,{still}[played];"
            f"[bg2][k2]overlay=0:{BAND_Y}:format=rgb,crop={W}:{BAND_H}:0:{BAND_Y},format=rgba,"
            f"pad={2 * W}:{BAND_H}:0:0:color=black@0,{still},crop={W}:{BAND_H}:x='{x}':y=0[ahead];"
            f"color=white@0.85:s=3x{BAND_H + 20}:r={FPS},format=rgba[head];"
            f"[played][ahead]overlay=x='{x}':y={BAND_Y}[v1];"
            f"[v1][head]overlay=x='{x}-1':y={BAND_Y - 10},format=yuv420p[v]")
        back = ["-i", str(photo)] if photo else ["-f", "lavfi", "-i", f"color=c={NIGHT}:s={W}x{H}:d=1"]
        run([FFMPEG, "-v", "error", "-y", *back,
             "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{SW}x{SH}", "-i", str(alpha),
             "-i", str(call), "-filter_complex", graph, "-map", "[v]", "-map", "2:a", "-t", f"{dur:.3f}",
             "-c:v", "libx264", "-preset", "veryfast", "-crf", "24", "-tune", "stillimage", "-r", str(FPS),
             "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(out)])
        return out.read_bytes()


async def make(det_id: int, photo: Path | None) -> bytes | None:
    """The call video for a detection, or None: no ffmpeg, no clip, or the render failed."""
    if not (FFMPEG and FFPROBE):
        return None
    clip, why = None, None
    for _ in range(8):   # a live detection arrives a few seconds before its clip is written (503 until then)
        try:
            r = await bng.client().get(f"/audio/{det_id}")
            if r.status_code == 200 and r.content:
                clip = r.content
                break
            why = r.status_code
        except httpx.HTTPError as e:
            why = e
        await asyncio.sleep(3)
    if clip is None:
        log.warning("call video %s: no clip: %s", det_id, why)
        return None
    async with _gate:
        try:
            return await asyncio.to_thread(render, clip, photo)
        except subprocess.CalledProcessError as e:
            log.warning("call video %s: %s", det_id, e.stderr.decode(errors="replace")[-400:].strip())
        except (OSError, ValueError, subprocess.SubprocessError) as e:
            log.warning("call video %s: %s", det_id, e)
    return None
