# Video Debrief — Setup (für deinen Agenten)

**Wirf diese Datei in deinen Agenten** (Claude Code, Cursor, …) mit der Bitte:
*„Richte Video Debrief nach dieser Anleitung ein."* Der Agent arbeitet die Schritte
ab, prüft dein System und schreibt am Ende eine `debrief.config.json`.

> Mensch oder Agent ohne Lust auf Automatik? Das gleiche manuell steht in
> `README.md` → „Manuelles Setup".

---

## Anweisung an den Agenten

Du richtest Video Debrief ein. Arbeite diese Schritte der Reihe nach ab, frage den
Nutzer nur dort, wo unten ausdrücklich „**frage**" steht, und bestätige
Installationen vor der Ausführung.

### 1. Betriebssystem erkennen
Ermittle das OS (`uname -s`, unter Windows `$OS`/PowerShell). Wähle danach den
passenden Paketmanager: macOS → `brew`, Debian/Ubuntu → `apt` + `pipx`,
Fedora → `dnf`, Windows → `winget`/`choco`.

### 2. Basis-Tools prüfen + ggf. installieren
Prüfe `ffmpeg`, `ffprobe`, `yt-dlp` (`command -v` / `where`). Fehlt etwas,
**schlage den OS-passenden Install-Befehl vor und führe ihn nach Bestätigung aus.**

### 3. Transcript-Engine wählen
- Prüfe, ob `whisper-cli` (whisper.cpp) auf dem `PATH` ist.
- Prüfe, ob `faster-whisper` als Python-Paket installiert ist.
- **Entscheidungslogik:**
  - whisper.cpp vorhanden → `whisper.mode = "auto"`, `whisper.bin = "whisper-cli"`, frage nach dem ggml-Modellpfad bzw. biete an, eines zu laden → `whisper.model_path`.
  - sonst faster-whisper vorhanden (oder installierbar) → `whisper.mode = "faster-whisper"`, `whisper.model_path = "large-v3"`.
  - sonst (nur URL-Videos mit Captions) → `whisper.mode = "captions"` und weise darauf hin, dass lokale Dateien dann kein Transcript bekommen.

### 4. Lokales LLM-Backend finden
Probe die gängigen Endpoints und liste die verfügbaren Modelle:
```bash
curl -s http://localhost:11434/api/tags        # Ollama
curl -s http://localhost:1234/v1/models          # LM Studio
curl -s http://localhost:8000/v1/models          # oMLX
```
Nimm das erste antwortende Backend. Setze `vision.base_url` (…/v1/chat/completions)
und `vision.backend` (`ollama` | `lmstudio` | `omlx`) entsprechend.
Braucht das Backend einen Key: leg ihn in eine ENV-Variable und trage deren
**Namen** in `vision.api_key_env` ein (niemals den Key selbst in die Datei).

### 5. Vision-Modell wählen — mit Fallback
Wähle aus der Modell-Liste ein **vision-fähiges** Modell und trage es als
`vision.model` ein. **Fallback-Kette (passend zum Backend):**
1. ein bereits installiertes Qwen-VL-Modell,
2. sonst ein installiertes Gemma-Vision-Modell,
3. sonst empfiehl dem Nutzer, eins zu pullen (nenne ein konkretes, **gegen die
   Live-Modell-Liste des Backends verifiziertes** Tag — rate keine Tags).

Setze `insights` standardmäßig auf dasselbe Backend/Modell (oder ein leichtes
Text-Modell, falls vorhanden).

### 6. Relevanz-Block — **frage** den Nutzer
Stelle wörtlich:

> „Soll Video Debrief jede Zusammenfassung mit einem **Relevanz-Block für deinen
> Kontext** ergänzen — also einschätzen, was das Video *für dich / dein Business*
> bedeutet? (j/n)"

- **ja** → frage: „Beschreib in 1–3 Sätzen, womit du arbeitest / was dich interessiert." → in `relevance.profile`, `relevance.enabled = true`.
- **nein** → `relevance.enabled = false` (Summary bleibt neutral).

### 7. Config schreiben + Smoke-Test
- Schreibe `debrief.config.json` (Basis: `debrief.config.example.json`, mit den ermittelten Werten).
- Führe einen Smoke-Test aus:
  ```bash
  python3 scripts/debrief.py "samples/30s-demo.mp4"
  ```
- Erwartung: `debrief_result.json` enthält `transcript` + `vision`, und
  `report.html` wurde geschrieben. Ist `summary.engine = host-agent`, findest du
  eine `SUMMARY_TODO.md` — schreibe die Summary und setze sie in den Report ein.
- Öffne `report.html` und melde dem Nutzer: fertig.

Wenn ein Schritt scheitert, **stopp und melde das konkrete Problem** statt zu raten.
