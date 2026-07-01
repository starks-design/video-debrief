#!/usr/bin/env python3
"""Frame-Beschreibung via OpenAI-kompatible Vision-API.

Backend (Ollama / LM Studio / oMLX / andere) kommt aus der Config
(base_url + model + optionaler ENV-Key). Bei backend == "omlx" wird das
Modell nach dem Job über die Admin-API entladen.
"""
from __future__ import annotations

import argparse
import base64
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import load_config, get_api_key, language_name  # noqa: E402

_CFG = load_config()
VISION_URL = _CFG["vision"]["base_url"]
DEFAULT_MODEL = _CFG["vision"]["model"]            # vom Setup gesetzt
# Frame descriptions follow the configured output language (default English).
_LANG_INSTRUCTION = f"\n\nWrite the entire description in {language_name(_CFG)}."


def _omlx_base() -> str:
    """Host-Teil der konfigurierten Vision-URL (für die oMLX-Admin-Endpoints)."""
    return VISION_URL.split("/v1/")[0]


# Admin-Unload-Endpoint nur relevant für backend == "omlx" (aus Config abgeleitet):
OMLX_ADMIN_URL = _omlx_base() + "/admin/api/models"


def _api_key() -> str:
    """Key aus der konfigurierten ENV-Variable (leer = kein Auth-Header)."""
    return get_api_key(_CFG["vision"]["api_key_env"])

DEFAULT_PROMPT = (
    "Describe this video frame in EXACTLY 5 sentences — one sentence per dimension, "
    "in this order:\n"
    "1. SUBJECT + ACTION: who/what is in the frame, what is happening.\n"
    "2. SETTING + COMPOSITION: location, indoor/outdoor, framing (close-up/medium/wide), "
    "camera angle (low/eye-level/high), depth-of-field.\n"
    "3. LOOK + STYLE: lighting (natural/artificial, hard/soft, direction, mood like "
    "'golden hour', 'harsh studio', 'dim ambient'), dominant colors / color grade "
    "(warm/cool, teal-orange, desaturated, vivid, monochrome), production style "
    "(handheld, static tripod, drone, dolly).\n"
    "4. UI + TEXT + LOGOS: any visible text, captions, brand logos, UI elements — "
    "transcribe them exactly as you read them. If none visible, say 'no visible text'.\n"
    "5. SPECIAL: anything notable that didn't fit above — emotion on faces, unusual props, "
    "motion blur direction, reflections, weather, sound cues if implied. If nothing "
    "notable, say 'no special elements'.\n\n"
    "Use concrete terms for objects (cameras, lenses, tools, vehicles, products) — "
    "not vague ones. No filler phrases. Each sentence stands alone."
)

CONTEXT_PROMPT = (
    "Describe THIS video frame in EXACTLY 5 sentences, with CONSISTENCY to prior frames.\n\n"
    "Recent frame descriptions (likely same scene, same people/objects):\n"
    "{context_block}\n\n"
    "Now describe the CURRENT frame in exactly 5 sentences in this order:\n"
    "1. SUBJECT + ACTION (use 'Same person/object, now ...' if continuing; "
    "'Cut to:' or 'New scene:' if scene changed).\n"
    "2. SETTING + COMPOSITION (location, framing, angle, depth-of-field).\n"
    "3. LOOK + STYLE (lighting, color grade, production style).\n"
    "4. UI + TEXT + LOGOS (transcribe visible text exactly; 'no visible text' if none).\n"
    "5. SPECIAL (emotion, props, motion, reflections; 'no special elements' if none).\n\n"
    "Stay CONSISTENT with prior frames: same outfit-color, same person-identification. "
    "Use concrete terms for objects, not vague ones. No filler. Each sentence stands alone."
)


def encode_image(path: Path) -> str:
    return base64.b64encode(path.read_bytes()).decode("ascii")


def describe_one(model: str, image_path: Path, prompt: str, timeout: int = 120) -> dict:
    b64 = encode_image(image_path)
    payload = {
        "model": model,
        "messages": [{
            "role": "user",
            "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
            ],
        }],
        "max_tokens": 350,
        "temperature": 0.2,
    }
    body = json.dumps(payload).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    api_key = _api_key()
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    req = urllib.request.Request(VISION_URL, data=body, headers=headers, method="POST")

    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"description": f"[ERROR] {exc}", "latency_s": round(time.time() - t0, 3), "error": True}
    latency = time.time() - t0

    try:
        data = json.loads(raw)
        content = data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, json.JSONDecodeError) as exc:
        return {"description": f"[ERROR parse] {exc}", "latency_s": round(latency, 3), "error": True}

    return {"description": content, "latency_s": round(latency, 3)}


def _build_context_block(prior_results: list[dict], window: int) -> str:
    recent = prior_results[-window:] if window > 0 else []
    if not recent:
        return "(this is the first frame — no prior context)"
    lines = []
    for r in recent:
        ts = r.get("timestamp", 0)
        m = int(ts // 60)
        s = ts - m * 60
        lines.append(f"- [{m:02d}:{s:05.2f}] {r.get('description', '')}")
    return "\n".join(lines)


def _omlx_admin_session() -> str | None:
    try:
        settings_path = Path.home() / ".omlx" / "settings.json"
        settings = json.loads(settings_path.read_text())
        api_key = settings["auth"]["api_key"]
        secret_key = settings["auth"]["secret_key"]
        payload = json.dumps({"api_key": api_key, "secret_key": secret_key}).encode()
        req = urllib.request.Request(_omlx_base() + "/admin/api/login", data=payload, headers={"Content-Type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            cookie = resp.headers.get("Set-Cookie", "")
            for part in cookie.split(";"):
                if "omlx_admin_session" in part:
                    return part.strip()
    except Exception:
        pass
    return None


def unload_model(model_id: str):
    cookie = _omlx_admin_session()
    if not cookie:
        print(f"[describe] unload skipped: no admin session", file=sys.stderr)
        return
    req = urllib.request.Request(
        f"{OMLX_ADMIN_URL}/{model_id}/unload",
        headers={"Cookie": cookie},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read().decode("utf-8"))
            print(f"[describe] model unloaded: {result}", file=sys.stderr)
    except Exception as exc:
        print(f"[describe] unload failed (non-critical): {exc}", file=sys.stderr)


def describe_all(
    model: str,
    frames: list[dict],
    prompt: str = DEFAULT_PROMPT,
    context_window: int = 2,
    save_dir: Path | None = None,
    progress_cb=None,
) -> dict:
    results = []
    total_t0 = time.time()
    use_context = context_window > 0
    checkpoint_file = save_dir / "vision_checkpoint.json" if save_dir else None
    pause_file = save_dir / "pause" if save_dir else None

    # Resume: lade vorherige Ergebnisse per Timestamp-Match
    existing_by_ts: dict[int, dict] = {}
    def _load_cached(source: list[dict], label: str):
        for r in source:
            ts_key = int(r["timestamp"])
            existing_by_ts[ts_key] = r
        if source:
            print(f"[describe] found {len(source)} cached frames from {label}", file=sys.stderr)

    if checkpoint_file and checkpoint_file.exists():
        try:
            saved = json.loads(checkpoint_file.read_text(encoding="utf-8"))
            _load_cached(saved.get("frames", []), "checkpoint")
        except Exception:
            pass
    if save_dir:
        result_json = save_dir / "debrief_result.json"
        if result_json.exists():
            try:
                rd = json.loads(result_json.read_text(encoding="utf-8"))
                vframes = rd.get("vision", {}).get("frames", [])
                if vframes and len(vframes) > len(existing_by_ts):
                    existing_by_ts.clear()
                    _load_cached(vframes, "result JSON")
            except Exception:
                pass

    skipped = 0
    print(f"[describe] {len(frames)} frames → model: {model}, ctx={context_window}", file=sys.stderr)

    for i, frame in enumerate(frames, 1):
        ts_key = int(frame["timestamp"])
        cached = existing_by_ts.get(ts_key)
        if cached and not cached.get("error"):
            results.append(cached)
            skipped += 1
            if skipped % 50 == 0:
                print(f"[describe] skipped {skipped} cached frames...", file=sys.stderr)
            continue

        # Pause-Check
        if pause_file and pause_file.exists():
            print(f"[describe] PAUSED at frame {i}/{len(frames)} — delete 'pause' file to resume", file=sys.stderr)
            while pause_file.exists():
                time.sleep(2)
            print(f"[describe] RESUMED", file=sys.stderr)

        path = Path(frame["path"])
        if not path.exists():
            print(f"[describe] frame missing: {path}", file=sys.stderr)
            continue

        if use_context:
            context_block = _build_context_block(results, context_window)
            frame_prompt = CONTEXT_PROMPT.format(context_block=context_block)
        else:
            frame_prompt = prompt
        frame_prompt = frame_prompt + _LANG_INSTRUCTION

        out = describe_one(model, path, frame_prompt)
        results.append({
            "index": frame["index"],
            "timestamp": frame["timestamp"],
            "filename": frame.get("filename", path.name),
            **out,
        })

        # Checkpoint nach jedem Frame
        if checkpoint_file:
            avg = sum(r.get("latency_s", 0) for r in results) / max(len(results), 1)
            checkpoint_file.write_text(json.dumps({
                "model": model,
                "context_window": context_window,
                "frame_count": len(results),
                "avg_latency_s": round(avg, 3),
                "frames": results,
            }, ensure_ascii=False), encoding="utf-8")

        if progress_cb:
            try:
                progress_cb(len(results), len(frames))
            except Exception:
                pass

        new_results = [r for r in results if r.get("latency_s", 0) > 0 and int(r["timestamp"]) not in existing_by_ts]
        if i % 5 == 0 or i == len(frames):
            avg_new = sum(r.get("latency_s", 0) for r in new_results) / max(len(new_results), 1) if new_results else 0
            print(
                f"[describe] {i}/{len(frames)} done ({skipped} cached, {len(new_results)} new) — avg {avg_new:.2f}s/frame "
                f"({model}, ctx={context_window})",
                file=sys.stderr,
            )
    total = time.time() - total_t0
    if skipped:
        print(f"[describe] resumed: {skipped} frames from cache, {len(results) - skipped} new", file=sys.stderr)

    # Checkpoint aufräumen
    if checkpoint_file and checkpoint_file.exists():
        checkpoint_file.unlink()

    # Vision-Modell entladen → RAM freigeben (nur oMLX hat die Admin-Unload-API)
    if _CFG["vision"].get("backend") == "omlx":
        print(f"[describe] unloading {model} from oMLX...", file=sys.stderr)
        unload_model(model)

    return {
        "model": model,
        "context_window": context_window,
        "total_time_s": round(total, 3),
        "frame_count": len(results),
        "avg_latency_s": round(total / max(len(results), 1), 3),
        "frames": results,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames-json", type=str, required=True)
    ap.add_argument("--model", type=str, default=DEFAULT_MODEL)
    ap.add_argument("--out", type=str, required=True)
    ap.add_argument("--context-window", type=int, default=2)
    args = ap.parse_args()

    data = json.loads(Path(args.frames_json).read_text())
    frames = data.get("frames", [])
    result = describe_all(args.model, frames, context_window=args.context_window)
    Path(args.out).write_text(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
