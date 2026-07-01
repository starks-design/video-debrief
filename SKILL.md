---
name: debrief
description: Turns a video (URL or local file) fully locally into a summary plus a searchable timeline built from transcript and image descriptions. Scene detection (ffmpeg) finds every cut, a local vision model describes each frame including OCR, Whisper transcribes the audio. No cloud upload. Trigger on /debrief <url-or-path> or when a video should be analyzed in depth.
argument-hint: "<video-url-or-path>"
allowed-tools: Bash, Read, Write
license: Apache-2.0
user-invocable: true
---

# /debrief — deep video analysis, fully local

Skip the whole video. Video Debrief turns a clip into a **summary** plus a clickable
**timeline** (what's said + what's on screen) in minutes. Everything runs on your
own machine — no upload, no forced API.

## Requirements

Set up once — drop `INSTALL.md` into your agent; it checks your system and writes
the `debrief.config.json`. Short version:

- `ffmpeg`, `ffprobe`, `yt-dlp` on the `PATH`
- A local LLM with an OpenAI-compatible API (Ollama / LM Studio / oMLX) for the
  image description — endpoint + model go in the config
- Transcript: auto-captions (yt-dlp), whisper.cpp **or** faster-whisper
- `debrief.config.json` (created from `debrief.config.example.json`)

## What the agent should do on /debrief

1. **Take the URL/path** from the prompt.
2. **Check the config** — does `debrief.config.json` exist? If not → work through
   `INSTALL.md` (setup), otherwise don't ask again.
3. **Run the pipeline:**
   ```bash
   python3 scripts/debrief.py "<URL_OR_PATH>"
   ```
   This does: download/locate → scene detection → transcript → vision description
   → insights → writes `debrief_result.json` + `report.html` to the output folder.
4. **Write the summary (only if `summary.engine` = `host-agent`):** a
   `SUMMARY_TODO.md` will be in the output folder with a ready-made prompt. Read
   `debrief_result.json`, write the summary following the prompt, and replace the
   placeholder block `<section id="summary">…</section>` in `report.html`.
   (With `summary.engine` = `local-llm` the tool does the summary itself.)
5. **Open the report:**
   ```bash
   open "<OUTPUT>/report.html"   # macOS · Linux: xdg-open · Windows: start
   ```

## Relevance block (optional)

If `relevance.enabled` is turned on during setup, the summary adds a
"relevance for you" block that rates the video against the profile stored during
setup. **Off** by default — then the summary stays neutral.

## Useful flags

```bash
python3 scripts/debrief.py "<src>" --no-vision        # transcript only
python3 scripts/debrief.py "<src>" --no-whisper       # image analysis only
python3 scripts/debrief.py "<src>" --scene-threshold 0.2   # more frames (cut-sparse videos)
python3 scripts/debrief.py "<src>" --out-dir ./my-report
python3 scripts/debrief.py "<src>" --resume           # backfill missing vision frames
```

## Output

| File | Contents |
|------|----------|
| `report.html` | video player + clickable transcript timeline + insight markers + summary |
| `debrief_result.json` | raw data: transcript segments, frame descriptions, insights |
| `SUMMARY_TODO.md` | (host-agent mode only) prompt for the summary |

## Privacy — cleans up after itself

After analysis, Video Debrief deletes the downloaded video and the frame images
again (`cleanup.delete_video` / `delete_frames`, default on) — only `report.html` +
`debrief_result.json` stay. YouTube videos don't need a local file for the report:
over `http(s)` inline with transcript sync, via `file://` as a thumbnail with
deep links to the respective spot.

Details on setup, models and troubleshooting: `README.md`.
