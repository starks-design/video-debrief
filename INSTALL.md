# Video Debrief — Setup (for your agent)

*🇩🇪 Deutsche Version: [INSTALL.de.md](INSTALL.de.md)*

**Drop this file into your agent** (Claude Code, Cursor, …) with the request:
*"Set up Video Debrief following these instructions."* The agent works through the
steps, checks your system, and writes a `debrief.config.json` at the end.

> Human, or an agent without patience for automation? The same steps are in
> `README.md` → "Manual setup".

---

## Instructions for the agent

You are setting up Video Debrief. Work through these steps in order, only ask the
user where it explicitly says "**ask**" below, and confirm installs before running
them.

### 1. Detect the operating system
Determine the OS (`uname -s`, on Windows `$OS`/PowerShell). Pick the matching
package manager: macOS → `brew`, Debian/Ubuntu → `apt` + `pipx`,
Fedora → `dnf`, Windows → `winget`/`choco`.

### 2. Check base tools + install if needed
Check `ffmpeg`, `ffprobe`, `yt-dlp` (`command -v` / `where`). If something's
missing, **propose the OS-appropriate install command and run it after confirmation.**

### 3. Choose the transcript engine
- Check whether `whisper-cli` (whisper.cpp) is on the `PATH`.
- Check whether `faster-whisper` is installed as a Python package.
- **Decision logic:**
  - whisper.cpp present → `whisper.mode = "auto"`, `whisper.bin = "whisper-cli"`, ask for the ggml model path or offer to download one → `whisper.model_path`.
  - else faster-whisper present (or installable) → `whisper.mode = "faster-whisper"`, `whisper.model_path = "large-v3"`.
  - else (URL videos with captions only) → `whisper.mode = "captions"`, and note that local files then get no transcript.

### 4. Find the local LLM backend
Probe the common endpoints and list the available models:
```bash
curl -s http://localhost:11434/api/tags        # Ollama
curl -s http://localhost:1234/v1/models          # LM Studio
curl -s http://localhost:8000/v1/models          # oMLX
```
Take the first responding backend. Set `vision.base_url` (…/v1/chat/completions)
and `vision.backend` (`ollama` | `lmstudio` | `omlx`) accordingly.
If the backend needs a key: put it in an ENV variable and set the **name** of that
variable in `vision.api_key_env` (never the key itself in the file).

### 5. Choose the vision model — with fallback
Pick a **vision-capable** model from the model list and set it as `vision.model`.
**Fallback chain (matching the backend):**
1. an already-installed Qwen-VL model,
2. else an installed Gemma-Vision model,
3. else recommend the user pull one (name a concrete tag **verified against the
   backend's live model list** — don't guess tags).

Set `insights` to the same backend/model by default (or a light text model if
available).

### 6. Relevance block — **ask** the user
Ask verbatim:

> "Should Video Debrief add a **relevance block for your context** to every
> summary — i.e. rate what the video means *for you / your business*? (y/n)"

- **yes** → ask: "Describe in 1–3 sentences what you work on / what interests you." → into `relevance.profile`, `relevance.enabled = true`.
- **no** → `relevance.enabled = false` (summary stays neutral).

### 7. Write config + smoke test
- Write `debrief.config.json` (base: `debrief.config.example.json`, with the detected values).
- Run a smoke test:
  ```bash
  python3 scripts/debrief.py "samples/30s-demo.mp4"
  ```
- Expected: `debrief_result.json` contains `transcript` + `vision`, and
  `report.html` was written. If `summary.engine = host-agent`, you'll find a
  `SUMMARY_TODO.md` — write the summary and insert it into the report.
- Open `report.html` and report back to the user: done.

If a step fails, **stop and report the concrete problem** instead of guessing.
