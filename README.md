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

## Lokal
    SCOPE=all python3 scripts/build.py && python3 -m http.server -d site 8000
