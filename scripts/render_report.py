#!/usr/bin/env python3
"""HTML-Report für Video Debrief — Video-Player + klickbare Transcript-Timeline +
Insight-Marker + Summary. Self-contained, keine externen Calls (keine Web-Fonts),
passend zum 'komplett lokal'-Versprechen. Dezenter Branding-Footer.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from config import get_labels  # noqa: E402

# Starks.Design Bildwortmarke (einfärbbar via currentColor), self-contained inline.
try:
    _LOGO_SVG = (Path(__file__).resolve().parent / "starks-logo.svg").read_text(encoding="utf-8")
except Exception:  # noqa: BLE001
    _LOGO_SVG = "Starks.Design"

# Shop-Link für den Footer (zentral, falls sich die URL ändert).
SHOP_URL = "https://starks.design"

# Player + Transcript-Sync (wie im Dashboard). Über http(s): YT IFrame API →
# Inline-Play + aktive Transcript-Zeile mitscrollen. Von file:// blockt YouTube
# das Embed (Fehler 153) → Thumbnail bleibt, Timeline-Klick öffnet die Stelle.
_SEEK_JS = r'''
var __mode = "__MODE__";
var __ytId = "__YTID__";
var __player = null;
var __isHttp = location.protocol.indexOf("http") === 0;
var __rows = [];

function __sync(t) {
  if (!__rows.length) return;
  var act = null;
  for (var i = 0; i < __rows.length; i++) { if (__rows[i].ts <= t + 0.25) act = __rows[i]; else break; }
  if (act && !act.el.classList.contains("active")) {
    var cur = document.querySelector(".tl-row.active");
    if (cur) cur.classList.remove("active");
    act.el.classList.add("active");
    act.el.scrollIntoView({ block: "center", behavior: "smooth" });
  }
}

function __buildYTPlayer() {
  var pw = document.getElementById("player-wrap");
  if (!pw) return;
  pw.innerHTML = '<div id="dw-yt-player"></div>';
  var make = function () {
    __player = new YT.Player("dw-yt-player", {
      videoId: __ytId, width: "100%", height: "100%",
      playerVars: { rel: 0, modestbranding: 1 },
      events: { onReady: function (e) {
        __player = e.target;
        setInterval(function () {
          if (__player && __player.getCurrentTime) __sync(__player.getCurrentTime());
        }, 500);
      } }
    });
  };
  if (window.YT && window.YT.Player) make();
  else {
    if (!window.YT) { var tag = document.createElement("script"); tag.src = "https://www.youtube.com/iframe_api"; document.head.appendChild(tag); }
    window.onYouTubeIframeAPIReady = make;
  }
}

function seekTo(s) {
  s = Math.floor(s);
  if (__mode === "yt") {
    if (__player && __player.seekTo) { __player.seekTo(s, true); if (__player.playVideo) __player.playVideo(); return; }
    window.open("https://www.youtube.com/watch?v=" + __ytId + "&t=" + s + "s", "_blank");
    return;
  }
  var v = document.getElementById("local-video");
  if (v) { v.currentTime = s; v.play(); }
}

document.addEventListener("DOMContentLoaded", function () {
  document.querySelectorAll(".tl-row").forEach(function (el) {
    __rows.push({ ts: parseFloat(el.getAttribute("data-ts")) || 0, el: el });
    el.addEventListener("click", function () {
      var cur = document.querySelector(".tl-row.active");
      if (cur) cur.classList.remove("active");
      el.classList.add("active");
    });
  });
  if (__mode === "yt" && __isHttp) __buildYTPlayer();
  var v = document.getElementById("local-video");
  if (v) v.addEventListener("timeupdate", function () { __sync(v.currentTime); });
});
'''


def fmt_time(sec: float) -> str:
    m = int(sec // 60)
    s = sec - m * 60
    return f"{m:02d}:{s:05.2f}"


def _is_url(s: str) -> bool:
    return s.startswith(("http://", "https://", "youtu.be/", "www."))


def _youtube_id(url: str) -> str | None:
    m = re.search(r"(?:v=|youtu\.be/|embed/)([a-zA-Z0-9_-]{11})", url)
    return m.group(1) if m else None


def merge_timeline(transcript: dict, vision: dict) -> list[dict]:
    rows = []
    for seg in transcript.get("segments", []):
        rows.append({"ts": seg["start"], "type": "audio", "text": seg["text"]})
    for fr in vision.get("frames", []):
        rows.append({"ts": fr["timestamp"], "type": "visual", "text": fr["description"]})
    rows.sort(key=lambda r: r["ts"])
    return rows


def _esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_report(meta: dict, frames_data: dict, transcript: dict, vision: dict,
                  total_time: float, work_dir: Path | None,
                  summary: str = "", insights: list[dict] | None = None,
                  branding: bool = True, embed_local: bool = True,
                  language: str = "en") -> str:
    lbl = get_labels({"language": language})
    title = meta.get("title", "Video Debrief report")
    uploader = meta.get("uploader", "")
    duration = frames_data.get("duration", 0)
    url = meta.get("url", "")
    work_dir = Path(work_dir) if work_dir else None

    yt_id = _youtube_id(url) if _is_url(url) else None
    video_path = None
    if not yt_id and work_dir:
        candidates = sorted(work_dir.glob("video.*"))
        video_path = candidates[0] if candidates else None

    # Insight → nächstes Transcript-Segment
    insight_at: dict[float, str] = {}
    if insights:
        seg_starts = [s["start"] for s in transcript.get("segments", [])]
        for ins in insights:
            its = ins["ts"]
            best = min(seg_starts, key=lambda s: abs(s - its), default=its)
            insight_at[best] = ins["text"]

    rows = merge_timeline(transcript, vision)
    tl_aud = []
    for r in rows:
        if r["type"] != "audio":
            continue
        sec = int(r["ts"])
        text = _esc(r["text"])
        marker = ""
        if r["ts"] in insight_at:
            marker = f'<span class="insight-marker">{_esc(insight_at[r["ts"]])}</span>'
        cls = " has-insight" if marker else ""
        tl_aud.append(
            f'<div class="tl-row{cls}" data-ts="{sec}" onclick="seekTo({sec})">'
            f'<span class="ts">[{fmt_time(r["ts"])}]</span>'
            f'<span class="txt">{marker}{text}</span></div>'
        )

    # Video-Block — YouTube via iframe (kein lokales Video nötig); sonst lokale Datei;
    # sonst Hinweis, dass das Video nach der Analyse gelöscht wurde (Privacy/Disk).
    player_mode = "none"
    if yt_id:
        player_mode = "yt"
        # YouTube blockt Embeds von file:// (Fehler 153). Default = Thumbnail + Play
        # (öffnet YouTube; Timeline-Klick öffnet die Stelle via &t=Ns). Über http(s)
        # upgradet das JS automatisch auf ein Inline-iframe (wie im Dashboard).
        video_block = (
            f'<div id="player-wrap">'
            f'<a id="yt-poster" href="https://www.youtube.com/watch?v={yt_id}" target="_blank" rel="noopener"'
            f" style=\"background-image:url('https://img.youtube.com/vi/{yt_id}/maxresdefault.jpg')\">"
            f'<span class="yt-play"></span></a></div>'
        )
    elif video_path and embed_local:
        player_mode = "local"
        video_block = (
            f'<div id="player-wrap"><video id="local-video" controls width="100%">'
            f'<source src="{video_path.name}" type="video/{video_path.suffix.lstrip(".")}">'
            f'</video></div>'
        )
    else:
        video_block = ('<div id="player-wrap" class="no-video"><div>'
                       f'<strong>{lbl["video_deleted_title"]}</strong><br>'
                       f'{lbl["video_deleted_body"]}</div></div>')

    if summary:
        summary_html = f'<section id="summary"><h2>{lbl["summary"]}</h2><div class="summary-body">{summary}</div></section>'
    else:
        summary_html = (f'<section id="summary"><h2>{lbl["summary"]}</h2><div class="summary-body">'
                        f'<p class="placeholder">{lbl["summary_placeholder"]}</p>'
                        '</div></section>')

    if branding:
        footer_html = (
            '<footer>'
            '<span class="made">Made with <strong>Video Debrief</strong></span>'
            f'<a class="brand" href="{SHOP_URL}" target="_blank" rel="noopener" title="Starks.Design">{_LOGO_SVG}</a>'
            '</footer>'
        )
    else:
        footer_html = '<footer></footer>'

    seek_script = _SEEK_JS.replace("__MODE__", player_mode).replace("__YTID__", yt_id or "")

    return f"""<!DOCTYPE html>
<html lang="{language}">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_esc(title)} — Video Debrief</title>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  body {{ background:#0d0b0b; color:#f1ebe5; font-family:'Inter',-apple-system,system-ui,sans-serif;
         font-size:15px; line-height:1.6; }}
  a {{ color:#C2A878; }}
  .mono,.ts {{ font-family:ui-monospace,'JetBrains Mono',monospace; }}
  .wrap {{ max-width:1400px; margin:0 auto; padding:1.5em; }}
  header {{ margin-bottom:1.2em; }}
  header h1 {{ font-size:1.5em; font-weight:700; margin-bottom:0.3em; }}
  header .meta {{ font-family:ui-monospace,monospace; font-size:0.78em; color:#666;
                  display:flex; flex-wrap:wrap; gap:1.2em; }}
  .top-row {{ display:grid; grid-template-columns:1fr 1fr; gap:1.5em; align-items:start; margin-bottom:1.5em; }}
  @media(max-width:900px) {{ .top-row {{ grid-template-columns:1fr; }} }}
  #player-wrap {{ position:relative; aspect-ratio:16/9; background:#000; border-radius:8px; overflow:hidden; }}
  #player-wrap video {{ width:100%; height:100%; }}
  #yt-link {{ position:absolute; top:0.6em; right:0.6em; background:rgba(0,0,0,0.7);
              color:#C2A878; padding:0.3em 0.8em; border-radius:4px; font-size:0.75em;
              text-decoration:none; font-family:ui-monospace,monospace; }}
  .tl-panel {{ overflow-y:auto; padding-right:0.5em; max-height:min(70vh, 500px); }}
  .tl-panel h2 {{ font-size:0.9em; font-weight:600; color:#C2A878; margin:0 0 0.5em;
                  padding-bottom:0.3em; border-bottom:1px solid #222; position:sticky;
                  top:0; background:#0d0b0b; z-index:1; }}
  .tl-row {{ padding:0.4em 0.6em; border-radius:5px; cursor:pointer; display:flex; gap:0.5em;
             border-bottom:1px solid #141210; }}
  .tl-row:hover {{ background:#1a1816; }}
  .tl-row.active {{ background:#2a2420; border-left:3px solid #C2A878; }}
  .tl-row .ts {{ font-size:0.72em; color:#C2A878; white-space:nowrap; min-width:5em; padding-top:0.15em; }}
  .tl-row .txt {{ font-size:0.82em; color:#d5cfc8; }}
  .tl-row.has-insight {{ background:#1a1510; border-left:3px solid #C2A878; padding:0.7em 0.6em; margin:0.3em 0; }}
  .insight-marker {{ display:inline-block; font-size:0.7em; font-weight:700; color:#0d0b0b;
                     background:#C2A878; padding:0.15em 0.6em; border-radius:3px;
                     font-family:ui-monospace,monospace; margin-bottom:0.35em; text-transform:uppercase; }}
  #summary {{ margin-bottom:1.5em; }}
  #summary h2 {{ font-size:1.1em; font-weight:600; color:#C2A878; margin:0 0 0.6em;
                 border-bottom:1px solid #222; padding-bottom:0.4em; }}
  .summary-body {{ background:#141210; border-radius:8px; padding:1.2em 1.5em; font-size:0.9em; line-height:1.7; }}
  .summary-body h3 {{ font-size:0.9em; font-weight:600; color:#C2A878; margin:1em 0 0.3em; }}
  .summary-body h3:first-child {{ margin-top:0; }}
  .summary-body ul {{ margin:0.3em 0 0.3em 1.5em; }}
  .key-insights {{ background:#1a1510; border-left:3px solid #C2A878; padding:0.8em 1.1em; border-radius:6px; margin-bottom:1em; }}
  .key-insights h3 {{ margin-top:0; }}
  .kf-stats {{ display:flex; flex-wrap:wrap; gap:0.7em; margin:0.6em 0; }}
  .kf-stats .stat {{ background:#0d0b0b; border:1px solid #222; border-radius:6px; padding:0.6em 0.9em; min-width:7em; }}
  .kf-stats .stat .v {{ display:block; font-size:1.3em; font-weight:700; font-family:ui-monospace,monospace; color:#C2A878; }}
  .kf-stats .stat .l {{ display:block; font-size:0.72em; color:#8a847d; margin-top:0.2em; }}
  .kf-rest {{ margin:0.4em 0 0.4em 1.2em; }}
  .placeholder {{ color:#555; font-style:italic; }}
  .relevance {{ background:#1a1510; border:1px solid #C2A878; border-radius:8px; padding:1.2em 1.5em; margin-top:1em; }}
  .relevance h3 {{ color:#C2A878; margin:0 0 0.5em; font-size:0.95em; }}
  .stats {{ display:flex; flex-wrap:wrap; gap:0.8em; margin-top:1.5em; }}
  .stat-box {{ background:#141210; border-radius:6px; padding:0.6em 1em; }}
  .stat-box .label {{ font-size:0.65em; text-transform:uppercase; letter-spacing:0.08em; color:#555; }}
  .stat-box .val {{ font-size:1.1em; font-weight:700; font-family:ui-monospace,monospace; }}
  #player-wrap iframe {{ width:100%; height:100%; border:0; }}
  #dw-yt-player {{ position:absolute; inset:0; width:100%; height:100%; }}
  #yt-poster {{ display:block; width:100%; height:100%; background-size:cover; background-position:center; position:relative; }}
  #yt-poster .yt-play {{ position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
                         width:68px; height:48px; border-radius:12px; background:rgba(20,18,16,0.78); transition:background 0.15s; }}
  #yt-poster .yt-play::after {{ content:""; position:absolute; top:50%; left:53%; transform:translate(-50%,-50%);
                                border-style:solid; border-width:11px 0 11px 18px; border-color:transparent transparent transparent #f1ebe5; }}
  #yt-poster:hover .yt-play {{ background:#C2A878; }}
  #yt-poster:hover .yt-play::after {{ border-left-color:#0d0b0b; }}
  #player-wrap.no-video {{ display:flex; align-items:center; justify-content:center; text-align:center; padding:1.5em; }}
  #player-wrap.no-video div {{ font-size:0.82em; color:#9a948c; line-height:1.6; }}
  #player-wrap.no-video strong {{ color:#C2A878; }}
  footer {{ margin-top:2.5em; padding-top:1.2em; border-top:1px solid #1a1a1a;
            display:flex; align-items:center; justify-content:center; gap:1.2em; flex-wrap:wrap; }}
  footer .made {{ font-size:0.78em; color:#777; }}
  footer .made strong {{ color:#C2A878; font-weight:600; }}
  footer .brand {{ display:inline-flex; align-items:center; color:#8a847d; transition:color 0.15s; text-decoration:none; }}
  footer .brand:hover {{ color:#C2A878; }}
  footer .starks-logo {{ height:1.4em; width:auto; display:block; }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>{_esc(title)}</h1>
    <div class="meta">
      {"<span>" + _esc(uploader) + "</span>" if uploader else ""}
      <span>{fmt_time(duration)}</span>
      <span>{transcript.get('segment_count',0)} {lbl["segments"]}</span>
      <span>{total_time:.0f}s {lbl["local_suffix"]}</span>
    </div>
  </header>

  <div class="top-row">
    {video_block}
    <div class="tl-panel">
      <h2>{lbl["transcript"]}</h2>
      {"".join(tl_aud)}
    </div>
  </div>

  {summary_html}

  <div class="stats">
    <div class="stat-box"><div class="label">Vision</div><div class="val">{_esc(str(vision.get('model','n/a')).split('-')[0])}</div></div>
    <div class="stat-box"><div class="label">Avg/Frame</div><div class="val">{vision.get('avg_latency_s',0)}s</div></div>
    <div class="stat-box"><div class="label">Whisper</div><div class="val">{transcript.get('latency_s',0)}s</div></div>
    <div class="stat-box"><div class="label">Scenes</div><div class="val">{frames_data.get('scene_changes_detected',0)}</div></div>
  </div>

  {footer_html}
</div>
<script>
{seek_script}
</script>
</body>
</html>"""
