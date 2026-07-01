#!/usr/bin/env python3
"""Video Debrief — Zusammenfassung.

Baut aus debrief_result.json (volles Transcript + visueller Verlauf +
Insights) den Prompt für eine strukturierte HTML-Summary. Generisch — kein
Branding, keine festen Geschäfts-Kontexte. Ein optionaler Relevanz-Block wird
NUR erzeugt, wenn `relevance.enabled` gesetzt ist, und nutzt ausschließlich
das vom Nutzer hinterlegte Profil.

Summary-Engine (aus Config `summary.engine`):
  host-agent   schreibt den fertigen Prompt nach SUMMARY_TODO.md; der Agent,
               der Video Debrief ausführt (z.B. Claude Code), schreibt die Summary.
  local-llm    POST an `summary.base_url` / `summary.model`.
  none         keine Summary.
"""
from __future__ import annotations

import json
import re
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_api_key, get_labels, language_name  # noqa: E402

DEEP_THRESHOLD_S = 30 * 60          # > 30 min → mehr Tiefe
TRANSCRIPT_BACKSTOP = 150_000
VISUAL_BACKSTOP = 400_000


def build_inputs(data: dict) -> dict:
    """Prompt-Bausteine aus den Analyse-Daten (volles Transcript + Visual-Track)."""
    meta = data.get("meta", {})
    segs = data.get("transcript", {}).get("segments", [])
    transcript_text = "\n".join(f"[{s['start']:.0f}s] {s['text']}" for s in segs)
    if len(transcript_text) > TRANSCRIPT_BACKSTOP:
        transcript_text = transcript_text[:TRANSCRIPT_BACKSTOP] + "\n[... truncated]"

    vframes = data.get("vision", {}).get("frames", [])
    visual_track = "\n".join(
        f"[{f['timestamp']:.0f}s] {f.get('description', '').strip()}"
        for f in vframes if f.get("description")
    )
    if len(visual_track) > VISUAL_BACKSTOP:
        visual_track = visual_track[:VISUAL_BACKSTOP] + "\n[... truncated]"

    insights = data.get("insights", [])
    insights_block = ""
    if insights:
        insights_block = "Extracted insights:\n" + "\n".join(
            f"- [{i['ts']:.0f}s] {i['text']}" for i in insights
        )
    return {
        "meta": meta,
        "duration": meta.get("duration", 0) or 0,
        "transcript_text": transcript_text,
        "visual_track": visual_track,
        "insights_block": insights_block,
    }


def build_prompt(meta: dict, transcript_text: str, visual_track: str,
                 insights_block: str, labels: dict, lang_name: str,
                 deep: bool = False,
                 relevance_enabled: bool = False, profile: str = "") -> str:
    title = meta.get("title", "Unknown")
    uploader = meta.get("uploader", "Unknown")
    dur_min = f"{meta.get('duration', 0) / 60:.0f} min"

    visual_section = ""
    if visual_track:
        visual_section = (
            "\n\nVisual track (what was on screen — slides, code, UI, on-screen text, "
            "OCR; one frame per entry with timestamp):\n"
            f"{visual_track}\n"
            "Use this track specifically for screen content (tools, commands, code, "
            "slide text, numbers on screen) — not for trivia."
        )

    if deep:
        depth_directive = (
            f"IMPORTANT: this video is {dur_min} long. Deliver DEPTH accordingly. "
            "Work through the WHOLE video (start to end), not just the intro.\n\n"
        )
        insights_hint = "10-15 distilled key statements from the ENTIRE video"
        keyfacts_hint = ("the most important facts/numbers from the ENTIRE video, ~1 per 5 min, "
                         "spread widely across the timeline")
    else:
        depth_directive = ""
        insights_hint = "5-8 distilled key statements from the whole video"
        keyfacts_hint = "the most important facts, numbers, statements — max 6"

    relevance_block = ""
    profile_ctx = ""
    if relevance_enabled and profile.strip():
        relevance_block = (
            f'\n<div class="relevance"><h3>{labels["relevance"]}</h3><ul>'
            '<li>Short, honest assessment against the user profile: relevant '
            'or not? Why? Max 3 bullet points.</li>'
            '</ul></div>'
        )
        profile_ctx = f"\n\nUser context (only for the relevance block): {profile.strip()}\n"

    return f"""You receive the analysis data of a video. Write a structured summary as HTML.

{depth_directive}Video: {title} by {uploader} ({dur_min})

Transcript (full):
{transcript_text}{visual_section}

{insights_block}{profile_ctx}

Write EXACTLY this HTML format — nothing before, nothing after:

<section id="summary"><h2>{labels["summary"]}</h2><div class="summary-body">
<div class="key-insights">
<h3>{labels["key_insights"]}</h3>
<ul>
<li>{insights_hint} — each concrete, in one sentence, with the relevant fact/number/tool</li>
<li>Sorted by importance, not chronologically</li>
</ul>
</div>
<h3>{labels["topic"]}</h3>
<p>What it's about, what happens — 2-3 sentences</p>
<h3>{labels["key_facts"]}</h3>
<div class="kf-stats">
<div class="stat"><span class="v">39.8%</span><span class="l">short label, 3-6 words</span></div>
<div class="stat"><span class="v">53 → 96</span><span class="l">another label</span></div>
</div>
<ul class="kf-rest"><li>Important facts WITHOUT a crisp metric as short bullets</li></ul>
<h3>{labels["bottom_line"]}</h3>
<p>Core takeaway in 1-2 sentences</p>{relevance_block}
</div></section>

Response format:
Line 1: [TAGS] comma-separated tags (3-6, lowercase, kebab-case)
Line 2+: the HTML block

Rules:
- In every bullet/paragraph, highlight key terms with <strong>…</strong> (numbers, tool/product names, core statements) — don't bold whole sentences.
- KEY FACTS as stat tiles: {keyfacts_hint}. v = compact value (max ~8 chars, e.g. "39.8%", "53 → 96", ">500k"), l = context in 3-6 words. 4-8 tiles, most striking first. NO <strong> in the tiles. Facts without a clear number as <li> in <ul class="kf-rest"> (max 4).
- Facts from transcript AND visual track, no fabrication.
- Language: write everything in {lang_name}, dense, no filler words.
- No unsupported numbers or promises. No branding, no action items."""


def parse_output(raw: str, summary_label: str = "Summary"):
    """Split [TAGS] / HTML. Returns (tags, summary_html)."""
    raw = raw.strip()
    tags: list[str] = []
    lines = raw.split("\n", 1)
    if lines and lines[0].startswith("[TAGS]"):
        tags = [t.strip() for t in lines[0][len("[TAGS]"):].split(",") if t.strip()]
        raw = lines[1].strip() if len(lines) > 1 else ""

    # strip ```html ... ``` if present
    raw = re.sub(r"^```(?:html)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    summary_html = raw
    if "<section" not in summary_html:
        summary_html = (
            f'<section id="summary"><h2>{summary_label}</h2>'
            f'<div class="summary-body">{summary_html}</div></section>'
        )
    return tags, summary_html


def _local_llm_summary(prompt: str, cfg: dict) -> str:
    s = cfg["summary"]
    payload = json.dumps({
        "model": s["model"],
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 2000,
        "temperature": 0.2,
    }).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    key = get_api_key(s.get("api_key_env", ""))
    if key:
        headers["Authorization"] = f"Bearer {key}"
    req = urllib.request.Request(s["base_url"], data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    return data["choices"][0]["message"]["content"].strip()


def generate_summary(data: dict, cfg: dict, work_dir: Path):
    """Erzeugt (summary_html, tags) je nach summary.engine.

    host-agent → schreibt SUMMARY_TODO.md mit dem fertigen Prompt und gibt
    ("", []) zurück; der ausführende Agent füllt die Summary in den Report.
    """
    engine = cfg["summary"]["engine"]
    if engine == "none":
        return "", []

    labels = get_labels(cfg)
    lang_name = language_name(cfg)
    inp = build_inputs(data)
    deep = (inp["duration"] or 0) > DEEP_THRESHOLD_S
    prompt = build_prompt(
        inp["meta"], inp["transcript_text"], inp["visual_track"], inp["insights_block"],
        labels, lang_name, deep=deep,
        relevance_enabled=cfg["relevance"]["enabled"],
        profile=cfg["relevance"]["profile"],
    )

    if engine == "host-agent":
        (work_dir / "SUMMARY_TODO.md").write_text(
            "# Video Debrief — summary task for the agent\n\n"
            f"Using the prompt below, write the summary and insert the generated "
            "`<section id=\"summary\">…</section>` block into `report.html` "
            f"(replacing the placeholder). Write the content in {lang_name}.\n\n---\n\n" + prompt,
            encoding="utf-8",
        )
        print("[summary] host-agent: prompt → SUMMARY_TODO.md", file=sys.stderr)
        return "", []

    if engine == "local-llm":
        t0 = time.time()
        try:
            raw = _local_llm_summary(prompt, cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"[summary] local-llm failed: {exc}", file=sys.stderr)
            return "", []
        print(f"[summary] local-llm in {time.time() - t0:.1f}s", file=sys.stderr)
        return parse_output(raw, labels["summary"])

    return "", []
