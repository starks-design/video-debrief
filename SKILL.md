---
name: debrief
description: Verwandelt ein Video (URL oder lokale Datei) komplett lokal in eine Zusammenfassung plus durchsuchbare Timeline aus Transcript und Bildbeschreibung. Scene-Detection (ffmpeg) findet jeden Schnitt, ein lokales Vision-Modell beschreibt jeden Frame inkl. OCR, Whisper transkribiert das Audio. Kein Cloud-Upload. Trigger bei /debrief <url-oder-pfad> oder wenn ein Video tief analysiert werden soll.
argument-hint: "<video-url-oder-pfad>"
allowed-tools: Bash, Read, Write
license: Apache-2.0
user-invocable: true
---

# /debrief — Video-Tiefenanalyse, komplett lokal

Spar dir das ganze Video. Video Debrief macht aus einem Clip in Minuten eine
**Zusammenfassung** plus eine klickbare **Timeline** (was gesagt wird + was im
Bild passiert). Alles läuft auf der eigenen Maschine — kein Upload, kein
API-Zwang.

## Voraussetzungen

Einmalig einrichten — wirf dafür `INSTALL.md` in deinen Agenten, der prüft dein
System und schreibt die `debrief.config.json`. Kurzform:

- `ffmpeg`, `ffprobe`, `yt-dlp` auf dem `PATH`
- Ein lokales LLM mit OpenAI-kompatibler API (Ollama / LM Studio / oMLX) für die
  Bildbeschreibung — Endpoint + Modell stehen in der Config
- Transcript: Auto-Captions (yt-dlp), whisper.cpp **oder** faster-whisper
- `debrief.config.json` (aus `debrief.config.example.json` erzeugt)

## Was der Agent bei /debrief tun soll

1. **URL/Pfad** aus dem Prompt nehmen.
2. **Config prüfen** — existiert `debrief.config.json`? Wenn nicht → `INSTALL.md`
   abarbeiten (Setup), sonst nicht erneut fragen.
3. **Pipeline starten:**
   ```bash
   python3 scripts/debrief.py "<URL_ODER_PFAD>"
   ```
   Das macht: Download/Locate → Scene-Detection → Transcript → Vision-Beschreibung
   → Insights → schreibt `debrief_result.json` + `report.html` in den Output-Ordner.
4. **Summary schreiben (nur wenn `summary.engine` = `host-agent`):** Es liegt dann
   eine `SUMMARY_TODO.md` im Output-Ordner mit einem fertigen Prompt. Lies
   `debrief_result.json`, schreibe die Zusammenfassung anhand des Prompts und
   ersetze den Platzhalter-Block `<section id="summary">…</section>` in `report.html`.
   (Bei `summary.engine` = `local-llm` erledigt das Tool die Summary selbst.)
5. **Report öffnen:**
   ```bash
   open "<OUTPUT>/report.html"   # macOS · Linux: xdg-open · Windows: start
   ```

## Relevanz-Block (optional)

Ist im Setup `relevance.enabled` aktiviert, ergänzt die Summary einen
„Relevanz für dich"-Block, der das Video gegen das im Setup hinterlegte Profil
einschätzt. Standardmäßig **aus** — dann bleibt die Summary neutral.

## Nützliche Flags

```bash
python3 scripts/debrief.py "<src>" --no-vision        # nur Transcript
python3 scripts/debrief.py "<src>" --no-whisper       # nur Bildanalyse
python3 scripts/debrief.py "<src>" --scene-threshold 0.2   # mehr Frames (cut-arme Videos)
python3 scripts/debrief.py "<src>" --out-dir ./mein-report
python3 scripts/debrief.py "<src>" --resume           # fehlende Vision-Frames nachholen
```

## Output

| Datei | Inhalt |
|-------|--------|
| `report.html` | Video-Player + klickbare Transcript-Timeline + Insight-Marker + Summary |
| `debrief_result.json` | Rohdaten: Transcript-Segmente, Frame-Beschreibungen, Insights |
| `SUMMARY_TODO.md` | (nur host-agent-Modus) Prompt für die Zusammenfassung |

## Privacy — räumt hinter sich auf

Nach der Analyse löscht Video Debrief das heruntergeladene Video und die Frame-Bilder
wieder (`cleanup.delete_video` / `delete_frames`, Default an) — nur `report.html` +
`debrief_result.json` bleiben. YouTube-Videos braucht der Report ohne lokale Datei:
über `http(s)` inline mit Transcript-Sync, per `file://` als Thumbnail mit Deeplinks
zur jeweiligen Stelle.

Details zu Setup, Modellen und Troubleshooting: `README.md`.
