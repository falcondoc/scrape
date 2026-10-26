#!/usr/bin/env python3
"""
Independent live adult IPTV list → playlist4.m3u

Does NOT depend on another GitHub raw file as the long-term source of truth.
Maintains a local catalog (live_catalog.json). On each run:
  - HEAD/GET probes streams in parallel
  - drops dead ones
  - writes playlist4.m3u from survivors

Optional --import-url once to seed/expand the catalog from any M3U.
"""
from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "live_catalog.json"
OUT_M3U = ROOT / "playlist4.m3u"
OUT_META = ROOT / "playlist4_meta.json"
UA = "Mozilla/5.0 (VLC/3.0) LibVLC"


def load_catalog() -> list[dict]:
    if CATALOG.exists():
        try:
            data = json.loads(CATALOG.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def save_catalog(items: list[dict]) -> None:
    CATALOG.write_text(json.dumps(items, indent=2, ensure_ascii=False), encoding="utf-8")


def parse_m3u(text: str) -> list[dict]:
    items = []
    lines = text.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if line.startswith("#EXTINF"):
            title = line.split(",", 1)[-1].strip() if "," in line else "Channel"
            logo = ""
            group = "Adult Live"
            m = re.search(r'tvg-logo="([^"]*)"', line)
            if m:
                logo = m.group(1)
            m = re.search(r'group-title="([^"]*)"', line)
            if m:
                group = m.group(1)
            j = i + 1
            stream = ""
            while j < len(lines):
                s = lines[j].strip()
                if s.startswith("http://") or s.startswith("https://"):
                    stream = s
                    break
                if s.startswith("#EXTINF"):
                    break
                j += 1
            if stream:
                items.append(
                    {
                        "title": title,
                        "stream_url": stream,
                        "thumbnail": logo,
                        "group": group,
                    }
                )
            i = j + 1
        else:
            i += 1
    return items


def import_url(url: str) -> int:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as r:
        text = r.read().decode("utf-8", errors="replace")
    incoming = parse_m3u(text)
    cat = load_catalog()
    by_url = {c["stream_url"]: c for c in cat if c.get("stream_url")}
    added = 0
    for it in incoming:
        u = it["stream_url"]
        if u not in by_url:
            by_url[u] = it
            added += 1
        else:
            by_url[u].update({k: v for k, v in it.items() if v})
    save_catalog(list(by_url.values()))
    print(f"import: +{added} (catalog size {len(by_url)})")
    return added


def probe(url: str, timeout: float = 6.0) -> bool:
    # try HEAD then short GET
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(
                url, method=method, headers={"User-Agent": UA, "Range": "bytes=0-0"}
            )
            with urllib.request.urlopen(req, timeout=timeout) as r:
                code = getattr(r, "status", 200) or 200
                if 200 <= int(code) < 400:
                    return True
        except urllib.error.HTTPError as e:
            if e.code in (200, 206, 302, 301):
                return True
            if e.code in (401, 403, 405) and method == "HEAD":
                continue
            return False
        except Exception:
            if method == "HEAD":
                continue
            return False
    return False


def write_m3u(items: list[dict]) -> None:
    lines = [
        "#EXTM3U",
        f"#SOURCE: local live_catalog (probed)",
        f"#REFRESHED: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        f"#ALIVE: {len(items)}",
        "",
    ]
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
                "name": "playlist4",
                "label": "Adult Live IPTV (probed)",
                "entries": len(items),
                "refreshed_utc": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--import-url", default="", help="one-shot seed/expand catalog from M3U URL")
    ap.add_argument("--workers", type=int, default=20)
    ap.add_argument("--timeout", type=float, default=6.0)
    ap.add_argument("--limit", type=int, default=0, help="probe at most N (0=all)")
    args = ap.parse_args()

    if args.import_url:
        import_url(args.import_url)

    cat = load_catalog()
    if not cat:
        print("catalog empty — run with --import-url once to seed")
        write_m3u([])
        return 0

    if args.limit > 0:
        cat = cat[: args.limit]

    print(f"probing {len(cat)} streams workers={args.workers}")
    t0 = time.time()
    alive = []
    dead = 0
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(probe, c["stream_url"], args.timeout): c for c in cat}
        for fut in as_completed(futs):
            c = futs[fut]
            ok = False
            try:
                ok = fut.result()
            except Exception:
                ok = False
            if ok:
                alive.append(c)
            else:
                dead += 1

    # keep dead in catalog but only write alive to m3u (catalog retains history)
    print(f"alive={len(alive)} dead={dead} elapsed={time.time()-t0:.1f}s")
    write_m3u(alive)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
