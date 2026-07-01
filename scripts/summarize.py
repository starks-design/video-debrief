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
from config import get_api_key  # noqa: E402

DEEP_THRESHOLD_S = 30 * 60          # > 30 min → mehr Tiefe
TRANSCRIPT_BACKSTOP = 150_000
VISUAL_BACKSTOP = 400_000


def build_inputs(data: dict) -> dict:
    """Prompt-Bausteine aus den Analyse-Daten (volles Transcript + Visual-Track)."""
    meta = data.get("meta", {})
    segs = data.get("transcript", {}).get("segments", [])
    transcript_text = "\n".join(f"[{s['start']:.0f}s] {s['text']}" for s in segs)
    if len(transcript_text) > TRANSCRIPT_BACKSTOP:
        transcript_text = transcript_text[:TRANSCRIPT_BACKSTOP] + "\n[... gekürzt]"

    vframes = data.get("vision", {}).get("frames", [])
    visual_track = "\n".join(
        f"[{f['timestamp']:.0f}s] {f.get('description', '').strip()}"
        for f in vframes if f.get("description")
    )
    if len(visual_track) > VISUAL_BACKSTOP:
        visual_track = visual_track[:VISUAL_BACKSTOP] + "\n[... gekürzt]"

    insights = data.get("insights", [])
    insights_block = ""
    if insights:
        insights_block = "Extrahierte Insights:\n" + "\n".join(
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
                 insights_block: str, deep: bool = False,
                 relevance_enabled: bool = False, profile: str = "") -> str:
    title = meta.get("title", "Unbekannt")
    uploader = meta.get("uploader", "Unbekannt")
    dur_min = f"{meta.get('duration', 0) / 60:.0f} Min"

    visual_section = ""
    if visual_track:
        visual_section = (
            "\n\nVisueller Verlauf (was im Bild zu sehen war — Slides, Code, UI, "
            "eingeblendeter Text, OCR; je Eintrag ein Frame mit Timestamp):\n"
            f"{visual_track}\n"
            "Nutze diesen Track gezielt für Bildschirm-Inhalte (Tools, Befehle, "
            "Code, Slide-Texte, Zahlen im Bild) — nicht für Belanglosigkeiten."
        )

    if deep:
        depth_directive = (
            f"WICHTIG: Dieses Video ist {dur_min} lang. Liefere ENTSPRECHEND TIEFE. "
            "Arbeite das GANZE Video durch (Anfang bis Ende), nicht nur den Einstieg.\n\n"
        )
        insights_hint = "10-15 destillierte Kernaussagen aus dem GESAMTEN Video"
        keyfacts_hint = ("Wichtigste Fakten/Zahlen aus dem GESAMTEN Video, ~1 pro 5 Min, "
                         "chronologisch breit gestreut")
    else:
        depth_directive = ""
        insights_hint = "5-8 destillierte Kernaussagen aus dem gesamten Video"
        keyfacts_hint = "Die wichtigsten Fakten, Zahlen, Aussagen — max 6"

    relevance_block = ""
    profile_ctx = ""
    if relevance_enabled and profile.strip():
        relevance_block = (
            '\n<div class="relevance"><h3>Relevanz für dich</h3><ul>'
            '<li>Kurze, ehrliche Einschätzung vor dem Profil des Nutzers: relevant '
            'oder nicht? Warum? Max 3 Bullet Points.</li>'
            '</ul></div>'
        )
        profile_ctx = f"\n\nNutzer-Kontext (nur für den Relevanz-Block): {profile.strip()}\n"

    return f"""Du bekommst die Analyse-Daten eines Videos. Schreibe eine strukturierte Zusammenfassung als HTML.

{depth_directive}Video: {title} von {uploader} ({dur_min})

Transcript (vollständig):
{transcript_text}{visual_section}

{insights_block}{profile_ctx}

Schreibe EXAKT dieses HTML-Format — nichts davor, nichts danach:

<section id="summary"><h2>Zusammenfassung</h2><div class="summary-body">
<div class="key-insights">
<h3>Wichtigste Erkenntnisse</h3>
<ul>
<li>{insights_hint} — jede konkret, in einem Satz, mit dem relevanten Fakt/Zahl/Tool</li>
<li>Sortiert nach Wichtigkeit, nicht chronologisch</li>
</ul>
</div>
<h3>Thema</h3>
<p>Worum geht es, was passiert — 2-3 Sätze</p>
<h3>Key Facts</h3>
<div class="kf-stats">
<div class="stat"><span class="v">39,8 %</span><span class="l">kurzes Label, 3-6 Wörter</span></div>
<div class="stat"><span class="v">53 → 96</span><span class="l">noch ein Label</span></div>
</div>
<ul class="kf-rest"><li>Wichtige Fakten OHNE prägnante Kennzahl als kurze Bullets</li></ul>
<h3>Fazit</h3>
<p>Kernaussage in 1-2 Sätzen</p>{relevance_block}
</div></section>

Antwort-Format:
Zeile 1: [TAGS] komma-separierte Tags (3-6 Stück, lowercase, kebab-case)
Zeile 2+: der HTML-Block

Regeln:
- Hebe in jedem Bullet/Absatz Schlüsselbegriffe mit <strong>…</strong> hervor (Zahlen, Tool-/Produktnamen, Kernaussagen) — nicht ganze Sätze fetten.
- KEY FACTS als Stat-Kacheln: {keyfacts_hint}. v = kompakter Wert (max ~8 Zeichen, z.B. "39,8 %", "53 → 96", ">500k"), l = Kontext in 3-6 Wörtern. 4-8 Kacheln, prägnanteste zuerst. KEINE <strong> in den Kacheln. Fakten ohne klare Zahl als <li> in <ul class="kf-rest"> (max 4).
- Fakten aus Transcript UND visuellem Verlauf, keine Erfindungen.
- Sprache: Deutsch (oder die Sprache des Transcripts), dicht, keine Füllwörter.
- Keine ungestützten Zahlen oder Versprechen. Kein Branding, keine Action-Items."""


def parse_output(raw: str):
    """[TAGS] / HTML zerlegen. Rückgabe: (tags, summary_html)."""
    raw = raw.strip()
    tags: list[str] = []
    lines = raw.split("\n", 1)
    if lines and lines[0].startswith("[TAGS]"):
        tags = [t.strip() for t in lines[0][len("[TAGS]"):].split(",") if t.strip()]
        raw = lines[1].strip() if len(lines) > 1 else ""

    # ggf. ```html ... ``` entfernen
    raw = re.sub(r"^```(?:html)?\s*", "", raw)
    raw = re.sub(r"\s*```$", "", raw)

    summary_html = raw
    if "<section" not in summary_html:
        summary_html = (
            f'<section id="summary"><h2>Zusammenfassung</h2>'
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

    inp = build_inputs(data)
    deep = (inp["duration"] or 0) > DEEP_THRESHOLD_S
    prompt = build_prompt(
        inp["meta"], inp["transcript_text"], inp["visual_track"], inp["insights_block"],
        deep=deep,
        relevance_enabled=cfg["relevance"]["enabled"],
        profile=cfg["relevance"]["profile"],
    )

    if engine == "host-agent":
        (work_dir / "SUMMARY_TODO.md").write_text(
            "# Video Debrief — Summary-Auftrag für den Agenten\n\n"
            "Schreibe anhand des folgenden Prompts die Zusammenfassung und setze den "
            "erzeugten `<section id=\"summary\">…</section>`-Block in `report.html` ein "
            "(ersetzt den Platzhalter).\n\n---\n\n" + prompt,
            encoding="utf-8",
        )
        print("[summary] host-agent: Prompt → SUMMARY_TODO.md", file=sys.stderr)
        return "", []

    if engine == "local-llm":
        t0 = time.time()
        try:
            raw = _local_llm_summary(prompt, cfg)
        except Exception as exc:  # noqa: BLE001
            print(f"[summary] local-llm fehlgeschlagen: {exc}", file=sys.stderr)
            return "", []
        print(f"[summary] local-llm in {time.time() - t0:.1f}s", file=sys.stderr)
        return parse_output(raw)

    return "", []
