#!/usr/bin/env python3
"""Video Debrief config. Pure stdlib.

Such-Reihenfolge:
  1. $DEBRIEF_CONFIG   (expliziter Pfad)
  2. ./debrief.config.json   (projekt-lokal)
  3. ~/.debrief/config.json  (user-global)

Datei-Werte überschreiben die Defaults (deep merge). Es werden KEINE Keychain
und KEINE festen Pfade verwendet — API-Keys kommen ausschließlich aus einer
ENV-Variable, deren Name in `*.api_key_env` steht (leer = kein Auth-Header).
"""
from __future__ import annotations

import json
import os
from pathlib import Path

DEFAULTS = {
    "output_dir": "./debrief-output",
    "vision": {
        "base_url": "http://localhost:11434/v1/chat/completions",  # Ollama default
        "model": "",            # vom Setup gesetzt (z.B. ein Qwen-VL / Gemma-Vision Tag)
        "api_key_env": "",      # Name der ENV-Var mit dem Key, falls nötig
        "backend": "ollama",    # ollama | lmstudio | omlx | other
        "context_window": 2,
    },
    "insights": {
        "base_url": "http://localhost:11434/v1/chat/completions",
        "model": "",
        "api_key_env": "",
        "enabled": True,
    },
    "whisper": {
        "mode": "auto",         # auto | captions | whisper | faster-whisper
        "bin": "whisper-cli",
        "model_path": "",       # ggml-Modell für whisper.cpp (leer = Default unter ~/.debrief/models)
        "language": "auto",
    },
    "summary": {
        "engine": "host-agent",  # host-agent | local-llm | none
        "base_url": "",
        "model": "",
        "api_key_env": "",
    },
    "relevance": {
        "enabled": False,
        "profile": "",
    },
    "branding": {"footer": True},
    "scene": {"threshold": 0.3, "heartbeat_seconds": 30.0, "max_frames": 0},
    # Nach der Analyse aufräumen: Video + Frames löschen (Privacy + Speicher).
    # Nur Report + debrief_result.json bleiben. Standardmäßig AN.
    "cleanup": {"delete_video": True, "delete_frames": True},
}


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def _find_file() -> Path | None:
    env = os.environ.get("DEBRIEF_CONFIG")
    if env and Path(env).expanduser().is_file():
        return Path(env).expanduser()
    cwd = Path.cwd() / "debrief.config.json"
    if cwd.is_file():
        return cwd
    usr = Path.home() / ".debrief" / "config.json"
    return usr if usr.is_file() else None


def load_config() -> dict:
    cfg = json.loads(json.dumps(DEFAULTS))  # deep copy
    p = _find_file()
    if p:
        try:
            cfg = _merge(cfg, json.loads(p.read_text(encoding="utf-8")))
        except Exception as e:  # noqa: BLE001
            raise SystemExit(f"[debrief] config error in {p}: {e}")
    return cfg


def get_api_key(api_key_env: str) -> str:
    """API-Key aus einer ENV-Variable. Leerer Name -> kein Key.
    Liest nie eine Keychain, hardcoded nie ein Secret."""
    return os.environ.get(api_key_env, "") if api_key_env else ""


def resolve_output_dir(cfg: dict) -> Path:
    p = Path(cfg["output_dir"]).expanduser()
    p.mkdir(parents=True, exist_ok=True)
    return p
