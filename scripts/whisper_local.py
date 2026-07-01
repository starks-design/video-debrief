#!/usr/bin/env python3
"""Transcript-Erzeugung — komplett lokal.

Modi (aus Config `whisper.mode`):
  auto            Auto-Captions via yt-dlp (nur URLs), sonst whisper.cpp
  captions        nur Auto-Captions (yt-dlp); keine gefunden -> leeres Transcript
  whisper         whisper.cpp (whisper-cli) + ggml-Modell
  faster-whisper  faster_whisper (pip-Paket), CPU/GPU

Liefert immer dasselbe Segment-Format: {language, model, latency_s,
segment_count, segments:[{start,end,text}]}.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import load_config  # noqa: E402

_CFG = load_config()
WHISPER_BIN = _CFG["whisper"]["bin"]
DEFAULT_MODEL = (
    Path(_CFG["whisper"]["model_path"]).expanduser()
    if _CFG["whisper"]["model_path"]
    else Path.home() / ".debrief" / "models" / "ggml-large-v3-turbo.bin"
)


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "www.", "youtu"))


def extract_audio(video_path: Path, out_wav: Path) -> Path:
    """Mono 16kHz PCM WAV — was whisper-cli will."""
    if shutil.which("ffmpeg") is None:
        raise SystemExit("ffmpeg not found")
    out_wav.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(video_path),
        "-vn", "-acodec", "pcm_s16le", "-ar", "16000", "-ac", "1",
        str(out_wav),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0 or not out_wav.exists():
        raise SystemExit(f"ffmpeg audio extract failed: {res.stderr.strip()}")
    return out_wav


def transcribe(audio_wav: Path, model: Path = DEFAULT_MODEL, language: str = "auto") -> dict:
    """Run whisper-cli, return parsed JSON in unified format."""
    if shutil.which(WHISPER_BIN) is None:
        raise SystemExit(f"{WHISPER_BIN} not in PATH. brew install whisper-cpp")
    if not model.exists():
        raise SystemExit(f"Whisper model missing: {model}")

    out_prefix = audio_wav.with_suffix("")
    out_json = out_prefix.with_suffix(".json")
    if out_json.exists():
        out_json.unlink()

    cmd = [
        WHISPER_BIN,
        "-m", str(model),
        "-f", str(audio_wav),
        "-oj",
        "-of", str(out_prefix),
        "-l", language,
        "--no-prints",
    ]
    t0 = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True)
    latency = time.time() - t0

    if res.returncode != 0:
        raise SystemExit(f"whisper-cli failed: {res.stderr.strip()[:300]}")
    if not out_json.exists():
        raise SystemExit(f"whisper-cli produced no JSON at {out_json}")

    raw = json.loads(out_json.read_text())
    segments = []
    for seg in raw.get("transcription") or []:
        text = (seg.get("text") or "").strip()
        if not text:
            continue
        offsets = seg.get("offsets") or {}
        segments.append({
            "start": round((offsets.get("from") or 0) / 1000.0, 2),
            "end": round((offsets.get("to") or 0) / 1000.0, 2),
            "text": text,
        })

    return {
        "language": (raw.get("result") or {}).get("language", "auto"),
        "model": str(model),
        "latency_s": round(latency, 3),
        "segment_count": len(segments),
        "segments": segments,
    }


def transcribe_video(video_path: Path, work_dir: Path, model: Path = DEFAULT_MODEL, language: str = "auto") -> dict:
    """End-to-end: video → audio → transcript."""
    work_dir.mkdir(parents=True, exist_ok=True)
    wav = work_dir / "audio.wav"
    print(f"[whisper] extracting audio…", file=sys.stderr)
    extract_audio(video_path, wav)
    print(f"[whisper] transcribing with {model.name}…", file=sys.stderr)
    result = transcribe(wav, model=model, language=language)
    print(
        f"[whisper] {result['segment_count']} segments in {result['latency_s']}s ({result['language']})",
        file=sys.stderr,
    )
    return result


# ── Captions-Pfad (yt-dlp Auto-Subs → VTT-Parse) ──

_CUE_RE = re.compile(
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})\s*-->\s*"
    r"(\d{1,2}:\d{2}:\d{2}[.,]\d{1,3}|\d{1,2}:\d{2}[.,]\d{1,3})"
)


def _vtt_ts(s: str) -> float:
    s = s.replace(",", ".")
    parts = s.split(":")
    if len(parts) == 3:
        h, m, rest = parts
    else:
        h, (m, rest) = "0", parts
    sec, _, ms = rest.partition(".")
    return int(h) * 3600 + int(m) * 60 + int(sec) + (int(ms.ljust(3, "0")[:3]) / 1000.0 if ms else 0.0)


def parse_vtt(text: str) -> list[dict]:
    """Parst WEBVTT (inkl. YouTube-Auto-Subs) zu Segmenten. Best-effort:
    entfernt Inline-Tags und dedupliziert die rollenden Wiederholungen."""
    segs: list[dict] = []
    cur: dict | None = None
    for raw in text.splitlines():
        line = raw.rstrip()
        m = _CUE_RE.search(line)
        if m:
            if cur and cur["text"]:
                segs.append(cur)
            cur = {"start": _vtt_ts(m.group(1)), "end": _vtt_ts(m.group(2)), "text": ""}
        elif cur is not None:
            if line.strip() == "":
                if cur["text"]:
                    segs.append(cur)
                cur = None
            elif not line.startswith(("WEBVTT", "NOTE", "Kind:", "Language:")):
                clean = re.sub(r"<[^>]+>", "", line).strip()
                if clean:
                    cur["text"] = (cur["text"] + " " + clean).strip()
    if cur and cur["text"]:
        segs.append(cur)
    # dedupe consecutive identical text (rolling captions)
    out: list[dict] = []
    for s in segs:
        if out and out[-1]["text"] == s["text"]:
            out[-1]["end"] = s["end"]
            continue
        out.append({"start": round(s["start"], 2), "end": round(s["end"], 2), "text": s["text"]})
    return out


def transcribe_captions(url: str, work_dir: Path, language: str = "auto") -> dict | None:
    """Lädt Auto-Captions via yt-dlp und parst sie. None wenn keine gefunden.
    Best-effort: ohne explizite Sprache wird en/de bevorzugt."""
    if shutil.which("yt-dlp") is None:
        return None
    work_dir.mkdir(parents=True, exist_ok=True)
    langs = language if language and language != "auto" else "en.*,de.*"
    cmd = [
        "yt-dlp", "--skip-download", "--write-auto-subs", "--write-subs",
        "--sub-langs", langs, "--sub-format", "vtt", "--convert-subs", "vtt",
        "--no-warnings", "-o", str(work_dir / "cap.%(ext)s"), url,
    ]
    subprocess.run(cmd, capture_output=True, text=True)
    vtts = sorted(work_dir.glob("cap*.vtt"))
    if not vtts:
        return None
    segs = parse_vtt(vtts[0].read_text(encoding="utf-8", errors="ignore"))
    if not segs:
        return None
    return {"language": language, "model": "captions:yt-dlp", "latency_s": 0,
            "segment_count": len(segs), "segments": segs}


def transcribe_faster(video_path: Path, work_dir: Path, language: str = "auto") -> dict:
    """faster-whisper (pip). Modellgröße aus whisper.model_path oder 'large-v3'."""
    try:
        from faster_whisper import WhisperModel  # noqa: PLC0415
    except ImportError:
        raise SystemExit("faster-whisper fehlt: pip install faster-whisper")
    wav = extract_audio(video_path, work_dir / "audio.wav")
    size = _CFG["whisper"].get("model_path") or "large-v3"
    model = WhisperModel(size, device="auto", compute_type="auto")
    t0 = time.time()
    seg_iter, _info = model.transcribe(str(wav), language=None if language == "auto" else language)
    segments = [{"start": round(s.start, 2), "end": round(s.end, 2), "text": s.text.strip()}
                for s in seg_iter if s.text.strip()]
    return {"language": language, "model": f"faster-whisper:{size}",
            "latency_s": round(time.time() - t0, 3),
            "segment_count": len(segments), "segments": segments}


def transcribe_auto(source: str, video_path: Path, work_dir: Path, language: str = "auto") -> dict:
    """Wählt den Transcript-Modus aus der Config. `source` = URL/Pfad (für Captions),
    `video_path` = heruntergeladene Datei (für whisper/faster)."""
    mode = _CFG["whisper"]["mode"]
    work_dir.mkdir(parents=True, exist_ok=True)
    if mode in ("auto", "captions") and _is_url(str(source)):
        cap = transcribe_captions(str(source), work_dir, language)
        if cap and cap["segment_count"] > 0:
            print(f"[whisper] captions: {cap['segment_count']} Segmente", file=sys.stderr)
            return cap
        if mode == "captions":
            print("[whisper] captions-Modus: keine Captions gefunden", file=sys.stderr)
            return {"language": language, "model": "captions:none", "latency_s": 0,
                    "segment_count": 0, "segments": []}
        print("[whisper] keine Captions → fallback whisper.cpp", file=sys.stderr)
    if mode == "faster-whisper":
        return transcribe_faster(Path(video_path), work_dir, language=language)
    return transcribe_video(Path(video_path), work_dir, model=DEFAULT_MODEL, language=language)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("video", type=str)
    ap.add_argument("--work-dir", type=str, required=True)
    ap.add_argument("--out", type=str, required=True)
    ap.add_argument("--model", type=str, default=str(DEFAULT_MODEL))
    ap.add_argument("--language", type=str, default="auto")
    args = ap.parse_args()

    result = transcribe_video(
        Path(args.video), Path(args.work_dir),
        model=Path(args.model), language=args.language,
    )
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
