# MySimpleStreamOrganizer

Statische Seite: pro Kanal das neueste Video mit Thumbnail, dazu 4 ältere zum Aufklappen.
Ein GitHub-Action-Job holt alle 30 Min. die öffentlichen RSS-Feeds (kein API-Key, kein Login)
und veröffentlicht `feed.json` + `index.html` auf GitHub Pages.

## Setup (ca. 5 Min.)
1. Neues Repo auf GitHub anlegen, Inhalt dieses Ordners pushen (Branch `main`).
2. Repo → Settings → Pages → Source: **GitHub Actions**.
3. `channels.txt` bearbeiten (eine Zeile pro Kanal: `@handle` oder `UC…`-ID) und committen.
   Jeder Push löst den Build aus; manuell auch über Actions → „Run workflow“.
4. URL `https://<user>.github.io/<repo>/` in Brave öffnen und als Favorit / Start-Kachel speichern.

## Lokal testen
    python3 scripts/fetch_feeds.py && python3 -m http.server -d site 8000

## Hinweise
- Shorts werden über die undokumentierte `UULF…`-Playlist ausgefiltert; fällt das weg,
  greift automatisch der normale Kanal-Feed (dann inkl. Shorts).
- Fällt ein Kanal aus, bleibt sein letzter Stand mit Warnhinweis stehen. Schlagen *alle* fehl,
  wird nicht deployt – die alte Seite bleibt online.
- „Gesehen“-Status liegt im localStorage des Browsers (pro Gerät).
- Pages auf GitHub Free braucht ein öffentliches Repo → deine Kanalliste ist dann öffentlich.
