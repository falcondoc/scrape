#!/usr/bin/env python3
"""Independent DesiHub scraper → playlist2.m3u (fast, no Selenium)."""
from __future__ import annotations

import argparse
import json
import logging
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
BASE = "https://desihub.org"
OUT_M3U = ROOT / "playlist2.m3u"
OUT_JSON = ROOT / "playlist2.json"
OUT_META = ROOT / "playlist2_meta.json"
STATE = ROOT / "desihub_state.json"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}
TIMEOUT = 15
WORKERS = 8

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("desihub")


def load_json(path: Path, default):
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            pass
    return default


def save_playlist(entries: list[dict]) -> None:
    # dedup by stream
    seen = {}
    for e in entries:
        u = (e.get("stream_url") or "").strip()
        if u:
            seen[u] = e
    entries = list(seen.values())
    OUT_JSON.write_text(json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8")
    lines = [
        "#EXTM3U",
        f"#SOURCE: desihub.org",
        f"#REFRESHED: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        "",
    ]
    for e in entries:
        title = (e.get("title") or "Untitled").replace("\n", " ").strip()
        logo = e.get("thumbnail") or ""
        page = e.get("page_url") or ""
        stream = e.get("stream_url") or ""
        lines.append(f'#EXTINF:-1 tvg-logo="{logo}" group-title="DesiHub",{title}')
        if page:
            lines.append(f"#EXTVLCOPT:http-referrer={page}")
        lines.append(stream)
        lines.append("")
    OUT_M3U.write_text("\n".join(lines), encoding="utf-8")
    OUT_META.write_text(
        json.dumps(
            {
                "name": "playlist2",
                "label": "DesiHub",
                "entries": len(entries),
                "refreshed_utc": datetime.now(timezone.utc).isoformat(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    log.info("saved %s entries → playlist2", len(entries))


def fetch(url: str) -> str | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
        if r.status_code == 404:
            return None
        r.raise_for_status()
        return r.text
    except Exception as e:
        log.warning("fetch %s → %s", url[:70], e)
        return None


def clean_title(text: str) -> str:
    text = re.sub(r"^Featured image for\s*", "", text or "", flags=re.I)
    return re.sub(r"\s+", " ", text).strip() or "Untitled"


def real_image(src: str) -> str:
    try:
        m = re.search(r"url=(.*?)&", src)
        if m:
            return unquote(m.group(1))
    except Exception:
        pass
    return src


def extract_stream(page_url: str) -> tuple[str | None, str]:
    html = fetch(page_url)
    if not html:
        return None, ""
    soup = BeautifulSoup(html, "html.parser")
    thumb = ""
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        thumb = og["content"]

    for video in soup.find_all("video"):
        if video.get("src"):
            return urljoin(page_url, video["src"]), thumb
        src = video.find("source")
        if src and src.get("src"):
            return urljoin(page_url, src["src"]), thumb

    iframe = soup.find("iframe", src=True)
    if iframe:
        emb = urljoin(page_url, iframe["src"])
        sub = fetch(emb)
        if sub:
            for pat in (
                r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)',
                r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
            ):
                m = re.search(pat, sub, re.I)
                if m:
                    return m.group(1).replace("&amp;", "&"), thumb
            # sometimes the iframe src itself is the stream
            if any(x in emb for x in (".mp4", ".m3u8", "embed")):
                return emb, thumb

    for pat in (
        r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)',
        r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
    ):
        m = re.search(pat, html, re.I)
        if m:
            return m.group(1).replace("&amp;", "&"), thumb
    return None, thumb


def parse_listing(html: str, page_url: str) -> list[dict]:
    soup = BeautifulSoup(html, "html.parser")
    items = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        full = urljoin(page_url, href)
        if "desihub.org" not in full:
            continue
        if any(x in full for x in ("/tag/", "/category/", "/page/", "/author/", "#", "/wp-")):
            continue
        path = full.rstrip("/").split("desihub.org")[-1]
        if path.count("/") < 1 or len(path) < 4:
            continue
        if full in seen:
            continue
        seen.add(full)
        title = clean_title(a.get("title") or a.get_text(" ", strip=True))
        img = a.find("img")
        thumb = ""
        if img:
            for attr in ("src", "data-src", "data-lazy-src"):
                if img.get(attr):
                    thumb = real_image(urljoin(page_url, img[attr]))
                    break
        if not title or len(title) < 3:
            continue
        items.append({"title": title, "page_url": full, "thumbnail": thumb})
    return items


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=5, help="listing pages to scan (fast)")
    ap.add_argument("--workers", type=int, default=WORKERS)
    ap.add_argument("--fresh", action="store_true", help="ignore existing playlist")
    args = ap.parse_args()

    existing = [] if args.fresh else load_json(OUT_JSON, [])
    have = {e.get("stream_url") for e in existing if e.get("stream_url")}
    log.info("existing=%s pages=%s workers=%s", len(existing), args.pages, args.workers)

    t0 = time.time()
    candidates: list[dict] = []
    for page in range(1, args.pages + 1):
        url = BASE if page == 1 else f"{BASE}/page/{page}"
        log.info("list %s", url)
        html = fetch(url)
        if not html:
            break
        items = parse_listing(html, url)
        log.info("  %s cards", len(items))
        candidates.extend(items)
        time.sleep(0.2)

    # unique by page_url
    by_page = {c["page_url"]: c for c in candidates}
    candidates = list(by_page.values())

    new = []
    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as ex:
        futs = {ex.submit(extract_stream, c["page_url"]): c for c in candidates}
        for fut in as_completed(futs):
            c = futs[fut]
            try:
                stream, thumb = fut.result()
            except Exception as e:
                log.warning("err %s", e)
                continue
            if not stream or stream in have:
                continue
            have.add(stream)
            new.append(
                {
                    "title": c["title"],
                    "stream_url": stream,
                    "page_url": c["page_url"],
                    "thumbnail": thumb or c.get("thumbnail") or "",
                }
            )

    all_entries = new + existing
    save_playlist(all_entries)
    STATE.write_text(
        json.dumps(
            {
                "last_run": datetime.now(timezone.utc).isoformat(),
                "pages": args.pages,
                "new": len(new),
                "total": len(all_entries),
                "elapsed_s": round(time.time() - t0, 1),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    log.info("done new=%s total=%s in %.1fs", len(new), len(all_entries), time.time() - t0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
