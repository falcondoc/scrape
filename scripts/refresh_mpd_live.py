#!/usr/bin/env python3
"""Refresh playlist5 from mpd_catalog.json. Soft probe — never empty."""
from __future__ import annotations
import argparse, json, time, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "mpd_catalog.json"
OUT_M3U = ROOT / "playlist5.m3u"
OUT_META = ROOT / "playlist5_meta.json"
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

def probe(url, timeout=5.0):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            r.read(32)
            return True
    except Exception:
        return False

def write(items, note=""):
    lines = [
        "#EXTM3U",
        "#SOURCE: mpd_catalog (Dorcel/Dusk/Babes/Desire)",
        f"#REFRESHED: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"#ENTRIES: {len(items)}",
    ]
    if note:
        lines.append(f"#NOTE: {note}")
    lines.append("")
    for e in items:
        title = e.get("title") or "Channel"
        logo = e.get("thumbnail") or ""
        group = e.get("group") or "Adult Live MPD"
        stream = e.get("stream_url") or ""
        props = e.get("props") or []
        lines.append(f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group}",{title}')
        for p in props:
            lines.append(p)
        lines.append(stream)
        lines.append("")
    OUT_M3U.write_text("\n".join(lines), encoding="utf-8")
    OUT_META.write_text(
        json.dumps(
            {
                "name": "playlist5",
                "label": "Adult Live MPD (Dorcel/Dusk/Babes/Desire)",
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
    ap.add_argument("--workers", type=int, default=15)
    args = ap.parse_args()
    cat = load()
    if not cat:
        write([], "empty catalog")
        return 0
    if not args.probe:
        write(cat, "catalog as-is")
        print(f"wrote {len(cat)}")
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
        write(cat, "probe failed; catalog kept")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
