#!/usr/bin/env python3
"""Scene-Detection mit ffmpeg.

Extrahiert Frames bei jedem harten Schnittwechsel (Scene-Change) plus
optional einen "Heartbeat"-Frame alle N Sekunden für statische Talking-Heads.

Output: frames/scene_NNNN_t<ms>.jpg + frames.json mit Timestamps.
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path


def get_duration_seconds(video_path: Path) -> float:
    """Video-Länge in Sekunden via ffprobe."""
    cmd = [
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(video_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    if res.returncode != 0:
        raise SystemExit(f"ffprobe failed: {res.stderr.strip()}")
    data = json.loads(res.stdout)
    return float(data["format"]["duration"])


def detect_scene_changes(video_path: Path, threshold: float) -> list[float]:
    """Liefert Liste von Timestamps (Sekunden) bei denen ein Scene-Change ist.

    Nutzt ffmpeg's `select='gt(scene,X)',showinfo` Filter — der gibt für jeden
    erkannten Cut eine Zeile in stderr mit `pts_time:N.NNN` aus.
    """
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-i", str(video_path),
        "-vf", f"select='gt(scene,{threshold})',showinfo",
        "-f", "null", "-",
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    pts_re = re.compile(r"pts_time:([0-9.]+)")
    timestamps: list[float] = []
    for line in res.stderr.splitlines():
        match = pts_re.search(line)
        if match:
            timestamps.append(float(match.group(1)))
    return sorted(set(timestamps))


def add_heartbeats(scene_ts: list[float], duration: float, every: float) -> list[float]:
    """Fügt Heartbeat-Frames in Lücken ein, wo zwischen zwei Scene-Cuts > `every` Sek liegen."""
    if every <= 0:
        return scene_ts
    augmented = list(scene_ts)
    if not augmented or augmented[0] > every:
        augmented.insert(0, 0.0)
    extra: list[float] = []
    for i in range(len(augmented) - 1):
        gap = augmented[i + 1] - augmented[i]
        if gap > every:
            n = int(gap // every)
            for k in range(1, n + 1):
                extra.append(augmented[i] + k * every)
    last = augmented[-1] if augmented else 0.0
    while last + every < duration:
        last += every
        extra.append(last)
    return sorted(set(augmented + extra))


def extract_frame(video_path: Path, timestamp: float, out_path: Path, width: int = 768) -> bool:
    """Extrahiert einen einzelnen Frame an Timestamp via ffmpeg."""
    cmd = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel", "error",
        "-y",
        "-ss", f"{timestamp:.3f}",
        "-i", str(video_path),
        "-frames:v", "1",
        "-vf", f"scale={width}:-1",
        "-q:v", "3",
        str(out_path),
    ]
    res = subprocess.run(cmd, capture_output=True, text=True)
    return res.returncode == 0 and out_path.exists() and out_path.stat().st_size > 0


def extract_all(
    video_path: Path,
    out_dir: Path,
    threshold: float = 0.3,
    heartbeat_seconds: float = 30.0,
    max_frames: int = 0,
    width: int = 768,
) -> dict:
    """Vollständige Pipeline: Detection + Heartbeat + Extract.

    Returns dict mit { duration, threshold, frames: [{index, timestamp, path}] }.
    """
    if shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None:
        raise SystemExit("ffmpeg/ffprobe not found. Install via: brew install ffmpeg")

    out_dir.mkdir(parents=True, exist_ok=True)
    duration = get_duration_seconds(video_path)
    print(f"[scene] video duration: {duration:.1f}s", file=sys.stderr)

    scene_ts = detect_scene_changes(video_path, threshold)
    print(f"[scene] {len(scene_ts)} scene-changes at threshold {threshold}", file=sys.stderr)

    timestamps = add_heartbeats(scene_ts, duration, heartbeat_seconds)

    if max_frames > 0 and len(timestamps) > max_frames:
        step = len(timestamps) / max_frames
        timestamps = [timestamps[int(i * step)] for i in range(max_frames)]
        print(f"[scene] capped at {max_frames} frames (step {step:.2f})", file=sys.stderr)

    if len(timestamps) < len(scene_ts) + 1:
        # mindestens den 0-Frame
        timestamps = [0.0] + timestamps if 0.0 not in timestamps else timestamps

    frames = []
    for idx, ts in enumerate(timestamps):
        out_path = out_dir / f"frame_{idx:04d}_t{int(ts*1000):07d}.jpg"
        if extract_frame(video_path, ts, out_path, width=width):
            frames.append({
                "index": idx,
                "timestamp": round(ts, 3),
                "path": str(out_path),
                "filename": out_path.name,
            })
        else:
            print(f"[scene] failed to extract frame at {ts:.2f}s", file=sys.stderr)

    print(f"[scene] extracted {len(frames)} frames", file=sys.stderr)

    return {
        "duration": duration,
        "threshold": threshold,
        "heartbeat_seconds": heartbeat_seconds,
        "scene_changes_detected": len(scene_ts),
        "frames": frames,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Scene-Detection Frame-Extraction")
    ap.add_argument("video", type=str, help="Path to video file")
    ap.add_argument("--out-dir", type=str, required=True)
    ap.add_argument("--threshold", type=float, default=0.3)
    ap.add_argument("--heartbeat-seconds", type=float, default=30.0)
    ap.add_argument("--max-frames", type=int, default=200)
    ap.add_argument("--width", type=int, default=768)
    args = ap.parse_args()

    result = extract_all(
        Path(args.video),
        Path(args.out_dir),
        threshold=args.threshold,
        heartbeat_seconds=args.heartbeat_seconds,
        max_frames=args.max_frames,
        width=args.width,
    )
    json_out = Path(args.out_dir) / "frames.json"
    json_out.write_text(json.dumps(result, indent=2))
    print(f"[scene] wrote {json_out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
