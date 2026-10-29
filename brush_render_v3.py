#!/usr/bin/env python3
"""Two-phase brush renderer v3 (stoic vampire): dust-in phase, then brush-clean reveal.

Usage:
  python3 brush_render_v3.py --still IMG --out CLIP.mp4 --duration SECONDS \
      --dust-pattern P --dust-seed N --dust-radius PX [--dust-end S] \
      --clean-pattern P --clean-seed N --clean-radius PX [--clean-end S]
Patterns: {h_lr,h_rl,v_tb,v_bt,diag,circle,strokes} for each phase.

Dirty layer parameters are copied EXACTLY from the approved v2 test
(brush_reveal.py): blur 2.2, brightness 0.60, dusty veil (104,96,80 @ 0.22),
static grain sigma 55, specks, 48 scratches, 120 dust blotches,
animated grain sigma 16 wherever currently dusty and not yet cleaned.
Timing: image starts CLEAN; dust brushes ON until dust-end (auto: 3.0s,
or 30% of duration when duration < 10s); clean sweep runs dust-end ->
clean-end (auto: 92% of duration); clean hold to the end.
Output: 1280x720, 30fps, silent, H.264 yuv420p, crf 20.
"""
import argparse, math, subprocess, sys
import numpy as np
from PIL import Image, ImageFilter

W, H, FPS = 1280, 720, 30
HOLD_IN = 0.7

def build_dirty(img, rng):
    dirty_pil = img.filter(ImageFilter.GaussianBlur(2.2))
    dirty = np.asarray(dirty_pil).astype(np.float32) * 0.60
    dirty = dirty * 0.78 + np.array([104.0, 96.0, 80.0], dtype=np.float32) * 0.22
    dirty += rng.normal(0, 55, (H, W, 1)).astype(np.float32)
    speck = rng.random((H, W, 1))
    dirty += (speck > 0.996) * 200
    dirty -= (speck < 0.004) * 150
    for _ in range(48):
        x = rng.integers(0, W)
        dirty[:, max(0, x - 1):x + 1] += rng.uniform(24, 60)
    for _ in range(120):
        cx, cy, r = rng.integers(0, W), rng.integers(0, H), rng.integers(40, 190)
        yy, xx = np.mgrid[max(0, cy - r):min(H, cy + r), max(0, cx - r):min(W, cx + r)]
        d2 = (xx - cx) ** 2 + (yy - cy) ** 2
        dirty[max(0, cy - r):min(H, cy + r), max(0, cx - r):min(W, cx + r)] += \
            (np.exp(-d2 / (2 * (r / 2) ** 2)) * rng.uniform(22, 58))[..., None]
    return np.clip(dirty, 0, 255)

def pass_centers(extent, R, feather):
    """Centers along the cross axis so stamped discs fully cover `extent`."""
    core = R - feather
    step = max(60.0, 1.55 * core)
    first = core * 0.72
    centers = []
    c = first
    while c < extent - core * 0.72:
        centers.append(c)
        c += step
    centers.append(extent - core * 0.72)
    return centers

class Serpentine:
    """Serpentine brush path. horizontal: passes run along X, stacked in Y.
    mirror_x / mirror_y flip the whole path (R->L / bottom->top variants)."""
    def __init__(self, horizontal, mirror_x, mirror_y, R, feather, sweep_len):
        self.horizontal, self.mx, self.my = horizontal, mirror_x, mirror_y
        self.R = R
        if horizontal:
            self.centers = pass_centers(H, R, feather)
            self.span = W + 2 * R
        else:
            self.centers = pass_centers(W, R, feather)
            self.span = H + 2 * R
        self.total = self.span * len(self.centers)
        self.speed = self.total / sweep_len
    def pos(self, d):
        per = self.span
        idx = min(int(d // per), len(self.centers) - 1)
        local = d - idx * per - self.R
        fwd = (idx % 2 == 0)
        if self.horizontal:
            x = local if fwd else (W - local)
            y = self.centers[idx]
        else:
            y = local if fwd else (H - local)
            x = self.centers[idx]
        if self.mx: x = W - x
        if self.my: y = H - y
        return x, y

class Diagonal:
    """Serpentine passes along the frame diagonal (u axis), offset along v."""
    def __init__(self, R, feather, sweep_len, flip):
        diag = math.hypot(W, H)
        self.ux, self.uy = W / diag, H / diag
        if flip: self.uy = -self.uy
        self.vx, self.vy = -self.uy, self.ux
        self.passlen = diag
        perp = W * abs(self.uy) + H * abs(self.ux)
        core = R - feather
        step = max(60.0, 1.55 * core)
        offs = []
        o = -perp / 2 + core * 0.72
        while o < perp / 2 - core * 0.72:
            offs.append(o); o += step
        offs.append(perp / 2 - core * 0.72)
        self.offs = offs
        self.span = self.passlen + 2 * R
        self.total = self.span * len(offs)
        self.speed = self.total / sweep_len
        self.R = R
    def pos(self, d):
        idx = min(int(d // self.span), len(self.offs) - 1)
        local = d - idx * self.span - self.R - self.passlen / 2
        s = local if idx % 2 == 0 else -local
        cx, cy = W / 2 + self.vx * self.offs[idx], H / 2 + self.vy * self.offs[idx]
        return cx + self.ux * s, cy + self.uy * s


class PhaseBrush:
    """One brush phase: accumulates its own mask along a pattern.
    Path patterns (h_lr/h_rl/v_tb/v_bt/diag) use the soft-disc stamp of
    brush_render.py (feather 0.44R, smoothstep, <=6px stamp steps).
    circle = expanding disc from a jittered centre; strokes = 34 scattered
    strokes in random order — both ported from brush_render.py (v2)."""
    def __init__(self, pattern, R, sweep_len, seed, flip=False):
        self.pattern = pattern
        self.R = R
        self.feather = 0.44 * R
        self.sweep_len = sweep_len
        self.rng = np.random.default_rng(seed)
        yy, xx = np.mgrid[0:2 * R, 0:2 * R]
        dist = np.sqrt((xx - R) ** 2 + (yy - R) ** 2)
        st = np.clip((R - dist) / self.feather, 0, 1)
        self.stamp = st * st * (3 - 2 * st)
        self.mask = np.zeros((H, W), dtype=np.float32)
        self.path = None
        self.circle_c = None
        self.strokes = None
        if pattern in ("h_lr", "h_rl", "v_tb", "v_bt"):
            self.path = Serpentine(horizontal=pattern.startswith("h"),
                                   mirror_x=(pattern == "h_rl"),
                                   mirror_y=(pattern == "v_bt"),
                                   R=R, feather=self.feather, sweep_len=sweep_len)
        elif pattern == "diag":
            self.path = Diagonal(R, self.feather, sweep_len, flip=flip)
        elif pattern == "circle":
            jx = self.rng.uniform(-0.12, 0.12) * W
            jy = self.rng.uniform(-0.12, 0.12) * H
            self.circle_c = (W / 2 + jx, H / 2 + jy)
            corners = [(0, 0), (W, 0), (0, H), (W, H)]
            self.circle_max = max(math.hypot(cx - self.circle_c[0], cy - self.circle_c[1])
                                  for cx, cy in corners) + self.feather
            yyf, xxf = np.mgrid[0:H, 0:W]
            self.cdist = np.sqrt((xxf - self.circle_c[0]) ** 2 +
                                 (yyf - self.circle_c[1]) ** 2)
        elif pattern == "strokes":
            n = 34
            strokes = []
            for _ in range(n):
                cx, cy = self.rng.uniform(0, W), self.rng.uniform(0, H)
                ang = self.rng.uniform(0, 2 * math.pi)
                ln = self.rng.uniform(300, 640)
                x1 = min(max(cx + math.cos(ang) * ln, 0), W)
                y1 = min(max(cy + math.sin(ang) * ln, 0), H)
                strokes.append([cx, cy, x1, y1, 0.0])
            order = self.rng.permutation(n)
            self.strokes = [strokes[i] for i in order]
        else:
            raise ValueError(f"unknown pattern {pattern}")
        self.prev_d = 0.0

    def stamp_at(self, cx, cy):
        R = self.R
        cx, cy = int(round(cx)), int(round(cy))
        xa, ya = max(0, cx - R), max(0, cy - R)
        xb, yb = min(W, cx + R), min(H, cy + R)
        if xb <= xa or yb <= ya: return
        sub = self.stamp[ya - (cy - R):ya - (cy - R) + (yb - ya),
                         xa - (cx - R):xa - (cx - R) + (xb - xa)]
        np.maximum(self.mask[ya:yb, xa:xb], sub, out=self.mask[ya:yb, xa:xb])

    def advance(self, tp):
        """Advance the brush to phase-time tp (seconds); returns list of heads."""
        tp = min(max(tp, 0.0), self.sweep_len)
        if self.path is not None:
            d = tp * self.path.speed
            step_px = 6.0
            nsteps = max(1, int((d - self.prev_d) / step_px))
            for k in range(nsteps + 1):
                dd = self.prev_d + (d - self.prev_d) * k / nsteps
                self.stamp_at(*self.path.pos(dd))
            head = self.path.pos(d)
            self.prev_d = d
            return [head]
        if self.pattern == "circle":
            p = tp / self.sweep_len if self.sweep_len > 0 else 1.0
            r_now = p * self.circle_max
            m2 = np.clip((r_now - self.cdist) / self.feather, 0, 1)
            m2 = m2 * m2 * (3 - 2 * m2)
            np.maximum(self.mask, m2, out=self.mask)
            heads = []
            for _ in range(3):
                ang = self.rng.uniform(0, 2 * math.pi)
                heads.append((self.circle_c[0] + math.cos(ang) * r_now,
                              self.circle_c[1] + math.sin(ang) * r_now))
            return heads
        # strokes
        p = tp / self.sweep_len if self.sweep_len > 0 else 1.0
        heads = []
        for si, st in enumerate(self.strokes):
            start = (si / len(self.strokes)) * 0.85
            local = (p - start) / 0.15
            if local <= 0: continue
            local = min(local, 1.0)
            frm = st[4]
            if local > frm:
                seg = math.hypot(st[2] - st[0], st[3] - st[1])
                nsteps = max(1, int((local - frm) * seg / 6))
                for k in range(nsteps + 1):
                    q = frm + (local - frm) * k / nsteps
                    self.stamp_at(st[0] + (st[2] - st[0]) * q,
                                  st[1] + (st[3] - st[1]) * q)
                st[4] = local
            if local < 1.0:
                heads.append((st[0] + (st[2] - st[0]) * local,
                              st[1] + (st[3] - st[1]) * local))
        return heads


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--still", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--duration", type=float, required=True)
    ap.add_argument("--dust-pattern", default="v_bt")
    ap.add_argument("--dust-seed", type=int, default=8102)
    ap.add_argument("--dust-radius", type=int, default=0)
    ap.add_argument("--dust-end", type=float, default=0.0,
                    help="0 = auto: 3.0s, or 30%% of duration when duration < 10s")
    ap.add_argument("--clean-pattern", default="h_lr")
    ap.add_argument("--clean-seed", type=int, default=8002)
    ap.add_argument("--clean-radius", type=int, default=132)
    ap.add_argument("--clean-end", type=float, default=0.0,
                    help="0 = auto: 92%% of duration")
    a = ap.parse_args()

    dust_end = a.dust_end if a.dust_end > 0 else (3.0 if a.duration >= 10.0
                                                 else 0.30 * a.duration)
    clean_end = a.clean_end if a.clean_end > 0 else 0.92 * a.duration
    clean_start = dust_end
    # Dirty layer uses the clean seed + same draw order as brush_render.py,
    # so the dusty state matches the approved scene-2 render.
    rng = np.random.default_rng(a.clean_seed)
    rng_dust = np.random.default_rng(a.dust_seed)
    R_clean = a.clean_radius
    R_dust = a.dust_radius if a.dust_radius else int(rng_dust.integers(120, 181))
    frames = int(round(a.duration * FPS))

    img = Image.open(a.still).convert("RGB")
    iw, ih = img.size
    s = max(W / iw, H / ih)
    img = img.resize((round(iw * s), round(ih * s)), Image.LANCZOS)
    x0, y0 = (img.size[0] - W) // 2, (img.size[1] - H) // 2
    img = img.crop((x0, y0, x0 + W, y0 + H))
    clean = np.asarray(img).astype(np.float32)
    dirty = build_dirty(img, rng)

    dust = PhaseBrush(a.dust_pattern, R_dust, sweep_len=dust_end,
                      seed=a.dust_seed, flip=bool(a.dust_seed % 2))
    cleanb = PhaseBrush(a.clean_pattern, R_clean,
                        sweep_len=clean_end - clean_start,
                        seed=a.clean_seed, flip=bool(a.clean_seed % 2))

    particles = []
    out_dir = os.path.dirname(os.path.abspath(a.out))
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgb24",
         "-s", f"{W}x{H}", "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264",
         "-pix_fmt", "yuv420p", "-preset", "medium", "-crf", "20",
         "-movflags", "+faststart", a.out],
        stdin=subprocess.PIPE)

    dust_done = False
    clean_done = False
    for f in range(frames):
        t = f / FPS
        heads = []
        if t <= dust_end:
            for h in dust.advance(t):
                heads.append((h, R_dust))
        elif not dust_done:
            dust.advance(dust_end)  # finalize: dust mask fully applied
            dust_done = True
        if clean_start <= t <= clean_end:
            for h in cleanb.advance(t - clean_start):
                heads.append((h, R_clean))
        elif t > clean_end and not clean_done:
            cleanb.advance(clean_end - clean_start)  # finalize: fully clean
            clean_done = True
        # spawn dust at BOTH phase heads (same particle recipe as v2)
        per_head = 9 if len(heads) <= 1 else 3
        for (bx, by), Rb in heads:
            for _ in range(per_head):
                ang = rng.uniform(0, 2 * math.pi)
                particles.append([bx + math.cos(ang) * Rb * 0.55, by + math.sin(ang) * Rb * 0.55,
                                  rng.uniform(-14, 14), rng.uniform(-46, -18),
                                  0.0, rng.uniform(0.4, 0.9), rng.uniform(1.2, 3.0)])
        dm = dust.mask[..., None]
        cm = cleanb.mask[..., None]
        dusted = clean * (1 - dm) + dirty * dm
        frame = dusted * (1 - cm) + clean * cm
        # animated grain wherever currently dusty and not yet cleaned
        grain_w = (dust.mask * (1 - cleanb.mask))[..., None]
        frame = frame + rng.normal(0, 16, (H, W, 1)).astype(np.float32) * grain_w
        alive = []
        for p in particles[-700:]:
            p[4] += 1 / FPS
            if p[4] >= p[5]: continue
            p[0] += p[2] / FPS; p[1] += p[3] / FPS
            alive.append(p)
            al = (1 - p[4] / p[5]) * 0.5
            r = p[6]
            xa, ya = int(p[0] - r * 3), int(p[1] - r * 3)
            xb, yb = int(p[0] + r * 3), int(p[1] + r * 3)
            if xb < 0 or yb < 0 or xa >= W or ya >= H: continue
            xa, ya = max(0, xa), max(0, ya); xb, yb = min(W, xb), min(H, yb)
            gy, gx = np.mgrid[ya:yb, xa:xb]
            g = np.exp(-((gx - p[0]) ** 2 + (gy - p[1]) ** 2) / (2 * (r * 1.6) ** 2)) * al * 190
            frame[ya:yb, xa:xb] += g[..., None]
        particles = alive
        proc.stdin.write(np.clip(frame, 0, 255).astype(np.uint8).tobytes())
    proc.stdin.close(); proc.wait()
    print(f"DONE {a.out} frames={frames} dur={frames / FPS:.3f}s "
          f"dust={a.dust_pattern}/seed{a.dust_seed}/R{R_dust} "
          f"clean={a.clean_pattern}/seed{a.clean_seed}/R{R_clean}")

if __name__ == "__main__":
    main()
