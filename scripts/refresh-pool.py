#!/usr/bin/env python3
"""
Refresh live-pool.json by pulling latest videos from configured YouTube channels.

Runs server-side (in GitHub Actions), so no CORS proxy is needed. The output is
a sidecar JSON file that the player fetches at load time.

Stdlib only — no pip install step required.
"""
import json
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

# ── Channels we pull from ──
# To add a new channel: append a dict here. `band=None` means routing by title
# keyword (use this for mixed channels like @jamsnips that post both bands).
CHANNELS = [
    {"chan": "UCdP9VYhSjhUYQRdELYCEiAA", "name": "@jamsnips",      "band": None, "snip": True},
    {"chan": "UCNMe_yeW_kCrjRImbUiQ3ZA", "name": "Goose Official", "band": "g",  "snip": False},
    {"chan": "UCDEPOd0RCvw8iSTqFpSBZLA", "name": "Phish Official", "band": "p",  "snip": False},
    {"chan": "UCAAXo0wFJD_B1tqztZLbhWg", "name": "LivePhish",      "band": "p",  "snip": False},
]

NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "yt":   "http://www.youtube.com/xml/schemas/2015",
}
FEED_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={cid}"
OUTPUT   = Path("live-pool.json")


def fetch_feed(channel_id: str) -> bytes:
    req = urllib.request.Request(
        FEED_URL.format(cid=channel_id),
        headers={"User-Agent": "Mozilla/5.0 jamhub-pool-refresher"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return r.read()


def parse_feed(xml_bytes: bytes) -> list[dict]:
    root = ET.fromstring(xml_bytes)
    items = []
    for entry in root.findall("atom:entry", NS):
        vid = (entry.findtext("yt:videoId", default="", namespaces=NS) or "").strip()
        title = (entry.findtext("atom:title", default="", namespaces=NS) or "").strip()
        published = (entry.findtext("atom:published", default="", namespaces=NS) or "")[:10]
        if re.fullmatch(r"[A-Za-z0-9_-]{11}", vid):
            items.append({"id": vid, "title": title, "published": published})
    return items


def detect_band(title: str) -> str | None:
    tl = title.lower()
    if re.search(r"\bgoose\b", tl): return "g"
    if re.search(r"\bphish\b", tl): return "p"
    return None


def detect_mix(title: str) -> bool:
    return bool(re.search(
        r"\bvol\.?\s*\d|\bmix\b|compilation|\bjoty\b|bliss jams|power jams",
        title, flags=re.I,
    ))


def clean_title(t: str) -> str:
    t = re.sub(r"\s*-\s*YouTube\s*$", "", t, flags=re.I)
    t = re.sub(r"^\s*Goose\s*[-–]\s*", "", t, flags=re.I)
    t = re.sub(r"^\s*Phish\s*[-–]\s*", "", t, flags=re.I)
    t = re.sub(r"\s*\(4K HDR\)\s*$", "", t, flags=re.I)
    return t.strip()


def main() -> int:
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "goose": [],
        "phish": [],
    }
    seen: set[str] = set()
    fetch_errors = 0

    for ch in CHANNELS:
        try:
            items = parse_feed(fetch_feed(ch["chan"]))
        except Exception as e:
            print(f"WARN: {ch['name']} ({ch['chan']}): {e}", file=sys.stderr)
            fetch_errors += 1
            continue

        kept = 0
        for it in items:
            if it["id"] in seen:
                continue
            band = ch["band"] or detect_band(it["title"])
            if not band:
                continue
            target = "goose" if band == "g" else "phish"
            is_mix = bool(ch["snip"]) and detect_mix(it["title"])
            venue  = ch["name"] + (f" · {it['published']}" if it["published"] else "")
            out[target].append({
                "id":    it["id"],
                "title": clean_title(it["title"]),
                "venue": venue,
                "date":  it["published"],
                "b":     band,
                "snip":  bool(ch["snip"]),
                "mix":   is_mix,
                "live":  True,
            })
            seen.add(it["id"])
            kept += 1
        print(f"  {ch['name']}: {kept} new")

    # Sort each band by date descending so newest appears first when merged.
    for key in ("goose", "phish"):
        out[key].sort(key=lambda x: x.get("date") or "", reverse=True)

    # Refuse to overwrite with an empty result if every fetch failed —
    # better to keep yesterday's pool than wipe it on a transient outage.
    if fetch_errors == len(CHANNELS):
        print("ERROR: all channel fetches failed — leaving live-pool.json untouched.",
              file=sys.stderr)
        return 1

    OUTPUT.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n",
                      encoding="utf-8")
    print(f"\nWrote {OUTPUT}: {len(out['goose'])} Goose, {len(out['phish'])} Phish")
    return 0


if __name__ == "__main__":
    sys.exit(main())
