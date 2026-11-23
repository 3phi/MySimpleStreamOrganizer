#!/usr/bin/env python3
"""Wendet Änderungen auf channels.json an, holt die angeforderten Feeds und schreibt site/data.json.

Steuerung über Umgebungsvariablen (setzt der Workflow):
  OPS    JSON-Liste von Änderungen, die die Seite schickt, z. B.
         [{"id": "UC…", "status": "parked"}, {"handle": "@neu", "status": "active", "category": "tech"}]
  SCOPE  Abzurufende Gruppen: "active", "parked", "suggested" (kommagetrennt), "all" oder "none"
  PREV   Pfad zur zuletzt veröffentlichten data.json – Videos nicht abgerufener Gruppen bleiben so erhalten

Nur Standardbibliothek. Kein API-Key, kein YouTube-Login.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CONFIG = ROOT / "channels.json"
OUT = ROOT / "site" / "data.json"

STATUSES = ("active", "suggested", "parked", "rejected")
FETCHABLE = ("active", "suggested", "parked")       # "rejected" wird nie geladen
VIDEOS_PER_CHANNEL = 5
MAX_OPS = 300
WORKERS = 6
# Schutz vor zu häufigem Abrufen – greift serverseitig, egal wer den Lauf auslöst
MIN_FETCH_INTERVAL_MIN = int(os.environ.get("MIN_FETCH_INTERVAL_MIN", "10"))  # pro Gruppe
MAX_NEW_PER_RUN = 10      # neue Kanäle pro Lauf
MAX_CHANNELS = 300        # Obergrenze gesamt

ID_RE = re.compile(r"^UC[\w-]{22}$")
HANDLE_RE = re.compile(r"^@[\w.\-]{3,30}$")
NS = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015",
      "media": "http://search.yahoo.com/mrss/"}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    "Cookie": "SOCS=CAI; CONSENT=YES+1",  # umgeht die EU-Zustimmungsseite
}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def log(*a):
    print(*a, flush=True)


# ---------------------------------------------------------------- HTTP / YouTube
def http_get(url: str, tries: int = 3) -> bytes:
    last = None
    for attempt in range(tries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=HEADERS), timeout=15) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            if isinstance(e, urllib.error.HTTPError) and e.code == 404:
                break
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def resolve_handle(handle: str) -> str:
    """@handle -> Kanal-ID. Prüft, dass die Seite wirklich zu diesem Handle gehört."""
    html = http_get(f"https://www.youtube.com/{handle}").decode("utf-8", "replace")
    vanity = re.search(r'"vanityChannelUrl":"https?://www\.youtube\.com/(@[^"]+)"', html)
    if vanity and vanity.group(1).lower() != handle.lower():
        raise RuntimeError(f"Seite gehört zu {vanity.group(1)}, nicht zu {handle}")
    for pat in (r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"',
                r'"externalId":"(UC[\w-]{22})"',
                r'<meta property="og:url" content="https://www\.youtube\.com/channel/(UC[\w-]{22})"'):
        m = re.search(pat, html)
        if m:
            return m.group(1)
    raise RuntimeError(f"Kanal-ID für {handle} nicht gefunden")


def parse_feed(xml: bytes) -> tuple[str, list[dict]]:
    root = ET.fromstring(xml)
    name = root.findtext("a:author/a:name", default="", namespaces=NS)
    videos = []
    for e in root.findall("a:entry", NS)[:VIDEOS_PER_CHANNEL]:
        stats = e.find("media:group/media:community/media:statistics", NS)
        videos.append({
            "id": e.findtext("yt:videoId", namespaces=NS),
            "title": e.findtext("a:title", default="", namespaces=NS),
            "published": e.findtext("a:published", default="", namespaces=NS),
            "views": int(stats.get("views", 0)) if stats is not None else None,
        })
    return name, videos


def fetch_channel(cid: str) -> tuple[str, list[dict]]:
    # UULF… = Upload-Playlist ohne Shorts/Lives (undokumentiert) -> Fallback auf Kanal-Feed
    urls = [f"https://www.youtube.com/feeds/videos.xml?playlist_id=UULF{cid[2:]}",
            f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}"]
    last = None
    for url in urls:
        try:
            name, videos = parse_feed(http_get(url))
            if videos or url == urls[-1]:
                return name, videos
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(str(last))


# ---------------------------------------------------------------- Konfiguration
def load_config() -> dict:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    cats = {c["id"] for c in cfg["categories"]}
    for c in cfg["channels"]:
        if c.get("status") not in STATUSES:
            raise SystemExit(f"Ungültiger Status bei {c}")
        if c.get("category") not in cats:
            raise SystemExit(f"Unbekannte Kategorie bei {c}")
    return cfg


def save_config(cfg: dict) -> None:
    """Eine Zeile pro Kanal, stabil sortiert -> lesbare Git-Diffs."""
    order = {s: i for i, s in enumerate(STATUSES)}
    cat_order = {c["id"]: i for i, c in enumerate(cfg["categories"])}
    chans = sorted(cfg["channels"], key=lambda c: (order[c["status"]], cat_order.get(c["category"], 99),
                                                    c.get("name", c.get("handle", "")).casefold()))
    keys = ("handle", "id", "name", "category", "status", "reason")
    lines = ["{", '  "categories": [']
    lines += [f"    {json.dumps(c, ensure_ascii=False)}," for c in cfg["categories"]]
    lines[-1] = lines[-1].rstrip(",")
    lines += ["  ],", '  "channels": [']
    for c in chans:
        ordered = {k: c[k] for k in keys if c.get(k)}
        lines.append(f"    {json.dumps(ordered, ensure_ascii=False)},")
    lines[-1] = lines[-1].rstrip(",")
    lines += ["  ]", "}", ""]
    CONFIG.write_text("\n".join(lines), encoding="utf-8")


def apply_ops(cfg: dict, raw: str) -> bool:
    """Setzt Status/Kategorie; fügt neue @handles hinzu. Ungültiges wird verworfen, nie ausgeführt."""
    if not raw.strip():
        return False
    try:
        ops = json.loads(raw)
        assert isinstance(ops, list)
    except Exception:  # noqa: BLE001
        log("OPS ist kein gültiges JSON – ignoriert")
        return False
    cats = {c["id"] for c in cfg["categories"]}
    by_id = {c["id"]: c for c in cfg["channels"] if c.get("id")}
    by_handle = {c["handle"].lower(): c for c in cfg["channels"] if c.get("handle")}
    changed = False
    added = 0
    for op in ops[:MAX_OPS]:
        if not isinstance(op, dict):
            continue
        cid, handle = op.get("id"), op.get("handle")
        status, category = op.get("status"), op.get("category")
        if cid is not None and not (isinstance(cid, str) and ID_RE.match(cid)):
            continue
        if handle is not None and not (isinstance(handle, str) and HANDLE_RE.match(handle)):
            continue
        if status is not None and status not in STATUSES:
            continue
        if category is not None and category not in cats:
            continue
        ch = (cid and by_id.get(cid)) or (handle and by_handle.get(handle.lower()))
        if ch is None:
            if not handle and not cid:
                continue
            if added >= MAX_NEW_PER_RUN or len(cfg["channels"]) >= MAX_CHANNELS:
                log(f"LIMIT   {handle or cid} nicht hinzugefügt (max. {MAX_NEW_PER_RUN}/Lauf, {MAX_CHANNELS} gesamt)")
                continue
            added += 1
            ch = {"handle": handle, "id": cid, "category": category or cfg["categories"][-1]["id"],
                  "status": status or "active"}
            cfg["channels"].append(ch)
            if cid:
                by_id[cid] = ch
            if handle:
                by_handle[handle.lower()] = ch
            log(f"NEU     {handle or cid}")
            changed = True
            continue
        for key, val in (("status", status), ("category", category)):
            if val and ch.get(key) != val:
                log(f"ÄNDERUNG {ch.get('name') or ch.get('handle')}: {key} {ch.get(key)} -> {val}")
                ch[key] = val
                changed = True
        if ch.get("status") == "active":
            ch.pop("reason", None)   # Begründung nur für Vorschläge relevant
    return changed


def resolve_missing(cfg: dict) -> bool:
    """Neue Handles in IDs auflösen; Dubletten (gleiche ID) zusammenführen."""
    changed = False
    for ch in list(cfg["channels"]):
        if ch.get("id") or ch["status"] == "rejected":
            continue
        try:
            ch["id"] = resolve_handle(ch["handle"])
            changed = True
        except Exception as e:  # noqa: BLE001
            log(f"FEHLER  {ch['handle']}: {e}")
            ch["error"] = "Kanal nicht gefunden"
            continue
        twin = next((c for c in cfg["channels"] if c is not ch and c.get("id") == ch["id"]), None)
        if twin:   # Handle war schon als anderer Eintrag vorhanden -> Änderung übernehmen, Duplikat entfernen
            twin["status"], twin["category"] = ch["status"], ch["category"]
            cfg["channels"].remove(ch)
    return changed


# ---------------------------------------------------------------- Ablauf
def minutes_since(iso) -> float:
    try:
        return (datetime.now(timezone.utc) - datetime.fromisoformat(iso)).total_seconds() / 60
    except Exception:  # noqa: BLE001
        return float("inf")


def parse_scope(raw: str) -> set[str]:
    parts = {p.strip().lower() for p in (raw or "active").split(",") if p.strip()}
    if "all" in parts:
        return set(FETCHABLE)
    return parts & set(FETCHABLE)


def main() -> int:
    cfg = load_config()
    changed = apply_ops(cfg, os.environ.get("OPS", ""))
    changed |= resolve_missing(cfg)
    scope = parse_scope(os.environ.get("SCOPE", "active"))

    prev = {}
    prev_path = os.environ.get("PREV")
    if prev_path and Path(prev_path).exists():
        try:
            prev = json.loads(Path(prev_path).read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            log("Vorheriger Stand unlesbar – starte leer")
    prev_videos = prev.get("videos", {}) if isinstance(prev, dict) else {}
    scopes = prev.get("scopes", {}) if isinstance(prev, dict) else {}

    # Drossel: Gruppen, die vor weniger als MIN_FETCH_INTERVAL_MIN Minuten geladen wurden, nicht erneut abrufen.
    # Ausnahme: Kanäle ohne jegliche Daten (z. B. gerade hinzugefügt) – begrenzt durch MAX_NEW_PER_RUN.
    throttled = set()
    for s in scope:
        age = minutes_since(scopes.get(s, {}).get("at"))
        if age < MIN_FETCH_INTERVAL_MIN:
            throttled.add(s)
            log(f"{s}: gedrosselt – zuletzt vor {age:.1f} Min. geladen (Minimum {MIN_FETCH_INTERVAL_MIN})")
    targets = [c for c in cfg["channels"] if c.get("id") and c["status"] in scope
               and (c["status"] not in throttled or not prev_videos.get(c["id"], {}).get("videos"))]
    log(f"Abruf: {', '.join(sorted(scope - throttled)) or '–'} ({len(targets)} Kanäle)")

    def work(ch):
        try:
            return ch, *fetch_channel(ch["id"]), None
        except Exception as e:  # noqa: BLE001
            return ch, None, None, str(e)

    stamp = now()
    videos: dict[str, dict] = {}
    # Bestehende Daten übernehmen (nur für Kanäle, die noch existieren und nicht abgelehnt sind)
    live_ids = {c["id"] for c in cfg["channels"] if c.get("id") and c["status"] != "rejected"}
    for cid, entry in prev_videos.items():
        if cid in live_ids:
            videos[cid] = entry
    stats: dict[str, dict] = {}
    with ThreadPoolExecutor(WORKERS) as ex:
        for ch, name, vids, err in ex.map(work, targets):
            s = stats.setdefault(ch["status"], {"ok": 0, "failed": 0})
            if err:
                s["failed"] += 1
                log(f"FEHLER  {ch.get('name') or ch['handle']}: {err[:150]}")
                old = videos.get(ch["id"], {})
                videos[ch["id"]] = {**old, "error": "Feed nicht erreichbar – zeige letzten Stand"}
                continue
            s["ok"] += 1
            videos[ch["id"]] = {"fetched": stamp, "videos": vids}
            if name and not ch.get("name"):
                ch["name"] = name
                changed = True
    for s in scope:
        st = stats.get(s, {"ok": 0, "failed": 0})
        if s in throttled:   # "checked" zeigt der Seite, dass der Lauf fertig ist; "at" bleibt der letzte echte Abruf
            scopes[s] = {**scopes.get(s, {}), "checked": stamp, "throttled": True}
        else:
            scopes[s] = {"at": stamp, "checked": stamp, **st, "throttled": False}
            log(f"{s}: {st['ok']} ok, {st['failed']} Fehler")

    if changed:
        save_config(cfg)
        log("channels.json geändert")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    public_cfg = {"categories": cfg["categories"],
                  "channels": [{k: v for k, v in c.items()} for c in cfg["channels"]]}
    OUT.write_text(json.dumps({"generated": stamp, "scopes": scopes, "limits": {"minFetchIntervalMin": MIN_FETCH_INTERVAL_MIN},
                               "config": public_cfg, "videos": videos},
                              ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log(f"-> {OUT} ({OUT.stat().st_size // 1024} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
