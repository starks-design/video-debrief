#!/usr/bin/env python3
"""Video Debrief — End-to-End Orchestrator.

Pipeline: yt-dlp → ffmpeg Scene-Detection → whisper.cpp + oMLX-Vision
→ Insight-Extraction → HTML-Report + stdout Markdown.

Usage:
    python3 debrief.py <url-or-path> [options]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import signal as _signal
import subprocess
import sys
import tempfile
import time
from datetime import date
from pathlib import Path

# ── SIGTERM handler: write result_partial.json before exit ──
_PARTIAL_SAVE_CALLBACK = None


def _sigterm_handler(signum, frame):
    if _PARTIAL_SAVE_CALLBACK:
        try:
            _PARTIAL_SAVE_CALLBACK()
        except Exception:
            pass
    raise SystemExit(0)


_signal.signal(_signal.SIGTERM, _sigterm_handler)

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

from config import load_config, get_api_key, language_name  # noqa: E402
from scene_frames import extract_all as extract_scene_frames  # noqa: E402
from describe_local import describe_all  # noqa: E402
from whisper_local import transcribe_auto  # noqa: E402
from summarize import generate_summary  # noqa: E402
from render_report import render_report  # noqa: E402

_CFG = load_config()
PERSISTENT_OUTPUT = Path(_CFG["output_dir"]).expanduser()


def _write_progress(work: Path, step: str, pct: float) -> None:
    """Write live pipeline progress so the dashboard worker can mirror it into
    the inbox store. One small file, overwritten on each step / vision frame."""
    try:
        (work / "progress.json").write_text(
            json.dumps({"step": step, "progress_pct": round(pct, 1), "updated_at": time.time()}),
            encoding="utf-8",
        )
    except Exception:
        pass


def _make_slug(source: str) -> str:
    today = date.today().isoformat()
    if is_url(source):
        yt_match = re.search(r"(?:v=|youtu\.be/)([a-zA-Z0-9_-]{11})", source)
        raw = yt_match.group(1) if yt_match else source.rsplit("/", 1)[-1].split("?")[0]
    else:
        p = Path(source).resolve()
        raw = p.parent.name if p.stem == "video" else p.stem
    clean = re.sub(r"[^\w\-]", "-", raw).strip("-")[:60]
    return f"{today}-{clean}" if clean else today


def is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "youtu.be/", "www."))


def download_video(source: str, work_dir: Path) -> Path:
    """yt-dlp Download. Bei lokalem Pfad: Datei kopieren bzw. zurückgeben."""
    if not is_url(source):
        p = Path(source).expanduser().resolve()
        if not p.exists():
            raise SystemExit(f"Local file not found: {p}")
        return p

    if shutil.which("yt-dlp") is None:
        raise SystemExit("yt-dlp not in PATH. brew install yt-dlp")

    work_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        "yt-dlp",
        "--no-playlist",
        "--no-warnings",
        "-f", "bv*[height<=720]+ba/b[height<=720]/b",
        "-o", str(work_dir / "video.%(ext)s"),
        source,
    ]
    print(f"[debrief] downloading via yt-dlp…", file=sys.stderr)
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"yt-dlp failed: {res.stderr.strip()[:300]}")

    # find what yt-dlp wrote
    candidates = sorted(work_dir.glob("video.*"))
    candidates = [c for c in candidates if c.suffix.lower() in (".mkv", ".mp4", ".webm")]
    if not candidates:
        raise SystemExit(f"no video file produced under {work_dir}")
    return candidates[0]


def get_video_metadata(url_or_path: str) -> dict:
    """yt-dlp Metadata für URLs, ffprobe für lokale Files."""
    if is_url(url_or_path) and shutil.which("yt-dlp"):
        cmd = ["yt-dlp", "--no-playlist", "--no-warnings", "--dump-json", url_or_path]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if res.returncode == 0:
            try:
                data = json.loads(res.stdout)
                return {
                    "title": data.get("title"),
                    "uploader": data.get("uploader"),
                    "duration": data.get("duration"),
                    "url": url_or_path,
                }
            except json.JSONDecodeError:
                pass
    return {"url": url_or_path}


INSIGHTS_PROMPT = (
    "Analyze this video transcript. Extract the 10-15 MOST IMPORTANT insights, "
    "facts, numbers, conclusions or key statements.\n\n"
    "For each insight return a JSON object with:\n"
    "- \"ts\": timestamp in seconds (float) from the transcript\n"
    "- \"text\": the insight in max 8 words, written in {lang_name}\n\n"
    "Answer ONLY with a JSON array, no markdown, no explanation.\n"
    "Focus: concrete numbers/stats, comparisons, conclusions, recommendations, "
    "surprising facts, named products/tools, deadlines.\n"
    "Ignore: filler words, greetings, self-references, transitions.\n\n"
    "Transcript:\n{transcript}"
)


def extract_insights(transcript: dict, model: str | None = None) -> list[dict]:
    import urllib.request
    import urllib.error

    if not _CFG["insights"].get("enabled", True):
        return []
    model = model or _CFG["insights"]["model"]
    segments = transcript.get("segments", [])
    if not segments:
        return []

    transcript_text = "\n".join(
        f"[{s['start']:.1f}s] {s['text']}" for s in segments
    )
    # cap to stay within the local model's context (Gemma) — großzügiger als die
    # alten 12k, damit Insights aus dem GANZEN Video kommen, nicht nur dem Anfang
    if len(transcript_text) > 40000:
        transcript_text = transcript_text[:40000] + "\n[... truncated]"

    prompt = INSIGHTS_PROMPT.format(transcript=transcript_text, lang_name=language_name(_CFG))
    payload = json.dumps({
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 1500,
        "temperature": 0.1,
    }).encode("utf-8")

    headers = {"Content-Type": "application/json"}
    api_key = get_api_key(_CFG["insights"]["api_key_env"])
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    req = urllib.request.Request(_CFG["insights"]["base_url"], data=payload, headers=headers, method="POST")
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            raw = json.loads(resp.read().decode("utf-8"))
        content = raw["choices"][0]["message"]["content"].strip()
    except Exception as exc:
        print(f"[insights] extraction failed: {exc}", file=sys.stderr)
        return []

    latency = time.time() - t0
    print(f"[insights] extracted in {latency:.1f}s via {model}", file=sys.stderr)

    # parse JSON from response (may be wrapped in ```json ... ```)
    content = re.sub(r"^```(?:json)?\s*", "", content)
    content = re.sub(r"\s*```$", "", content)
    try:
        insights = json.loads(content)
        if isinstance(insights, list):
            return [{"ts": float(i.get("ts", 0)), "text": str(i.get("text", ""))}
                    for i in insights if i.get("text")]
    except (json.JSONDecodeError, ValueError):
        print(f"[insights] JSON parse failed: {content[:200]}", file=sys.stderr)
    return []


def main() -> int:
    ap = argparse.ArgumentParser(description="Video Debrief: lokale Video-Tiefenanalyse")
    ap.add_argument("source", type=str, help="URL or local path")
    ap.add_argument("--context-window", type=int, default=2,
                    help="Wie viele vorherige Frame-Beschreibungen als Text-Context "
                         "mitgeben (Drift-Vermeidung). 0 = isoliert. Default: 2")
    ap.add_argument("--scene-threshold", type=float, default=0.3)
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--heartbeat-seconds", type=float, default=10.0)
    ap.add_argument("--out-dir", type=str, default=None)
    ap.add_argument("--no-vision", action="store_true")
    ap.add_argument("--no-whisper", action="store_true")
    ap.add_argument("--whisper-language", type=str, default="auto")
    ap.add_argument("--resume", action="store_true", help="Resume: nur fehlende Vision-Frames nachholen")
    args = ap.parse_args()

    if args.out_dir:
        work = Path(args.out_dir).expanduser().resolve()
    else:
        slug = _make_slug(args.source)
        work = PERSISTENT_OUTPUT / slug
    work.mkdir(parents=True, exist_ok=True)
    print(f"[debrief] work dir: {work}", file=sys.stderr)

    t_total = time.time()
    result_file = work / "debrief_result.json"

    def _save_incremental(**updates):
        data = {}
        if result_file.exists():
            try:
                data = json.loads(result_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        data.update(updates)
        data["total_time_s"] = round(time.time() - t_total, 2)
        result_file.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")

    # ── RESUME MODE: nur fehlende Vision-Frames nachholen ──
    if args.resume and result_file.exists():
        from describe_local import DEFAULT_MODEL
        from scene_frames import extract_frame, get_duration_seconds

        existing = json.loads(result_file.read_text(encoding="utf-8"))
        all_frame_ts = [f["timestamp"] for f in existing.get("frames", {}).get("frames", [])]
        existing_vision_ts = {int(f["timestamp"]) for f in existing.get("vision", {}).get("frames", [])}

        missing_ts = [ts for ts in all_frame_ts if int(ts) not in existing_vision_ts]
        print(f"[debrief] RESUME: {len(existing_vision_ts)} vorhanden, {len(missing_ts)} fehlend von {len(all_frame_ts)}", file=sys.stderr)

        if not missing_ts:
            print(f"[debrief] nichts nachzuholen", file=sys.stderr)
            return 0

        # Video finden
        video_candidates = sorted(work.glob("video.*"))
        if not video_candidates:
            video_path = download_video(args.source, work)
        else:
            video_path = video_candidates[0]

        # Nur fehlende Frames extrahieren
        frames_dir = work / "frames"
        frames_dir.mkdir(exist_ok=True)
        missing_frames = []
        for idx, ts in enumerate(missing_ts):
            out_path = frames_dir / f"resume_{idx:04d}_t{int(ts*1000):07d}.jpg"
            if extract_frame(video_path, ts, out_path):
                missing_frames.append({"index": idx, "timestamp": round(ts, 3), "path": str(out_path), "filename": out_path.name})
        print(f"[debrief] {len(missing_frames)} fehlende Frames extrahiert", file=sys.stderr)

        # Nur fehlende beschreiben
        if missing_frames:
            vision_new = describe_all(DEFAULT_MODEL, missing_frames, context_window=args.context_window, save_dir=work)

            # Merge: alte + neue Vision-Frames, sortiert nach Timestamp
            all_vision = existing.get("vision", {}).get("frames", []) + vision_new.get("frames", [])
            all_vision.sort(key=lambda f: f["timestamp"])

            merged_vision = {
                "model": vision_new.get("model", existing.get("vision", {}).get("model", "")),
                "context_window": args.context_window,
                "total_time_s": round(existing.get("vision", {}).get("total_time_s", 0) + vision_new.get("total_time_s", 0), 3),
                "frame_count": len(all_vision),
                "avg_latency_s": round(sum(f.get("latency_s", 0) for f in all_vision) / max(len(all_vision), 1), 3),
                "frames": all_vision,
            }
            _save_incremental(vision=merged_vision)

        # Cleanup resume-Frames
        for f in frames_dir.glob("resume_*.jpg"):
            f.unlink()
        if not list(frames_dir.iterdir()):
            frames_dir.rmdir()

        print(f"[debrief] RESUME fertig: {len(all_vision)} Vision-Frames total", file=sys.stderr)
        return 0

    # ── NORMAL MODE ──

    # --- 1. Download / locate video ---
    _write_progress(work, "download", 0)
    meta = get_video_metadata(args.source) if is_url(args.source) else {"url": args.source}
    video_path = download_video(args.source, work)
    _save_incremental(meta=meta)

    # --- 2. Scene-Detection + Frame-Extract (skip bei --no-vision) ---
    _write_progress(work, "frames", 0)
    frames_data = {"frames": [], "duration": 0, "threshold": 0, "scene_changes_detected": 0}
    if not args.no_vision:
        frames_data = extract_scene_frames(
            video_path, work / "frames",
            threshold=args.scene_threshold,
            heartbeat_seconds=args.heartbeat_seconds,
            max_frames=args.max_frames,
        )
    else:
        print("[debrief] --no-vision: Scene-Detection + Frame-Extract übersprungen", file=sys.stderr)
        from scene_frames import get_duration_seconds
        frames_data["duration"] = get_duration_seconds(video_path)
    _save_incremental(frames=frames_data)

    # --- 3. Whisper ---
    _write_progress(work, "whisper", 0)
    transcript = {"segments": [], "segment_count": 0, "model": "n/a", "latency_s": 0}
    if not args.no_whisper:
        transcript = transcribe_auto(args.source, video_path, work, language=args.whisper_language)
    _save_incremental(transcript=transcript)

    # --- 4. Vision (skip bei --no-vision) ---
    _write_progress(work, "vision", 0)
    vision = {"frames": [], "model": "n/a", "total_time_s": 0, "avg_latency_s": 0}
    if not args.no_vision:
        from describe_local import DEFAULT_MODEL
        model_id = DEFAULT_MODEL
        # Register partial-save callback so SIGTERM writes progress to result_partial.json
        global _PARTIAL_SAVE_CALLBACK
        _partial_file = work / "result_partial.json"
        _frame_count_total = len(frames_data.get("frames", []))

        def _save_partial():
            done = len(vision.get("frames", []))
            pct = round(done / max(_frame_count_total, 1) * 100, 1)
            _partial_file.write_text(json.dumps({
                "step": "vision",
                "vision_frames_done": done,
                "vision_frames_total": _frame_count_total,
                "progress_pct": pct,
            }, indent=2), encoding="utf-8")

        def _vision_progress(done: int, total: int):
            _write_progress(work, "vision", done / max(total, 1) * 100)

        _PARTIAL_SAVE_CALLBACK = _save_partial
        vision = describe_all(model_id, frames_data["frames"], context_window=args.context_window, save_dir=work, progress_cb=_vision_progress)
        _PARTIAL_SAVE_CALLBACK = None  # vision complete — no partial needed
    else:
        print("[debrief] --no-vision: Vision-Beschreibung übersprungen", file=sys.stderr)
    # --- 5. Insights (lokales LLM) ---
    insights = []
    try:
        insights = extract_insights(transcript)
    except Exception as exc:  # noqa: BLE001
        print(f"[insights] übersprungen: {exc}", file=sys.stderr)
    _save_incremental(vision=vision, insights=insights)

    # --- 6. Summary (host-agent → SUMMARY_TODO.md, oder local-llm) ---
    _write_progress(work, "summary", 0)
    meta_for_summary = {**meta, "duration": meta.get("duration") or frames_data.get("duration", 0)}
    summary_html, tags = generate_summary(
        {"meta": meta_for_summary, "transcript": transcript, "vision": vision, "insights": insights},
        _CFG, work,
    )
    if summary_html or tags:
        _save_incremental(summary=summary_html, tags=tags)

    # --- 7. HTML-Report ---
    _cleanup = _CFG.get("cleanup", {})
    html = render_report(
        meta_for_summary, frames_data, transcript, vision,
        round(time.time() - t_total, 2), work,
        summary=summary_html, insights=insights,
        branding=_CFG["branding"]["footer"],
        embed_local=not _cleanup.get("delete_video", True),
        language=_CFG.get("language", "en"),
    )
    (work / "report.html").write_text(html, encoding="utf-8")

    # --- 8. Cleanup: Video + Frames löschen (Privacy + Speicher). Report bleibt. ---
    import shutil as _sh
    if _cleanup.get("delete_frames", True):
        fdir = work / "frames"
        if fdir.exists():
            _sh.rmtree(fdir, ignore_errors=True)
        transients = (list(work.glob("audio.*")) + list(work.glob("cap*.vtt"))
                      + [work / "progress.json", work / "result_partial.json",
                         work / "vision_checkpoint.json"])
        for a in transients:
            try:
                a.unlink()
            except OSError:
                pass
    if _cleanup.get("delete_video", True):
        for v in work.glob("video.*"):
            try:
                v.unlink()
            except OSError:
                pass
        print("[debrief] cleanup: Video + Frames gelöscht (nur Report bleibt)", file=sys.stderr)

    _write_progress(work, "done", 100)
    print(f"[debrief] report: {work / 'report.html'}", file=sys.stderr)
    print(f"\n---\n**Output:** `{work}`", file=sys.stderr)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
