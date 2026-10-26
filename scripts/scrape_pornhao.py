#!/usr/bin/env python3
"""Independent Pornhao performer scraper → playlist3.m3u (HTTP only, fast)."""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://pornhao.com"
OUT_M3U = ROOT / "playlist3.m3u"
OUT_JSON = ROOT / "playlist3.json"
OUT_META = ROOT / "playlist3_meta.json"
PERFORMERS = ROOT / "performers.txt"

UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
DEFAULT_MODELS = [
    "angela-white",
    "brandi-love",
    "lana-rhoades",
    "riley-reid",
    "abella-danger",
    "adriana-chechik",
    "alexis-fawx",
    "nicole-aniston",
    "violet-myers",
    "mia-khalifa",
]


def fetch(url: str, timeout: int = 18) -> str | None:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Referer": BASE + "/"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"  FAIL {url[:70]} {e}", file=sys.stderr)
        return None


def slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def load_models(cli: list[str] | None, limit: int) -> list[str]:
    if cli:
        return [slugify(x) for x in cli if x.strip()]
    if PERFORMERS.exists():
        lines = []
        for ln in PERFORMERS.read_text(encoding="utf-8").splitlines():
            ln = ln.split("#", 1)[0].strip()
            if ln:
                lines.append(slugify(ln))
        if lines:
            return lines[:limit]
    return DEFAULT_MODELS[:limit]


def video_links(html: str) -> list[str]:
    found = re.findall(r'href=["\']([^"\']+/video/[^"\']+)["\']', html, re.I)
    out, seen = [], set()
    for h in found:
        full = urljoin(BASE, h)
        if full not in seen and "/video/" in full:
            seen.add(full)
            out.append(full)
    return out


def parse_video(page_url: str) -> dict | None:
    html = fetch(page_url)
    if not html:
        return None
    title = "Untitled"
    m = re.search(r"<title>([^<]+)</title>", html, re.I)
    if m:
        title = re.sub(r"\s*[-|].*$", "", m.group(1)).strip() or title
    thumb = ""
    m = re.search(r'property=["\']og:image["\'][^>]+content=["\']([^"\']+)', html, re.I)
    if not m:
        m = re.search(r'content=["\']([^"\']+)["\'][^>]+property=["\']og:image["\']', html, re.I)
    if m:
        thumb = m.group(1)
    stream = None
    m = re.search(r'<video[^>]+src=["\']([^"\']+)', html, re.I)
    if m:
        stream = m.group(1).replace("&amp;", "&")
    if not stream:
        m = re.search(r'(https?://[^\s"\'<>]+pornocdn[^\s"\'<>]+\.mp4[^\s"\'<>]*)', html, re.I)
        if m:
            stream = m.group(1).replace("&amp;", "&")
    if not stream:
        m = re.search(r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)', html, re.I)
        if m:
            stream = m.group(1).replace("&amp;", "&")
    if not stream:
        return None
    return {"title": title, "stream_url": stream, "page_url": page_url, "thumbnail": thumb}


def scrape_model(slug: str, max_videos: int, pages: int) -> list[dict]:
    results = []
    seen_pages = set()
    for p in range(1, pages + 1):
        url = f"{BASE}/models/{slug}/" if p == 1 else f"{BASE}/models/{slug}/?page={p}"
        html = fetch(url)
        if not html:
            break
        links = video_links(html)
        if not links:
            break
        for link in links:
            if link in seen_pages:
                continue
            seen_pages.add(link)
            if len(results) >= max_videos:
                return results
            info = parse_video(link)
            if info:
                info["model"] = slug
                results.append(info)
            time.sleep(0.15)
    return results


def save(entries: list[dict]) -> None:
    seen = {}
    for e in entries:
        u = e.get("stream_url")
        if u:
            seen[u] = e
    entries = list(seen.values())
    OUT_JSON.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "#EXTM3U",
        f"#SOURCE: pornhao.com",
        f"#REFRESHED: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]
    for e in entries:
        model = (e.get("model") or "pornhao").replace("-", " ").title()
        title = e.get("title") or model
        logo = e.get("thumbnail") or ""
        stream = e.get("stream_url") or ""
        lines.append(
            f'#EXTINF:-1 tvg-id="{e.get("model","")}" tvg-name="{model}" tvg-logo="{logo}" group-title="{model}",{title}'
        )
        lines.append(stream)
        lines.append("")
    OUT_M3U.write_text("\n".join(lines), encoding="utf-8")
    OUT_META.write_text(
        json.dumps(
            {
                "name": "playlist3",
                "label": "Pornhao performers",
                "entries": len(entries),
                "refreshed_utc": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"saved {len(entries)} → playlist3.m3u")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("-p", "--performer", nargs="*", default=None)
    ap.add_argument("--max-models", type=int, default=8)
    ap.add_argument("--max-per-model", type=int, default=8)
    ap.add_argument("--pages", type=int, default=1)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    models = load_models(args.performer, args.max_models)
    print(f"models={len(models)} max_per={args.max_per_model} pages={args.pages}")
    t0 = time.time()
    all_e: list[dict] = []

    # sequential models, parallel video parse inside scrape_model is sequential for politeness;
    # parallelize across models lightly
    with ThreadPoolExecutor(max_workers=max(1, min(args.workers, len(models)))) as ex:
        futs = {
            ex.submit(scrape_model, m, args.max_per_model, args.pages): m for m in models
        }
        for fut in as_completed(futs):
            m = futs[fut]
            try:
                res = fut.result()
            except Exception as e:
                print(f"model {m} err {e}", file=sys.stderr)
                continue
            print(f"  {m}: {len(res)}")
            all_e.extend(res)

    save(all_e)
    print(f"elapsed {time.time()-t0:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
