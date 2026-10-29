THE MAN WHO GOES QUIET — RENDER KIT (46 scenes, 7:15 voiceover)

WHAT'S INSIDE
- build/img/scene_01.png ... scene_46.png   (all stills, locked ink style)
- plan.json                                  (scene timings + dust/clean pattern, radius, seed per scene — already assigned)
- audio/voiceover.mp3                        (his voiceover)
- brush_render_v3.py                         (two-phase brush renderer: dust-in, then brush-clean)
- render_all.py                              (renders every scene clip into build/clips/)
- make_delivery.py                           (loudnorm + assembles delivery parts into delivery720/)
- scenes_spec.md                             (scene list with narration + visual per scene)

REQUIREMENTS
- Python 3 with:  pip install pillow numpy
- ffmpeg on PATH  (check: ffmpeg -version)

COMMANDS (run from this folder)
1) Convert the voiceover:
   ffmpeg -i audio/voiceover.mp3 -ac 1 -ar 48000 audio/voiceover.wav

2) Render all scene clips (resumable — if it stops, run it again; finished scenes are skipped):
   python3 render_all.py
   Optional range:  python3 render_all.py 1 23

3) Build the delivery parts (loudnorms the voiceover once, muxes audio, parts stay under ~90MB):
   python3 make_delivery.py
   Output: delivery720/quietman_brush720_part01_v1.mp4 ... + delivery_manifest.txt

OPTIONAL — join the parts into one full video:
   cd delivery720
   printf "file '%s'\n" quietman_brush720_part*_v1.mp4 > list.txt
   ffmpeg -f concat -safe 0 -i list.txt -c copy stoic_vampire_quiet_man_full_v1_720p.mp4

OUTPUT FORMAT (locked)
1280x720, 30fps, H.264 yuv420p + AAC 192k, +faststart. Voiceover only — no music.
Scenes join back-to-back, no black gaps. Every clip matches its narration window (hard sync).
