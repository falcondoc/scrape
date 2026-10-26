#!/usr/bin/env python3
"""
Independent Desi/Kaamdesi scraper → playlist1.m3u + playlist1.json

Fast path for GitHub Actions:
  - mode=refresh  → only first N pages (default 3), merge + dedup  (~1–3 min)
  - mode=batch    → walk more pages with parallel workers
  - mode=reset    → rebuild from page 1

No Selenium. cloudscraper + BS4 + ThreadPool.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import cloudscraper
from bs4 import BeautifulSoup

# ---------- config ----------
ROOT = Path(__file__).resolve().parents[1]
BASE_URL = "https://kaamdesi.com"
STATE_FILE = ROOT / "scraper_state.json"
PLAYLIST_JSON = ROOT / "playlist1.json"
PLAYLIST_M3U = ROOT / "playlist1.m3u"
META_JSON = ROOT / "playlist1_meta.json"

DELAY = 0.25
BATCH_PAGES = 8
REFRESH_PAGES = 3
MAX_PAGE_LIMIT = 400
MAX_WORKERS = 10
IFRAME_WORKERS = 4
REQUEST_TIMEOUT = 18

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("desi")

_local = threading.local()


def get_scraper():
    if not getattr(_local, "s", None):
        s = cloudscraper.create_scraper(
            browser={"browser": "chrome", "platform": "windows", "desktop": True}
        )
        s.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-US,en;q=0.9",
                "Referer": BASE_URL + "/",
            }
        )
        _local.s = s
    return _local.s


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "last_page": 0,
        "completed": False,
        "total_videos": 0,
        "last_run": "",
        "run_count": 0,
        "last_mode": "",
    }


def save_state(state: dict) -> None:
    state["last_run"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    state["run_count"] = int(state.get("run_count", 0)) + 1
    STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_existing() -> list[dict]:
    if PLAYLIST_JSON.exists():
        try:
            data = json.loads(PLAYLIST_JSON.read_text(encoding="utf-8"))
            if isinstance(data, list):
                return data
        except Exception:
            pass
    return []


def dedup(entries: list[dict]) -> list[dict]:
    seen: dict[str, dict] = {}
    for e in entries:
        u = (e.get("stream_url") or "").strip()
        if u:
            seen[u] = e
    return list(seen.values())


def fetch_html(url: str, retries: int = 2) -> str | None:
    s = get_scraper()
    for attempt in range(retries + 1):
        try:
            r = s.get(url, timeout=REQUEST_TIMEOUT)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.text
        except Exception as e:
            if attempt >= retries:
                log.warning("fetch fail %s → %s", url[:70], e)
                return None
            time.sleep(0.8 * (attempt + 1))
    return None


def is_tiny(url: str) -> bool:
    ul = url.lower()
    return any(
        t in ul
        for t in (
            "1x1",
            "spacer",
            "blank",
            "pixel",
            "loading",
            "spinner",
            "placeholder",
            "avatar",
            "icon",
            "logo",
            "gravatar",
            "emoji",
            "smilies",
            "wp-includes",
        )
    )


def listing_url(page: int) -> str:
    if page <= 1:
        return BASE_URL.rstrip("/") + "/"
    return f"{BASE_URL.rstrip('/')}/page/{page}/"


def parse_listing(html: str, page_url: str) -> list[dict]:
    """Return list of {title, page_url, thumbnail} from a listing page."""
    soup = BeautifulSoup(html, "html.parser")
    items: list[dict] = []
    seen_href: set[str] = set()

    # common card patterns on kaamdesi / similar WP themes
    candidates = []
    for sel in (
        "article",
        ".post",
        ".entry",
        ".video-item",
        ".item",
        ".thumb",
        "div.post-item",
        "div.video",
    ):
        found = soup.select(sel)
        if found and len(found) >= 3:
            candidates = found
            break
    if not candidates:
        # fallback: any anchor that looks like a post
        candidates = soup.find_all("a", href=True)

    for block in candidates:
        a = block if block.name == "a" else block.find("a", href=True)
        if not a:
            continue
        href = a.get("href", "").strip()
        if not href:
            continue
        full = urljoin(page_url, href)
        parsed = urlparse(full)
        if "kaamdesi.com" not in parsed.netloc:
            continue
        path = parsed.path.rstrip("/")
        if not path or path == "" or "/page/" in path or path.count("/") < 1:
            continue
        skip = (
            "/category/",
            "/tag/",
            "/author/",
            "/wp-",
            "/feed",
            "/page/",
            "/search",
            "#",
        )
        if any(s in full.lower() for s in skip):
            continue
        if full in seen_href:
            continue
        seen_href.add(full)

        title = (a.get("title") or a.get_text(" ", strip=True) or "").strip()
        if not title or len(title) < 4:
            img = (block if block.name != "a" else a).find("img")
            if img:
                title = (img.get("alt") or img.get("title") or "").strip()
        if not title:
            title = path.strip("/").replace("-", " ").title()

        thumb = ""
        img = (block if block.name != "a" else a).find("img")
        if img:
            for attr in ("src", "data-src", "data-lazy-src", "data-original", "data-thumb"):
                val = (img.get(attr) or "").strip()
                if val and not val.startswith("data:") and not is_tiny(val):
                    thumb = urljoin(page_url, val)
                    break

        items.append({"title": title, "page_url": full, "thumbnail": thumb})

    # de-noise: keep unique page urls, prefer longer titles
    by_url: dict[str, dict] = {}
    for it in items:
        u = it["page_url"]
        if u not in by_url or len(it["title"]) > len(by_url[u]["title"]):
            by_url[u] = it
    return list(by_url.values())


def extract_stream(html: str, page_url: str) -> tuple[str | None, str]:
    """Return (stream_url, thumbnail) from a video page."""
    soup = BeautifulSoup(html, "html.parser")
    thumb = ""
    og = soup.find("meta", property="og:image")
    if og and og.get("content"):
        thumb = og["content"].strip()

    # direct video / source
    for video in soup.find_all("video"):
        src = video.get("src")
        if src and (".mp4" in src or ".m3u8" in src):
            return urljoin(page_url, src.replace("&amp;", "&")), thumb
        for source in video.find_all("source"):
            src = source.get("src")
            if src and (".mp4" in src or ".m3u8" in src):
                return urljoin(page_url, src.replace("&amp;", "&")), thumb
        if not thumb and video.get("poster"):
            thumb = urljoin(page_url, video["poster"])

    text = html
    # mp4 on known CDNs first
    patterns = [
        r'(https?://[^\s"\'<>]+mmsbee[^\s"\'<>]+\.mp4[^\s"\'<>]*)',
        r'(https?://[^\s"\'<>]+\.mp4[^\s"\'<>]*)',
        r'(https?://[^\s"\'<>]+\.m3u8[^\s"\'<>]*)',
    ]
    for pat in patterns:
        m = re.search(pat, text, re.I)
        if m:
            url = m.group(1).replace("&amp;", "&").rstrip("\\).,;")
            if "facebook" in url or "google" in url:
                continue
            return url, thumb

    # iframe embed → follow once
    for iframe in soup.find_all("iframe", src=True):
        src = iframe["src"].strip()
        if not src or src.startswith("about:"):
            continue
        full = urljoin(page_url, src)
        if "kaamdesi" in full and full.rstrip("/") == page_url.rstrip("/"):
            continue
        sub = fetch_html(full, retries=1)
        if not sub:
            continue
        for pat in patterns:
            m = re.search(pat, sub, re.I)
            if m:
                url = m.group(1).replace("&amp;", "&").rstrip("\\).,;")
                return url, thumb

    return None, thumb


def process_item(item: dict, existing_urls: set[str], lock: threading.Lock) -> dict | None:
    page_url = item["page_url"]
    html = fetch_html(page_url)
    if not html:
        return None
    stream, thumb = extract_stream(html, page_url)
    if not stream:
        return None
    with lock:
        if stream in existing_urls:
            return None
        existing_urls.add(stream)
    return {
        "title": item.get("title") or "Untitled",
        "stream_url": stream,
        "page_url": page_url,
        "thumbnail": thumb or item.get("thumbnail") or "",
    }


def has_next_page(html: str, current: int) -> bool:
    if f"/page/{current + 1}" in html or f"/page/{current + 1}/" in html:
        return True
    soup = BeautifulSoup(html, "html.parser")
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if re.search(rf"/page/{current + 1}/?$", href):
            return True
        txt = a.get_text(strip=True).lower()
        if txt in ("next", "»", "›", "older"):
            return True
    return False


def scrape_pages(
    start: int,
    num_pages: int,
    existing_urls: set[str],
    workers: int,
) -> tuple[list[dict], int, bool]:
    new_entries: list[dict] = []
    lock = threading.Lock()
    current = start
    reached_end = False
    empty_streak = 0

    for _ in range(num_pages):
        if current > MAX_PAGE_LIMIT:
            reached_end = True
            break
        page_url = listing_url(current)
        log.info("listing page %s → %s", current, page_url)
        html = fetch_html(page_url)
        if html is None:
            log.info("page %s 404/empty — end", current)
            reached_end = True
            break

        listings = parse_listing(html, page_url)
        if not listings:
            empty_streak += 1
            log.info("page %s: 0 listings (streak %s)", current, empty_streak)
            if empty_streak >= 2:
                reached_end = True
                break
            current += 1
            time.sleep(DELAY)
            continue
        empty_streak = 0

        page_entries: list[dict] = []
        with ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [
                ex.submit(process_item, item, existing_urls, lock) for item in listings
            ]
            for fut in as_completed(futs):
                try:
                    res = fut.result()
                except Exception as e:
                    log.warning("worker error: %s", e)
                    continue
                if res:
                    page_entries.append(res)

        new_entries.extend(page_entries)
        log.info("page %s: +%s (batch total %s)", current, len(page_entries), len(new_entries))

        if not has_next_page(html, current):
            log.info("no next after page %s", current)
            reached_end = True
            break

        current += 1
        time.sleep(DELAY)

    last_done = current if reached_end else current - 1
    return new_entries, max(last_done, start - 1), reached_end


def save_playlist(entries: list[dict]) -> None:
    entries = dedup(entries)
    PLAYLIST_JSON.write_text(
        json.dumps(entries, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    lines = ["#EXTM3U", f"#REFRESHED: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}", ""]
    for e in entries:
        title = (e.get("title") or "Untitled").replace("\n", " ").strip()
        logo = e.get("thumbnail") or ""
        page = e.get("page_url") or ""
        stream = e.get("stream_url") or ""
        if not stream:
            continue
        lines.append(f'#EXTINF:-1 tvg-logo="{logo}",{title}')
        if page:
            lines.append(f"#EXTVLCOPT:http-referrer={page}")
        lines.append(stream)
        lines.append("")
    PLAYLIST_M3U.write_text("\n".join(lines), encoding="utf-8")

    meta = {
        "name": "playlist1",
        "label": "Desi / Kaamdesi VOD",
        "entries": len(entries),
        "refreshed_utc": datetime.now(timezone.utc).isoformat(),
        "file": "playlist1.m3u",
    }
    META_JSON.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    log.info("saved %s → %s + %s", len(entries), PLAYLIST_M3U.name, PLAYLIST_JSON.name)


def main() -> int:
    global MAX_WORKERS, REFRESH_PAGES, BATCH_PAGES
    p = argparse.ArgumentParser(description="Independent Kaamdesi → playlist1")
    p.add_argument("--mode", choices=["batch", "refresh", "reset"], default="refresh")
    p.add_argument("--start-page", type=int, default=None)
    p.add_argument("--workers", type=int, default=MAX_WORKERS)
    p.add_argument("--refresh-pages", type=int, default=REFRESH_PAGES)
    p.add_argument("--batch-pages", type=int, default=BATCH_PAGES)
    args = p.parse_args()

    MAX_WORKERS = max(1, args.workers)
    REFRESH_PAGES = max(1, args.refresh_pages)
    BATCH_PAGES = max(1, args.batch_pages)
    mode = args.mode

    state = load_state()
    log.info("MODE=%s workers=%s", mode.upper(), MAX_WORKERS)
    log.info(
        "state last_page=%s completed=%s total=%s",
        state.get("last_page"),
        state.get("completed"),
        state.get("total_videos"),
    )

    if mode == "reset":
        state = {
            "last_page": 0,
            "completed": False,
            "total_videos": 0,
            "last_run": "",
            "run_count": 0,
            "last_mode": "reset",
        }
        existing: list[dict] = []
    else:
        existing = load_existing()

    existing_urls = {e["stream_url"] for e in existing if e.get("stream_url")}
    log.info("existing playlist: %s", len(existing))

    new_entries: list[dict] = []
    last_page = int(state.get("last_page") or 0)
    reached_end = bool(state.get("completed"))

    t0 = time.time()

    if mode in ("batch", "reset"):
        if reached_end and mode != "reset":
            log.info("already completed site walk → switching to refresh")
            mode = "refresh"
        else:
            start = args.start_page if args.start_page is not None else last_page + 1
            if start < 1:
                start = 1
            log.info("BATCH pages %s → %s", start, start + BATCH_PAGES - 1)
            new_entries, last_page, reached_end = scrape_pages(
                start, BATCH_PAGES, existing_urls, MAX_WORKERS
            )

    if mode == "refresh":
        log.info("REFRESH first %s pages", REFRESH_PAGES)
        new_entries, _, _ = scrape_pages(1, REFRESH_PAGES, existing_urls, MAX_WORKERS)

    if mode == "refresh":
        all_entries = new_entries + existing
    else:
        all_entries = existing + new_entries
    all_entries = dedup(all_entries)

    elapsed = time.time() - t0
    log.info(
        "done mode=%s new=%s total=%s last_page=%s end=%s elapsed=%.1fs",
        mode,
        len(new_entries),
        len(all_entries),
        last_page,
        reached_end,
        elapsed,
    )

    save_playlist(all_entries)

    if mode != "refresh":
        state["last_page"] = last_page
        state["completed"] = reached_end
    state["total_videos"] = len(all_entries)
    state["last_mode"] = mode
    save_state(state)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
