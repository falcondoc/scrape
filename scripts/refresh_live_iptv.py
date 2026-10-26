#!/usr/bin/env python3
"""Soft probe for playlist2 (live). Never publishes empty if catalog has entries."""
from __future__ import annotations
import argparse, json, re, time, urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "live_catalog.json"
OUT_M3U = ROOT / "playlist2.m3u"
OUT_META = ROOT / "playlist2_meta.json"
UA = "VLC/3.0.18 LibVLC/3.0.18"

def load_catalog():
    if CATALOG.exists():
        try:
            d = json.loads(CATALOG.read_text(encoding="utf-8"))
            if isinstance(d, list):
                return d
        except Exception:
            pass
    return []

def save_catalog(items):
    CATALOG.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")

def parse_m3u(text):
    items = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            title = line.split(",", 1)[-1].strip() if "," in line else "Channel"
            logo, group = "", "Adult Live"
            m = re.search(r'tvg-logo="([^"]*)"', line)
            if m: logo = m.group(1)
            m = re.search(r'group-title="([^"]*)"', line)
            if m: group = m.group(1)
            j = i + 1
            stream = ""
            while j < len(lines):
                s = lines[j].strip()
                if s.startswith("http"):
                    stream = s
                    break
                if s.startswith("#EXTINF"):
                    break
                j += 1
            if stream:
                items.append({"title": title, "stream_url": stream, "thumbnail": logo, "group": group})
            i = j + 1
        else:
            i += 1
    return items

def import_url(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        text = r.read().decode("utf-8", errors="replace")
    incoming = parse_m3u(text)
    cat = {c["stream_url"]: c for c in load_catalog() if c.get("stream_url")}
    added = 0
    for it in incoming:
        u = it["stream_url"]
        if u not in cat:
            cat[u] = it
            added += 1
        else:
            cat[u].update({k: v for k, v in it.items() if v})
    save_catalog(list(cat.values()))
    print(f"import +{added} catalog={len(cat)}")
    return added

def probe(url, timeout=5.0):
    try:
        req = urllib.request.Request(
            url,
            method="GET",
            headers={"User-Agent": UA, "Accept": "*/*", "Icy-MetaData": "1"},
        )
        with urllib.request.urlopen(req, timeout=timeout) as r:
            code = getattr(r, "status", 200) or 200
            if 200 <= int(code) < 500:
                r.read(32)
                return True
    except urllib.error.HTTPError as e:
        # many IPTV servers reject HEAD/bots but still play in VLC — treat 4xx as soft-fail only
        if e.code in (401, 403, 405, 404):
            return False
        return False
    except Exception:
        return False
    return False

def write_m3u(items, note=""):
    lines = [
        "#EXTM3U",
        "#SOURCE: live_catalog",
        f"#REFRESHED: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"#ENTRIES: {len(items)}",
    ]
    if note:
        lines.append(f"#NOTE: {note}")
    lines.append("")
    for e in items:
        title = e.get("title") or "Channel"
        logo = e.get("thumbnail") or ""
        group = e.get("group") or "Adult Live"
        stream = e.get("stream_url") or ""
        lines.append(f'#EXTINF:-1 tvg-logo="{logo}" group-title="{group}",{title}')
        lines.append(stream)
        lines.append("")
    OUT_M3U.write_text("\n".join(lines), encoding="utf-8")
    OUT_META.write_text(
        json.dumps(
            {
                "name": "playlist2",
                "label": "Adult Live IPTV",
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
    ap.add_argument("--import-url", default="")
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--soft", action="store_true", default=True, help="if all probes fail, keep full catalog")
    ap.add_argument("--hard", action="store_true", help="only write alive (can empty)")
    args = ap.parse_args()
    soft = not args.hard

    if args.import_url:
        import_url(args.import_url)

    cat = load_catalog()
    if not cat:
        print("empty catalog")
        write_m3u([], "empty catalog")
        return 0

    print(f"probing {len(cat)} soft={soft}")
    t0 = time.time()
    alive = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(probe, c["stream_url"], args.timeout): c for c in cat}
        for fut in as_completed(futs):
            c = futs[fut]
            try:
                ok = fut.result()
            except Exception:
                ok = False
            if ok:
                alive.append(c)

    elapsed = time.time() - t0
    print(f"alive={len(alive)}/{len(cat)} in {elapsed:.1f}s")

    if alive:
        write_m3u(alive, f"probed alive {len(alive)}/{len(cat)}")
    elif soft:
        # CRITICAL: never publish empty playlist2
        print("all probes failed from this network — keeping full catalog in playlist2")
        write_m3u(cat, "probe unreachable from runner; catalog kept")
    else:
        write_m3u([], "hard probe empty")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
