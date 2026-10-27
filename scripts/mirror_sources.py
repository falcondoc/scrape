#!/usr/bin/env python3
"""
Mirror external adult M3U sources into playlist1..N with live health checks.

- Fetches each URL from sources.json
- Parses #EXTINF blocks
- Probes every stream URL (HEAD then short GET)
- Keeps ONLY channels that return 2xx and look like media
- Writes playlist{N}.m3u + playlist{N}.json
- Builds combined_playlist.m3u
- If a source yields zero live channels, keeps the previous file (last-known-good)
"""
from __future__ import annotations

import json
import re
import ssl
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES_FILE = ROOT / "sources.json"

UA_WEB = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
UA_TV = (
    "Mozilla/5.0 (X11; Linux armv7l) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/88.0.4324.182 Odin/88.4324.2.10 Safari/537.36 "
    "Model/Hisense-MT9602 VIDAA/6.0(Tesla;SmartTV;VS0732FC1;"
    "MTK9602/V0000.06.13K.O1124;HD;VS0732F;)"
)
ANTIK_REFERER = "https://webtv.sk/tv/"

# probe tuning
PROBE_WORKERS = 16
PROBE_TIMEOUT = 10
MIN_KEEP_RATIO = 0.05  # if new live < 5% of previous, keep previous file
SSL_CTX = ssl.create_default_context()


def load_sources() -> list[dict]:
    if not SOURCES_FILE.exists():
        raise SystemExit(f"missing {SOURCES_FILE}")
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise SystemExit("sources.json must be a non-empty list")
    return data


def fetch(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(
        url, headers={"User-Agent": UA_WEB, "Accept": "*/*"}
    )
    with urllib.request.urlopen(req, timeout=timeout, context=SSL_CTX) as resp:
        raw = resp.read()
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def parse_entries(text: str) -> list[dict]:
    """Split M3U into {name, url, raw_block} dicts."""
    # drop leading non-EXTINF header noise for splitting
    parts = re.split(r"\n(?=#EXTINF)", text)
    entries: list[dict] = []
    for block in parts:
        block = block.strip()
        if not block or "#EXTINF" not in block:
            continue
        name = ""
        m = re.search(r"#EXTINF:[^\n]*,([^\n]+)", block)
        if m:
            name = m.group(1).strip()
        url = None
        for line in block.splitlines():
            s = line.strip()
            if s.startswith("http://") or s.startswith("https://"):
                url = s
                break
        if not url:
            continue
        entries.append({"name": name, "url": url, "raw": block})
    return entries


def probe_one(entry: dict) -> dict:
    """Return entry with ok=True/False after HTTP probe."""
    url = entry["url"]
    headers = {"User-Agent": UA_WEB, "Accept": "*/*"}
    if "antik.sk" in url:
        headers["User-Agent"] = UA_TV
        headers["Referer"] = ANTIK_REFERER
        headers["Origin"] = "https://webtv.sk"

    last_err = ""
    for method in ("HEAD", "GET"):
        try:
            req = urllib.request.Request(url, headers=headers, method=method)
            t0 = time.time()
            with urllib.request.urlopen(
                req, timeout=PROBE_TIMEOUT, context=SSL_CTX
            ) as resp:
                code = resp.status
                ctype = (resp.headers.get("Content-Type") or "").lower()
                body = b""
                if method == "GET":
                    body = resp.read(8000)
                elapsed = round(time.time() - t0, 2)
                ok = 200 <= code < 400
                if method == "GET" and body and ok:
                    low = body[:500].lower()
                    # reject pure HTML error pages that still return 200
                    if (
                        b"<html" in low
                        and b"mpd" not in low
                        and b"#extm3u" not in low
                        and b"extinf" not in low
                        and b"<mpd" not in low
                        and "mpegurl" not in ctype
                        and "mpd" not in ctype
                        and "dash" not in ctype
                        and "octet" not in ctype
                        and "video" not in ctype
                        and "application/vnd.apple" not in ctype
                    ):
                        ok = False
                return {
                    **entry,
                    "ok": ok,
                    "status": code,
                    "ctype": ctype[:80],
                    "ms": elapsed,
                }
        except Exception as ex:
            last_err = str(ex)[:120]
            continue
    return {
        **entry,
        "ok": False,
        "status": None,
        "ctype": "",
        "ms": None,
        "err": last_err,
    }


def filter_live(entries: list[dict]) -> tuple[list[dict], list[dict]]:
    """Probe all entries; return (live, dead)."""
    if not entries:
        return [], []
    live: list[dict] = []
    dead: list[dict] = []
    with ThreadPoolExecutor(max_workers=PROBE_WORKERS) as pool:
        futs = [pool.submit(probe_one, e) for e in entries]
        for fut in as_completed(futs):
            r = fut.result()
            if r.get("ok"):
                live.append(r)
            else:
                dead.append(r)
    # preserve original order
    order = {e["url"]: i for i, e in enumerate(entries)}
    live.sort(key=lambda x: order.get(x["url"], 10**9))
    dead.sort(key=lambda x: order.get(x["url"], 10**9))
    return live, dead


def count_entries_in_file(path: Path) -> int:
    if not path.exists():
        return 0
    n = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if s.startswith("http://") or s.startswith("https://"):
            n += 1
    return n


def build_m3u_body(live: list[dict], label: str, source_url: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "#EXTM3U",
        f"#SOURCE: {source_url}",
        f"#LABEL: {label}",
        f"#REFRESHED: {now}",
        f"#GENERATOR: mirror_sources.py (live-filter)",
        f"#ENTRIES: {len(live)}",
        f"#NOTE: only channels that returned HTTP 2xx on probe",
        "",
    ]
    for e in live:
        lines.append(e["raw"])
        lines.append("")
    return "\n".join(lines)


def write_playlist(
    idx: int,
    label: str,
    source_url: str,
    live: list[dict],
    total_parsed: int,
) -> dict:
    name = f"playlist{idx}"
    m3u_path = ROOT / f"{name}.m3u"
    json_path = ROOT / f"{name}.json"
    prev_count = count_entries_in_file(m3u_path)

    # last-known-good guard: if we got almost nothing but had a solid file, keep it
    if (
        live
        and prev_count > 0
        and len(live) < max(1, int(prev_count * MIN_KEEP_RATIO))
    ):
        print(
            f"[keep] {name}: new live={len(live)} << previous={prev_count}, "
            "keeping previous file"
        )
        meta = {
            "name": name,
            "label": label,
            "source_url": source_url,
            "entries": prev_count,
            "entries_live": len(live),
            "entries_parsed": total_parsed,
            "bytes": m3u_path.stat().st_size,
            "refreshed_utc": None,
            "file": f"{name}.m3u",
            "kept_previous": True,
        }
        json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta

    if not live:
        if m3u_path.exists() and prev_count > 0:
            print(
                f"[keep] {name}: zero live channels, keeping previous "
                f"({prev_count} entries)"
            )
            meta = {
                "name": name,
                "label": label,
                "source_url": source_url,
                "entries": prev_count,
                "entries_live": 0,
                "entries_parsed": total_parsed,
                "bytes": m3u_path.stat().st_size,
                "refreshed_utc": None,
                "file": f"{name}.m3u",
                "kept_previous": True,
            }
            json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return meta
        print(f"[warn] {name}: zero live and no previous file")
        return {
            "name": name,
            "label": label,
            "source_url": source_url,
            "entries": 0,
            "entries_live": 0,
            "entries_parsed": total_parsed,
            "file": f"{name}.m3u",
            "error": "no live channels",
        }

    body = build_m3u_body(live, label, source_url)
    m3u_path.write_text(body, encoding="utf-8")
    meta = {
        "name": name,
        "label": label,
        "source_url": source_url,
        "entries": len(live),
        "entries_live": len(live),
        "entries_parsed": total_parsed,
        "bytes": len(body.encode("utf-8")),
        "refreshed_utc": datetime.now(timezone.utc).isoformat(),
        "file": f"{name}.m3u",
        "kept_previous": False,
    }
    json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(
        f"[ok] {name}.m3u  live={len(live)}/{total_parsed}  label={label}"
    )
    return meta


def build_combined(metas: list[dict]) -> None:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out_lines = [
        "#EXTM3U",
        f"#COMBINED: {len(metas)} sources (live-filtered)",
        f"#REFRESHED: {now}",
        "#GENERATOR: mirror_sources.py (live-filter)",
        "",
    ]
    total = 0
    for m in metas:
        path = ROOT / m["file"]
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        body_lines = text.splitlines()
        if body_lines and body_lines[0].strip().upper().startswith("#EXTM3U"):
            body_lines = body_lines[1:]
        # strip our own meta comments from individual files so combined stays clean
        cleaned = []
        for line in body_lines:
            if line.startswith("#SOURCE:") or line.startswith("#LABEL:"):
                continue
            if line.startswith("#REFRESHED:") or line.startswith("#GENERATOR:"):
                continue
            if line.startswith("#ENTRIES:") or line.startswith("#NOTE:"):
                continue
            cleaned.append(line)
        out_lines.append(
            f"# --- {m['name']} | {m['label']} | {m.get('entries', 0)} live ---"
        )
        out_lines.extend(cleaned)
        out_lines.append("")
        total += int(m.get("entries") or 0)

    out = "\n".join(out_lines) + "\n"
    (ROOT / "combined_playlist.m3u").write_text(out, encoding="utf-8")
    summary = {
        "sources": len(metas),
        "total_entries": total,
        "refreshed_utc": datetime.now(timezone.utc).isoformat(),
        "playlists": metas,
        "mode": "live-filter",
    }
    (ROOT / "combined_meta.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(f"[ok] combined_playlist.m3u  total_live={total}")


def main() -> int:
    sources = load_sources()
    metas: list[dict] = []

    for i, src in enumerate(sources, start=1):
        url = src.get("url") or src.get("source")
        label = src.get("label") or src.get("name") or f"source-{i}"
        if not url:
            print(f"[skip] index {i}: no url")
            continue

        print(f"[fetch] playlist{i} <- {url}")
        try:
            content = fetch(url)
        except Exception as e:
            print(f"[fail] playlist{i} fetch: {e}")
            existing = ROOT / f"playlist{i}.m3u"
            if existing.exists():
                print(f"[keep] using existing {existing.name}")
                metas.append(
                    {
                        "name": f"playlist{i}",
                        "label": label,
                        "source_url": url,
                        "entries": count_entries_in_file(existing),
                        "bytes": existing.stat().st_size,
                        "refreshed_utc": None,
                        "file": f"playlist{i}.m3u",
                        "error": str(e),
                        "kept_previous": True,
                    }
                )
            continue

        entries = parse_entries(content)
        print(f"[parse] playlist{i}: {len(entries)} entries, probing...")
        live, dead = filter_live(entries)
        print(
            f"[probe] playlist{i}: live={len(live)}  dead={len(dead)}"
        )

        meta = write_playlist(i, label, url, live, len(entries))
        metas.append(meta)
        time.sleep(0.3)

    if metas:
        build_combined(metas)
        (ROOT / "sources_status.json").write_text(
            json.dumps(
                {
                    "refreshed_utc": datetime.now(timezone.utc).isoformat(),
                    "count": len(metas),
                    "mode": "live-filter",
                    "items": metas,
                },
                indent=2,
            ),
            encoding="utf-8",
        )
    else:
        print("[warn] nothing mirrored")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
