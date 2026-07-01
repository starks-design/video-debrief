# Video Debrief

**Sieh dir das Video nicht an — lass es dir zusammenfassen.**

Video Debrief verwandelt jedes Video — Webinar, Werbespot, Tutorial, eigenes
Recording — in Minuten in eine **Zusammenfassung** plus eine durchsuchbare
**Timeline** aus Transcript und Bildbeschreibung. Du sparst dir das Ansehen und
behältst trotzdem alles: jede Zahl, jeden eingeblendeten Text, jeden Schnitt.

Und das Beste: **alles läuft lokal.** Kein Cloud-Upload, kein API-Zwang, keine
fremden Server. Ein lokales Vision-Modell beschreibt die Bilder, Whisper
transkribiert das Audio, dein Agent schreibt die Summary. Dein Material bleibt
auf deiner Maschine.

Video Debrief ist ein **Skill für Claude Code** (läuft auch in Cursor und anderen
agentischen Systemen) — und die Python-Pipeline funktioniert genauso standalone
im Terminal.

![Beispiel-Report: eine NVIDIA-GTC-2026-Keynote als Zusammenfassung und durchsuchbare Timeline](assets/report-preview.png)

<sub>Eine 4:41 lange NVIDIA-GTC-2026-Keynote → Zusammenfassung, Key Facts und eine durchsuchbare Transcript-Timeline. **[▶ Interaktiven Report öffnen](https://htmlpreview.github.io/?https://github.com/starks-design/video-debrief/blob/main/examples/example-report.html)** (über http, damit der Player inline läuft).</sub>

---

## Was es macht (4 lokale Stufen)

1. **Download / Locate** — `yt-dlp` lädt das Video (URL) oder nimmt deine lokale Datei.
2. **Scene-Detection** — `ffmpeg` findet jeden harten Schnitt + Heartbeat-Frames in langen statischen Passagen.
3. **Transcript** — Auto-Captions, `whisper.cpp` oder `faster-whisper` (du wählst).
4. **Vision** — ein lokales Vision-Modell beschreibt jeden Scene-Frame in 5 Sätzen inkl. OCR.

Ergebnis: `report.html` (Player + klickbare Timeline + Insight-Marker + Summary)
und `debrief_result.json` (alle Rohdaten). Beispiel: `examples/example-report.html`.

---

## Schnellstart (mit Agent — empfohlen)

Wirf **`INSTALL.md`** in deinen Agenten (Claude Code o.ä.). Er erkennt dein OS,
prüft die Tools, findet dein lokales LLM-Backend, wählt ein Vision-Modell und
schreibt die `debrief.config.json`. Danach:

```
/debrief https://www.youtube.com/watch?v=…
```

oder direkt:

```bash
python3 scripts/debrief.py "https://www.youtube.com/watch?v=…"
python3 scripts/debrief.py "/pfad/zu/meinem-video.mp4"
```

---

## Manuelles Setup

### 1. ffmpeg + yt-dlp (Pflicht)

Scene-Detection, Frame-Extraktion und Audio brauchen **ffmpeg/ffprobe**, der
Download braucht **yt-dlp**.

| OS | Befehl |
|----|--------|
| macOS | `brew install ffmpeg yt-dlp` |
| Linux (Debian/Ubuntu) | `sudo apt install ffmpeg` · `pipx install yt-dlp` |
| Windows | `winget install Gyan.FFmpeg yt-dlp.yt-dlp` (oder `choco install ffmpeg yt-dlp`) |

Test: `ffmpeg -version` · `ffprobe -version` · `yt-dlp --version`.

### 2. Scene-Detection (kein extra Tool — nur Verständnis)

Video Debrief extrahiert Frames bei jedem erkannten Schnitt. Gesteuert über
`scene.threshold` in der Config (Default `0.3`):

- **Zu wenige Frames?** (cut-arme Talking-Heads/Slides) → Threshold senken, z.B. `0.2`, oder per Flag: `--scene-threshold 0.2`.
- **Zu viele Frames?** (sehr schnittlastig) → Threshold erhöhen (`0.4`–`0.5`) oder `--max-frames 80` setzen.
- `scene.heartbeat_seconds` (Default `30`) erzwingt zusätzlich alle N Sekunden einen Frame in langen statischen Passagen, damit nichts durchrutscht.

### 3. Transcript — drei Wege

Setze `whisper.mode` in der Config:

- **`auto`** (Default) — bei URLs zuerst Auto-Captions (`yt-dlp`, gratis, instant); keine Captions oder lokale Datei → Fallback `whisper.cpp`.
- **`captions`** — nur Auto-Captions. Best-effort, abhängig davon ob das Video welche hat. Für sichere Transcripte in beliebiger Sprache nimm `whisper`.
- **`whisper`** — [whisper.cpp](https://github.com/ggml-org/whisper.cpp). Installiere `whisper-cli` und ein ggml-Modell, trage den Pfad in `whisper.model_path` ein:
  ```bash
  brew install whisper-cpp          # macOS; Linux/Windows: siehe whisper.cpp README
  # ggml-Modell laden, z.B. large-v3-turbo, und Pfad in die Config:
  #   "whisper": { "mode": "whisper", "model_path": "/pfad/ggml-large-v3-turbo.bin" }
  ```
- **`faster-whisper`** — reines pip-Paket, kein C-Build:
  ```bash
  pip install faster-whisper
  # "whisper": { "mode": "faster-whisper", "model_path": "large-v3" }
  ```

### 4. Vision-Backend (lokales LLM)

Video Debrief spricht jede **OpenAI-kompatible** Chat-API an. Trage Endpoint +
Modell in `vision` ein. Drei gängige Backends:

| Backend | `vision.base_url` | `vision.backend` |
|---------|-------------------|------------------|
| **Ollama** (Default) | `http://localhost:11434/v1/chat/completions` | `ollama` |
| **LM Studio** | `http://localhost:1234/v1/chat/completions` | `lmstudio` |
| **oMLX** (Apple Silicon) | `http://localhost:8000/v1/chat/completions` | `omlx` |

> **Apple-Silicon-Tipp:** Ollama fährt Vision-Modelle über Metal. Für
> MLX-beschleunigte Vision (spürbar schneller auf M-Chips) nimm **oMLX** oder LM
> Studios MLX-Runtime — Ollamas MLX-Backend (0.19+) beschleunigt aktuell nur
> Text-Modelle.

Als `vision.model` ein **vision-fähiges** Modell eintragen (Qwen-VL- oder
Gemma-Vision-Familie). Welche Tags dein Backend kennt, listet:

```bash
curl -s http://localhost:11434/api/tags          # Ollama
curl -s http://localhost:1234/v1/models           # LM Studio
```

> **Hinweis zur Verifikation:** Diese Pipeline wurde live gegen **oMLX** getestet.
> Ollama und LM Studio nutzen dieselbe OpenAI-kompatible Schnittstelle und sind
> dokumentiert, aber **nicht live verifiziert** — exakte Modell-Tags variieren je
> nach installierter Version, prüfe sie über die obigen Endpoints.

Braucht dein Backend einen API-Key, leg ihn in eine ENV-Variable und trage deren
**Namen** in `vision.api_key_env` ein (z.B. `"OPENAI_API_KEY"`). Video Debrief liest
den Key zur Laufzeit aus der ENV — er steht nie in einer Datei.

### 5. Insights & Summary

- `insights` nutzt dasselbe (oder ein anderes) lokales LLM, um 10–15 Kernaussagen mit Timestamps zu ziehen. Abschaltbar via `"insights": { "enabled": false }`.
- `summary.engine`:
  - **`host-agent`** (Default) — die Pipeline legt einen fertigen Prompt als `SUMMARY_TODO.md` ab; dein Agent (Claude Code) schreibt die Summary in den Report. Beste Qualität, kein extra Modell nötig.
  - **`local-llm`** — die Pipeline ruft selbst ein LLM (`summary.base_url` / `summary.model`). Für Standalone-Betrieb ohne Agent.
  - **`none`** — keine Summary.

### 6. Aufräumen — was nach der Analyse bleibt (Privacy)

Video Debrief **löscht nach der Analyse das heruntergeladene Video und die
extrahierten Frame-Bilder wieder** — übrig bleiben nur der Report (`report.html`)
und die Rohdaten (`debrief_result.json`). Das ist Absicht: nichts Schweres
bleibt liegen, und sensibles Material verschwindet von der Platte, sobald es
analysiert ist.

- Gesteuert über `cleanup.delete_video` und `cleanup.delete_frames` (beide Default **an**).
- Bei **YouTube-URLs** braucht der Report keine lokale Videodatei: über einen Server / dein Dashboard (`http`) spielt er inline mit mitlaufendem Transcript; per Doppelklick (`file://`, wo YouTube Embeds blockt) zeigt er das Thumbnail, dessen Timeline-Klicks das Video auf YouTube an der jeweiligen Sekunde öffnen.
- Bei **lokalen Dateien** bleibt dein Original natürlich unberührt (es wird nie kopiert); im Report steht dann ein Hinweis, dass das Arbeitsvideo gelöscht wurde — die Timeline funktioniert trotzdem.
- Willst du Video/Frames behalten (z.B. zum Debuggen), setze die Flags auf `false`.

---

## Config-Referenz

Kopiere `debrief.config.example.json` nach `debrief.config.json` und passe an.
Suchreihenfolge: `$DEBRIEF_CONFIG` → `./debrief.config.json` → `~/.debrief/config.json`.

| Schlüssel | Bedeutung |
|-----------|-----------|
| `output_dir` | Wohin Reports geschrieben werden (Default `./debrief-output`) |
| `vision.base_url` / `.model` / `.backend` / `.api_key_env` | Vision-Endpoint, Modell, Backend-Typ, ENV-Name des Keys |
| `vision.context_window` | Wie viele vorherige Frame-Beschreibungen als Kontext (Drift-Vermeidung), Default 2 |
| `insights.*` | Endpoint/Modell/Key fürs Insight-LLM · `enabled` |
| `whisper.mode` / `.bin` / `.model_path` / `.language` | Transcript-Modus + whisper.cpp-Binary/Modell + Sprache (`auto`) |
| `summary.engine` / `.base_url` / `.model` | `host-agent` \| `local-llm` \| `none` |
| `relevance.enabled` / `.profile` | Optionaler „Relevanz für dich"-Block + dein Profil |
| `branding.footer` | Dezenter „Made with Video Debrief"-Footer im Report (Default `true`) |
| `scene.threshold` / `.heartbeat_seconds` / `.max_frames` | Scene-Detection-Tuning |
| `cleanup.delete_video` / `.delete_frames` | Nach der Analyse Video + Frames löschen (Default **an**) — nur Report + JSON bleiben |

---

## Troubleshooting

| Problem | Lösung |
|---------|--------|
| `ffmpeg/ffprobe not found` | ffmpeg installieren (siehe oben) |
| Scene-Detection liefert 0 Frames | `scene.threshold` senken (`0.2`) |
| Vision-Antwort leer / Fehler | Backend läuft? `vision.base_url` korrekt? Modell vision-fähig + gepullt? |
| `whisper-cli not in PATH` | `whisper.mode` auf `captions`/`faster-whisper` stellen oder whisper.cpp installieren |
| Summary fehlt im Report | `summary.engine`? Bei `host-agent`: `SUMMARY_TODO.md` abarbeiten lassen |

---

## Lizenz & Herkunft

Apache License 2.0 (siehe `LICENSE`) — nutzbar auch kommerziell, solange Copyright
und `NOTICE` erhalten bleiben; die Marke „Starks.Design" ist davon ausgenommen.
Gebaut von **[Starks.Design](https://starks.design)**.
Wenn dir Video Debrief hilft: behalte den dezenten Footer im Report — oder schalte
ihn via `branding.footer: false` ab. Kein Zwang.
