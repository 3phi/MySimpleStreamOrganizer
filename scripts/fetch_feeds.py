#!/usr/bin/env python3
"""Liest channels.txt, holt die YouTube-RSS-Feeds und schreibt site/feed.json.

Nur Standardbibliothek. Kein API-Key, kein Login.
Exit-Code 1, wenn KEIN Kanal geladen werden konnte -> der Deploy bricht ab
und die zuletzt veröffentlichte Seite bleibt online.
"""
import json
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CHANNELS_FILE = ROOT / "channels.txt"
OUT_FILE = ROOT / "site" / "feed.json"
VIDEOS_PER_CHANNEL = 5

NS = {
    "a": "http://www.w3.org/2005/Atom",
    "yt": "http://www.youtube.com/xml/schemas/2015",
    "media": "http://search.yahoo.com/mrss/",
}
HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/130.0 Safari/537.36",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
    # Umgeht die EU-Cookie-Zustimmungsseite bei der Handle-Auflösung
    "Cookie": "SOCS=CAI; CONSENT=YES+1",
}
CHANNEL_ID_RE = re.compile(r"^UC[\w-]{22}$")


def http_get(url: str, tries: int = 3) -> bytes:
    last = None
    for attempt in range(tries):
        try:
            req = urllib.request.Request(url, headers=HEADERS)
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read()
        except (urllib.error.URLError, TimeoutError) as e:
            last = e
            # 404 ist endgültig, kein Retry
            if isinstance(e, urllib.error.HTTPError) and e.code == 404:
                break
            time.sleep(1.5 * (attempt + 1))
    raise RuntimeError(f"{url}: {last}")


def read_channel_list() -> list[str]:
    entries = []
    for line in CHANNELS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            entries.append(line)
    return entries


def resolve_channel_id(entry: str) -> str:
    if CHANNEL_ID_RE.match(entry):
        return entry
    handle = entry if entry.startswith("@") else "@" + entry
    html = http_get(f"https://www.youtube.com/{handle}").decode("utf-8", "replace")
    for pattern in (
        r'<link rel="canonical" href="https://www\.youtube\.com/channel/(UC[\w-]{22})"',
        r'"externalId":"(UC[\w-]{22})"',
        r'"channelId":"(UC[\w-]{22})"',
    ):
        m = re.search(pattern, html)
        if m:
            return m.group(1)
    raise RuntimeError(f"Kanal-ID für {handle} nicht gefunden")


def parse_feed(xml_bytes: bytes) -> tuple[str, list[dict]]:
    root = ET.fromstring(xml_bytes)
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


def fetch_channel(cid: str) -> dict:
    # UULF… = Upload-Playlist nur mit regulären Videos (ohne Shorts/Lives).
    # Undokumentiert -> Fallback auf den normalen Kanal-Feed.
    urls = [
        f"https://www.youtube.com/feeds/videos.xml?playlist_id=UULF{cid[2:]}",
        f"https://www.youtube.com/feeds/videos.xml?channel_id={cid}",
    ]
    last = None
    for url in urls:
        try:
            name, videos = parse_feed(http_get(url))
            if videos or url == urls[-1]:
                return {"name": name, "videos": videos, "shortsFiltered": "UULF" in url}
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(str(last))


def main() -> int:
    previous = {}
    if OUT_FILE.exists():
        try:
            previous = {c["id"]: c for c in json.loads(OUT_FILE.read_text())["channels"]}
        except Exception:  # noqa: BLE001
            pass

    channels, seen, ok = [], set(), 0
    for entry in read_channel_list():
        try:
            cid = resolve_channel_id(entry)
        except Exception as e:  # noqa: BLE001
            print(f"FEHLER  {entry}: {e}", file=sys.stderr)
            channels.append({"id": entry, "name": entry, "url": "", "videos": [],
                             "error": "Kanal nicht gefunden"})
            continue
        if cid in seen:
            continue
        seen.add(cid)
        item = {"id": cid, "url": f"https://www.youtube.com/channel/{cid}"}
        try:
            item.update(fetch_channel(cid))
            ok += 1
            print(f"OK      {entry} -> {cid} ({item['name']}, {len(item['videos'])} Videos)")
        except Exception as e:  # noqa: BLE001
            print(f"FEHLER  {entry} ({cid}): {e}", file=sys.stderr)
            old = previous.get(cid, {})
            item.update({"name": old.get("name", entry), "videos": old.get("videos", []),
                         "error": "Feed nicht erreichbar – zeige letzten Stand"})
        channels.append(item)
        time.sleep(0.3)  # höflich bleiben

    if ok == 0:
        print("Kein einziger Feed geladen – breche ab, alte Seite bleibt online.", file=sys.stderr)
        return 1

    OUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUT_FILE.write_text(json.dumps({
        "generated": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "channels": channels,
    }, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{ok}/{len(channels)} Kanäle -> {OUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
