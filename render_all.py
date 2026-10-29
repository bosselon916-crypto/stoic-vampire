#!/usr/bin/env python3
"""Resumable scene renderer for the two-phase build: loops plan.json,
skips clips that already probe within ±0.05s of their window, renders the
rest with brush_render_v3.py using per-scene dust/clean params."""
import json, os, subprocess, sys

WORK = os.path.dirname(os.path.abspath(__file__))
os.makedirs(f"{WORK}/build/clips", exist_ok=True)
plan = json.load(open(f"{WORK}/plan.json"))

def probe_dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration", "-of", "csv=p=0", path],
                       capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except Exception:
        return None

lo = int(sys.argv[1]) if len(sys.argv) > 1 else 1
hi = int(sys.argv[2]) if len(sys.argv) > 2 else 999
done, failed = 0, []
for sc in plan:
    n = sc["n"]
    if n < lo or n > hi:
        continue
    still = f"{WORK}/build/img/scene_{n:02d}.png"
    out = f"{WORK}/build/clips/scene_{n:02d}.mp4"
    d = probe_dur(out) if os.path.exists(out) else None
    if d is not None and abs(d - sc["dur"]) <= 0.05:
        done += 1
        continue
    if os.path.exists(out):
        os.remove(out)
    if not os.path.exists(still):
        failed.append((n, "missing still"))
        continue
    r = subprocess.run(["python3", f"{WORK}/brush_render_v3.py",
                        "--still", still, "--out", out,
                        "--duration", str(sc["dur"]),
                        "--dust-pattern", sc["dust_pattern"],
                        "--dust-seed", str(sc["dust_seed"]),
                        "--dust-radius", str(sc["dust_radius"]),
                        "--clean-pattern", sc["clean_pattern"],
                        "--clean-seed", str(sc["clean_seed"]),
                        "--clean-radius", str(sc["clean_radius"])],
                       capture_output=True, text=True)
    if r.returncode != 0:
        failed.append((n, r.stderr[-400:]))
        print(f"scene {n}: FAILED\n{r.stderr[-400:]}", flush=True)
    else:
        done += 1
        print(f"scene {n}: ok ({done})", flush=True)
print(f"RENDER PASS COMPLETE done={done} failed={failed}")
