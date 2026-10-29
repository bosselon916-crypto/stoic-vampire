#!/usr/bin/env python3
"""Delivery assembly for stoic vampire video #2 (two-phase build):
1) loudnorm the full voiceover ONCE,
2) re-encode each scene clip at crf 24 (1280x720),
3) greedily group consecutive scenes into parts with video bytes <= 85MB,
4) mux each part with its loudnormed audio slice (AAC 192k, +faststart),
5) write delivery_manifest.txt.
Masters (build/clips, crf 20) stay untouched."""
import json, os, subprocess, sys

ROOT = os.path.dirname(os.path.abspath(__file__))
CLIPS = os.path.join(ROOT, "build/clips")
DL = os.path.join(ROOT, "delivery720")
SC = os.path.join(DL, "scenes")
os.makedirs(SC, exist_ok=True)
VO_SRC = os.path.join(ROOT, "audio/voiceover.wav")
VO_LOUD = os.path.join(ROOT, "build/vo_loud_full.wav")
CAP = 85 * 1024 * 1024

plan = json.load(open(os.path.join(ROOT, "plan.json")))

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        print("FAIL:", " ".join(cmd), "\n", r.stderr[-800:], flush=True)
        sys.exit(1)

os.makedirs(os.path.join(ROOT, "build"), exist_ok=True)

# 1) ensure WAV source exists, then loudnorm once
mp3_src = os.path.join(ROOT, "audio/voiceover.mp3")
if not os.path.exists(VO_SRC) and os.path.exists(mp3_src):
    print("converting voiceover.mp3 to 48kHz WAV...", flush=True)
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", mp3_src,
         "-ac", "1", "-ar", "48000", VO_SRC])

if not os.path.exists(VO_LOUD):
    run(["ffmpeg", "-y", "-loglevel", "error", "-i", VO_SRC,
         "-af", "loudnorm=I=-16:TP=-1.5:LRA=11", "-ar", "48000", VO_LOUD])
    print("loudnorm done", flush=True)

# 2) crf24 delivery encode per scene (video only), resumable
sizes = {}
for sc in plan:
    n = sc["n"]
    src = os.path.join(CLIPS, f"scene_{n:02d}.mp4")
    dst = os.path.join(SC, f"scene_{n:02d}.mp4")
    if not (os.path.exists(dst) and os.path.getsize(dst) > 10000):
        run(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-an",
             "-c:v", "libx264", "-pix_fmt", "yuv420p", "-preset", "medium",
             "-crf", "24", "-r", "30", dst])
    sizes[n] = os.path.getsize(dst)
    if n % 25 == 0:
        print(f"delivery-encoded {n}/{len(plan)}", flush=True)
print("all scenes delivery-encoded", flush=True)

# 3) greedy grouping by video bytes
parts, cur, cur_bytes = [], [], 0
for sc in plan:
    n = sc["n"]
    if cur and cur_bytes + sizes[n] > CAP:
        parts.append(cur); cur, cur_bytes = [], 0
    cur.append(sc); cur_bytes += sizes[n]
if cur:
    parts.append(cur)
print(f"parts: {len(parts)}", flush=True)

# 4) build parts
manifest = [f"Stoic Vampire — The Man Who Goes Quiet (two-phase brush) — delivery parts, {len(parts)} parts, 720p crf24"]
total_dur = 0.0
for i, grp in enumerate(parts, 1):
    lst = os.path.join(DL, f"concat_{i:02d}.txt")
    with open(lst, "w") as f:
        for sc in grp:
            f.write(f"file '{SC}/scene_{sc['n']:02d}.mp4'\n")
    start, end = grp[0]["start"], grp[-1]["end"]
    dur = end - start
    total_dur += dur
    out = os.path.join(DL, f"quietman_brush720_part{i:02d}_v1.mp4")
    run(["ffmpeg", "-y", "-loglevel", "error",
         "-f", "concat", "-safe", "0", "-i", lst,
         "-ss", f"{start}", "-t", f"{dur}", "-i", VO_LOUD,
         "-map", "0:v", "-map", "1:a", "-c:v", "copy", "-c:a", "aac",
         "-b:a", "192k", "-movflags", "+faststart", out])
    mb = os.path.getsize(out) / 1048576
    manifest.append(f"part {i:02d} | scenes {grp[0]['n']:02d}-{grp[-1]['n']:02d} | audio {start:.2f}-{end:.2f} | dur {dur:.2f}s | {mb:.1f} MB | quietman_brush720_part{i:02d}_v1.mp4")
    print(f"part {i:02d} done: scenes {grp[0]['n']}-{grp[-1]['n']}, {mb:.1f} MB", flush=True)

open(os.path.join(DL, "delivery_manifest.txt"), "w").write("\n".join(manifest))
print(f"TOTAL parts={len(parts)} duration={total_dur:.1f}s", flush=True)
print("DELIVERY DONE", flush=True)
