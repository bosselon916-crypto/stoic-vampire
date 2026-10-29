# Cloud & Local Video Rendering — Memory & Production Rules

> **Quick Checklist**: Follow these rules on every new video project to guarantee 100% first-pass render success without errors.

---

### 1. Image Assets (Never Split Folders)
- **The Mistake**: Scenes split between `render_kit` and `render_kit 2`.
- **The Rule**: All scene images MUST be named sequentially (`scene_01.png`, `scene_02.png`, ... `scene_N.png`) and live together in a single folder: `build/img/`.

---

### 2. Python Scripts & Subprocesses
- **The Mistake**: Calling `["python3", "script.py"]` inside Python scripts. In GitHub Actions and virtualenvs, `python3` points to system Python where `PIL`/`numpy` are missing.
- **The Rule**: Always use `sys.executable`:
  ```python
  subprocess.run([sys.executable, "brush_render_v3.py", ...])
  ```
- **Error Propagation**: Never let a batch script exit `0` if scenes failed. Always exit `1`:
  ```python
  if failed:
      sys.exit(1)
  ```

---

### 3. Output Directory & FFmpeg Pipes
- **The Mistake**: FFmpeg stdin pipe crashes with `BrokenPipeError: [Errno 32] Broken pipe` if the target output directory does not exist.
- **The Rule**: Always ensure directory exists before starting FFmpeg:
  ```python
  out_dir = os.path.dirname(os.path.abspath(a.out))
  if out_dir:
      os.makedirs(out_dir, exist_ok=True)
  ```
- Always ensure `import os` is at the top of rendering scripts.

---

### 4. Git Large Pushes (Prevent HTTP 400)
- **The Mistake**: Pushing 100 MB+ of scene PNGs fails with `error: RPC failed; HTTP 400 curl 22`.
- **The Rule**: Increase Git's buffer before pushing large asset folders:
  ```bash
  git config http.postBuffer 524288000
  git config http.maxRequestBuffer 524288000
  ```

---

### 5. GitHub Actions Quality Gates
- **Upload Artifact**: Never allow silent missing files. Set `if-no-files-found: error`:
  ```yaml
  uses: actions/upload-artifact@v4
  with:
      name: clips-chunk-${{ matrix.chunk }}
      path: build/clips/*.mp4
      if-no-files-found: error
  ```
- **Clip Count Gate**: Before running the final assembly job, verify the exact clip count matches the total scenes:
  ```yaml
  count=$(ls -1 build/clips/scene_*.mp4 2>/dev/null | wc -l)
  if [ "$count" -lt 46 ]; then
      echo "ERROR: Expected 46 clips, found $count"
      exit 1
  fi
  ```

---

### 6. GitHub Account for Cloud Rendering
- **The Mistake**: Brand new, unverified GitHub accounts block GitHub Actions (`"Actions has been disabled for this user"`).
- **The Rule**: Always use an existing, email-verified GitHub account or complete 2FA setup first. Public repositories have 100% free unlimited Actions minutes.
