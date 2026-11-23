# MySimpleStreamOrganizer

Eigene YouTube-Startseite ohne Login: pro Kanal das neueste Video, kompakt mit kleinem Thumbnail.
Live: https://3phi.github.io/MySimpleStreamOrganizer/

## Ansichten
| Tab | Inhalt | Wird geladen |
|---|---|---|
| **Feed** | deine Kanäle | per ↻ oder automatisch beim Öffnen, wenn älter als 60 Min. |
| **Vorschläge** | Kanäle zum Ausprobieren – ✓ Übernehmen / ✕ Ablehnen | nur per ↻ in diesem Tab |
| **Geparkt** | ruhende Kanäle, nicht im Feed | nur per ↻ in diesem Tab |
| **Abgelehnt** | nur als Liste, wird nie geladen | – |

Kategorie-Chips filtern jede Ansicht. Über ⋯ an jedem Kanal: Status wechseln, Kategorie ändern.
Neue Kanäle: ⚙︎ → „Kanal hinzufügen“ (`@handle` oder Kanal-Link).

## Wie es funktioniert
- `channels.json` ist die einzige Quelle für Kanäle, Kategorien und Status (eine Zeile pro Kanal).
- Die Seite ändert sie nie direkt. Sie startet den Workflow `update.yml` mit zwei Eingaben:
  `ops` (Änderungen) und `scope` (welche Gruppen geladen werden). Der Workflow wendet die Änderungen an,
  committet `channels.json`, holt nur die angeforderten RSS-Feeds und veröffentlicht `data.json`.
- Videos nicht angeforderter Gruppen übernimmt der Workflow aus dem letzten veröffentlichten Stand.
- Änderungen erscheinen sofort (optimistisch) und gelten als gespeichert, sobald die neue `data.json` sie enthält.
  Unbestätigte Änderungen werden mit jedem Lauf erneut mitgeschickt (GitHub ersetzt wartende Läufe).

## Token (einmalig pro Gerät)
GitHub → Settings → Developer settings → Fine-grained tokens → Generate:
nur dieses Repo, Permission **Actions: Read and write**, sonst nichts. Auf der Seite unter ⚙︎ eintragen.
Der Token kann Workflows starten, aber keinen Code ändern; `channels.json` schreibt nur der Workflow selbst.

## Sicherheit & Missbrauchsschutz
- Ohne Token ist die Seite reine Anzeige. Besucher und Bots lösen keine Läufe aus – auch nicht den Auto-Abruf beim Öffnen.
- Workflow-Läufe starten nur: Push auf `main`, oder `workflow_dispatch` mit Schreibrecht/Token. Keine Trigger auf Pull Requests oder Issues.
- Drossel im Workflow (greift auch bei geleaktem Token): je Gruppe höchstens ein YouTube-Abruf pro
  `MIN_FETCH_INTERVAL_MIN` (Standard 10 Min.); max. 10 neue Kanäle pro Lauf, 300 gesamt; Eingaben werden validiert.
- `concurrency`: höchstens ein laufender + ein wartender Lauf.
- Geleakter Token: auf GitHub widerrufen – sofort wirkungslos. Schaden begrenzt auf Läufe starten/abbrechen und
  Kanalstatus ändern (in der Git-Historie sichtbar, rückgängig zu machen). Kein Zugriff auf Code oder Workflow.
- Alle Pages-Projekte unter `3phi.github.io` teilen sich den Browser-Speicher. Keine Fremd-Skripte in anderen
  Pages-Projekten einbinden – oder dieser Seite eine eigene (Sub-)Domain geben.

## Lokal
    SCOPE=all python3 scripts/build.py && python3 -m http.server -d site 8000
