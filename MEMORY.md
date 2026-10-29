# Cloud & Local Video Rendering — Memory & Production Rules

> **MANDATORY AGENT POLICY (STRICT MANUAL CONTROL)**:
> 1. **NEVER auto-start renders on git push**: Workflows must ONLY use `workflow_dispatch:`. The agent's job is ONLY to prepare code/assets and push to GitHub. The USER manually clicks "Run workflow" when ready.
> 2. **NEVER auto-publish CDN releases**: Release publishing is ALWAYS a manual `workflow_dispatch:`. The USER manually triggers the Fastly CDN release after the video render finishes.
> 3. **Single Master File in Release**: In the Fastly CDN release, publish ONLY the final master video (~450–500 MB). Do not clutter the release with raw clips or split parts.

---

### Core Production Rules & Checklist

#### 1. Manual Execution Only (No Auto-Triggers)
- Never add `push:` event triggers to `.github/workflows/`. Only use `workflow_dispatch:`.
- The agent prepares the repository, checks paths, and pushes.
- The user decides when to run the render workflow and when to run the release workflow.

#### 2. Fastly CDN for High-Speed Downloads
- Standard GitHub Actions artifacts (Azure Blob storage) get throttled to ~1 KB/s by ISPs.
- GitHub Releases are served via Fastly Global CDN (`github.com/.../releases/download/...`) at full line speed (25–35 MB/s).
- Keep release assets clean: only attach the single finished master video (`.mp4`).

#### 3. Image Assets (Never Split Folders)
- Never split scene stills across multiple folders (e.g. `render_kit` vs `render_kit 2`).
- All scene stills MUST live in a single folder: `build/img/scene_01.png` ... `scene_N.png`.

#### 4. Python Subprocess Executable
- Never call `subprocess.run(["python3", ...])`.
- Always use `sys.executable`:
  ```python
  subprocess.run([sys.executable, "brush_render_v3.py", ...])
  ```
- In GitHub Actions and virtualenvs, `sys.executable` guarantees access to installed dependencies (`pillow`, `numpy`).

#### 5. Fail-Fast Batch Scripts
- Batch render scripts must exit with code 1 if any scene fails:
  ```python
  if failed:
      sys.exit(1)
  ```
- Prevents silent failures from reporting false-positive green checkmarks.

#### 6. Output Directory & FFmpeg Pipe Safety
- Always call `os.makedirs(os.path.dirname(os.path.abspath(a.out)), exist_ok=True)` before spawning FFmpeg stdin pipes.
- Prevents `BrokenPipeError: [Errno 32] Broken pipe`.
- Always verify `import os` is at the top of the script.

#### 7. Git Buffer for 100MB+ Scene Images
- Before pushing large assets, increase Git's postBuffer:
  ```bash
  git config http.postBuffer 524288000
  git config http.maxRequestBuffer 524288000
  ```
- Prevents `error: RPC failed; HTTP 400 curl 22`.

#### 8. GitHub Actions Quality Gates
- In artifact uploads: always set `if-no-files-found: error`.
- In assembly: verify clip count strictly matches total scenes before running assembly.

#### 9. GitHub Account Requirements
- Use an established/email-verified GitHub account.
- Public repositories have 100% free unlimited Actions minutes.
