#!/usr/bin/env python3
"""Refresh playlist4 from movies_catalog.json. Optional soft probe — never empty."""
from __future__ import annotations
import argparse, json, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "movies_catalog.json"
OUT_M3U = ROOT / "playlist4.m3u"
OUT_META = ROOT / "playlist4_meta.json"
UA = "VLC/3.0.18 LibVLC/3.0.18"

def load():
    if CATALOG.exists():
        try:
            d = json.loads(CATALOG.read_text(encoding="utf-8"))
            if isinstance(d, list):
                return d
        except Exception:
            pass
    return []

def probe(url, timeout=4.0):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Range": "bytes=0-1"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(16)
            return True
    except Exception:
        return False

def write(items, note=""):
    lines = [
        "#EXTM3U",
        "#SOURCE: movies_catalog",
        f"#REFRESHED: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"#ENTRIES: {len(items)}",
    ]
    if note:
        lines.append(f"#NOTE: {note}")
    lines.append("")
    for e in items:
        lines.append(
            f'#EXTINF:-1 tvg-logo="{e.get("thumbnail","")}" group-title="{e.get("group","XXX Movies")}",{e.get("title") or "Movie"}'
        )
        lines.append(e.get("stream_url") or "")
        lines.append("")
    OUT_M3U.write_text("\n".join(lines), encoding="utf-8")
    OUT_META.write_text(
        json.dumps(
            {
                "name": "playlist4",
                "label": "XXX Movies catalog",
                "entries": len(items),
                "refreshed_utc": datetime.now(timezone.utc).isoformat(),
                "note": note,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--probe", action="store_true")
    ap.add_argument("--workers", type=int, default=25)
    args = ap.parse_args()
    cat = load()
    if not cat:
        write([], "empty catalog")
        return 0
    if not args.probe:
        write(cat, "catalog as-is (no probe)")
        print(f"wrote {len(cat)} without probe")
        return 0
    alive = []
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(probe, c["stream_url"]): c for c in cat}
        for fut in as_completed(futs):
            c = futs[fut]
            try:
                if fut.result():
                    alive.append(c)
            except Exception:
                pass
    print(f"alive {len(alive)}/{len(cat)}")
    if alive:
        write(alive, f"probed {len(alive)}/{len(cat)}")
    else:
        write(cat, "probe all failed; catalog kept")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
