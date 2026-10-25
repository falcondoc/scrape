#!/usr/bin/env python3
"""
Build master M3U from pornhao.com — grouped by performer.
Tokens expire; intended for periodic GitHub Actions refresh.

Usage:
  python build_master_m3u.py                     # top models (MAX_MODELS)
  python build_master_m3u.py --performer "Angela White" "Brandi Love"
  python build_master_m3u.py -p angela-white brandi-love
"""

from __future__ import annotations

import argparse
import re
import sys
import time
import json
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

BASE = "https://pornhao.com"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)
OUT_M3U = Path("playlist.m3u")
OUT_JSON = Path("playlist.json")
MAX_MODELS = 30
MAX_PAGES_PER_MODEL = 5
MIN_VIDEOS = 1
SLEEP = 0.2

STUDIO_HINTS = {
    "vixen": "Vixen", "blacked": "Blacked", "tushy": "Tushy",
    "deeper": "Deeper", "slayed": "Slayed", "milfy": "Milfy",
    "wifey": "Wifey", "blackedraw": "BlackedRaw", "tushyraw": "TushyRaw",
}


def fetch(url: str, timeout: int = 22) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9"}
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode("utf-8", errors="replace")


def fetch_safe(url: str, retries: int = 2) -> str | None:
    for attempt in range(retries + 1):
        try:
            return fetch(url)
        except Exception as e:
            if attempt == retries:
                print(f"  FAIL {url[:70]} -> {e}", file=sys.stderr)
                return None
            time.sleep(1.0 * (attempt + 1))
    return None


def slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "-", s)
    return s.strip("-")


def clean_title(raw: str, performer: str | None = None) -> str:
    """Strip garbage, site suffixes, ellipses, make readable."""
    if not raw:
        return "Untitled"
    t = raw.strip()
    # cut common site / SEO tails
    for sep in (" - Porn", " - Free", " | ", " — ", " – "):
        if sep in t:
            t = t.split(sep)[0]
    t = re.sub(r"\s+", " ", t)
    # kill trailing dots / ellipsis spam
    t = re.sub(r"[\.…]+$", "", t).strip()
    # strip leftover .mp4 / .xxx style junk if any leaked in
    t = re.sub(r"\.(mp4|avi|mkv|xxx|com)\b", "", t, flags=re.I)
    # collapse multi-spaces and weird punctuation gaps
    t = re.sub(r"\s*([,;:!?])\s*", r"\1 ", t)
    t = re.sub(r"\s+", " ", t).strip(" -_|")
    # optional: drop performer name prefix if it just repeats the group
    if performer:
        p = performer.strip()
        if t.lower().startswith(p.lower()):
            t = t[len(p):].lstrip(" :-–—|")
    if len(t) < 3:
        return raw.strip()[:120]
    # title-case only when it looks like a slug (all lower / dashed)
    if re.fullmatch(r"[a-z0-9 \-]+", t):
        t = t.replace("-", " ").title()
    return t[:160]


def list_models(limit: int = MAX_MODELS) -> list[tuple[str, str]]:
    models, seen = [], set()
    for seed in [f"{BASE}/models/", f"{BASE}/models/?s=count"]:
        html = fetch_safe(seed)
        if not html:
            continue
        for m in re.finditer(r'href="https?://[^"]*?/models/([a-z0-9-]+)/?"', html):
            slug = m.group(1)
            if slug.isdigit() or slug in seen or len(slug) < 2:
                continue
            seen.add(slug)
            models.append((slug, slug.replace("-", " ").title()))
            if len(models) >= limit:
                return models
    return models


def resolve_performers(names: list[str]) -> list[tuple[str, str]]:
    """Map human names or slugs to (slug, display_name)."""
    out = []
    for n in names:
        n = n.strip()
        if not n:
            continue
        slug = slugify(n)
        # verify page exists; if not, still keep slug
        html = fetch_safe(f"{BASE}/models/{slug}/")
        if html and ("404" in html[:400] or "not found" in html[:400].lower()):
            print(f"  warn: no page for {slug}, skipping", file=sys.stderr)
            continue
        display = n if " " in n or n != slug else slug.replace("-", " ").title()
        # prefer title-cased words from the page h1 when available
        if html:
            hm = re.search(r"<h1[^>]*>([^<]+)</h1>", html, re.I)
            if hm:
                display = hm.group(1).strip()
        out.append((slug, display))
    return out


def model_video_pages(slug: str) -> list[str]:
    urls, seen = [], set()
    for page in range(1, MAX_PAGES_PER_MODEL + 1):
        page_url = f"{BASE}/models/{slug}/" if page == 1 else f"{BASE}/models/{slug}/{page}/"
        html = fetch_safe(page_url)
        if not html:
            break
        found = re.findall(r'href="(https://pornhao\.com/video/[^"]+-(\d+)/)"', html)
        if not found:
            break
        for full, _ in found:
            if full not in seen:
                seen.add(full)
                urls.append(full)
        if page > 1 and f"/models/{slug}/{page + 1}/" not in html:
            break
        time.sleep(0.1)
    return urls


def extract_stream(video_page_url: str, performer: str | None = None) -> dict | None:
    html = fetch_safe(video_page_url)
    if not html:
        return None
    all_mp4 = re.findall(
        r'(https://video\d+\.pornocdn\.info/zak/[^"\s,]+?\.mp4\?st=[A-Za-z0-9_-]+&e=\d+)',
        html,
    )
    if not all_mp4:
        return None
    best = next((u for u in all_mp4 if "own_1080p" in u or "/own3/" in u), all_mp4[0])
    vid_m = re.search(r"-(\d+)/?$", video_page_url.rstrip("/"))
    vid = vid_m.group(1) if vid_m else "0"

    title = None
    tm = re.search(r"<title>([^<]+)</title>", html, re.I)
    if tm:
        title = tm.group(1)
    if not title or len(title) < 4:
        slug = video_page_url.rstrip("/").split("/")[-1]
        title = slug.rsplit("-", 1)[0].replace("-", " ")
    title = clean_title(title, performer=performer)

    logo = f"https://pornhao.com/images/{vid}.jpg"
    studio = None
    low = html[:6000].lower()
    for key, label in STUDIO_HINTS.items():
        if key in low:
            studio = label
            break
    return {"id": vid, "title": title, "url": best, "logo": logo, "studio": studio}


def process_model(item: tuple[str, str]) -> tuple[str, str, list[dict]]:
    slug, name = item
    print(f"[model] {name}", flush=True)
    pages = model_video_pages(slug)
    videos = []
    with ThreadPoolExecutor(max_workers=5) as ex:
        futs = [ex.submit(extract_stream, u, name) for u in pages]
        for fut in as_completed(futs):
            try:
                data = fut.result()
                if data:
                    videos.append(data)
            except Exception:
                pass
    videos.sort(key=lambda v: int(v["id"]), reverse=True)
    print(f"  -> {len(videos)} streams", flush=True)
    return slug, name, videos


def write_m3u(groups: list[tuple[str, str, list[dict]]]) -> int:
    lines = ["#EXTM3U"]
    total = 0
    for slug, name, videos in groups:
        if len(videos) < MIN_VIDEOS:
            continue
        for v in videos:
            # pure performer grouping (studio optional as secondary tag)
            group = name
            title = v["title"].replace("\n", " ").replace(",", " ")
            lines.append(
                f'#EXTINF:-1 tvg-id="{slug}" tvg-name="{name}" '
                f'tvg-logo="{v.get("logo", "")}" group-title="{group}",{title}'
            )
            lines.append(v["url"])
            total += 1
    OUT_M3U.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return total


def main() -> None:
    global MAX_PAGES_PER_MODEL

    ap = argparse.ArgumentParser(description="Build performer-grouped master M3U from pornhao")
    ap.add_argument(
        "-p", "--performer",
        nargs="+",
        help='Specific performers, e.g. -p "Angela White" "Brandi Love" or -p angela-white',
    )
    ap.add_argument("--max-models", type=int, default=MAX_MODELS)
    ap.add_argument("--pages", type=int, default=MAX_PAGES_PER_MODEL)
    args = ap.parse_args()

    MAX_PAGES_PER_MODEL = args.pages

    if args.performer:
        print(f"== performer mode: {args.performer} ==")
        models = resolve_performers(args.performer)
        if not models:
            print("no valid performers resolved", file=sys.stderr)
            sys.exit(1)
    else:
        print("== listing models ==")
        models = list_models(args.max_models)

    print(f"models queued: {len(models)}")
    groups = []
    for i, item in enumerate(models):
        try:
            groups.append(process_model(item))
        except Exception as e:
            print(f"model fail {item}: {e}", file=sys.stderr)
        time.sleep(SLEEP)
        if (i + 1) % 5 == 0:
            print(f"-- {i + 1}/{len(models)} --", flush=True)

    groups.sort(key=lambda g: len(g[2]), reverse=True)
    total = write_m3u(groups)
    meta = {
        "models": len(groups),
        "videos": total,
        "generated": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "source": BASE,
        "mode": "performer" if args.performer else "top",
        "performers": [n for _, n, _ in groups],
        "top": [{"slug": s, "name": n, "count": len(vs)} for s, n, vs in groups[:20]],
    }
    OUT_JSON.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"DONE -> {OUT_M3U} ({total} entries)")


if __name__ == "__main__":
    main()
