#!/usr/bin/env python3
"""
Mirror external adult M3U sources into playlist1..N in this repo.
Sources are listed in sources.json. Each entry becomes playlist{N}.m3u
plus a small meta json. Also builds combined_playlist.m3u.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCES_FILE = ROOT / "sources.json"
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


def load_sources() -> list[dict]:
    if not SOURCES_FILE.exists():
        raise SystemExit(f"missing {SOURCES_FILE}")
    data = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    if not isinstance(data, list) or not data:
        raise SystemExit("sources.json must be a non-empty list")
    return data


def fetch(url: str, timeout: int = 60) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def count_entries(text: str) -> int:
    # count stream URLs (http lines that are not tags)
    n = 0
    for line in text.splitlines():
        s = line.strip()
        if s.startswith("http://") or s.startswith("https://"):
            n += 1
    return n


def ensure_header(text: str, label: str, source_url: str) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    body = text.lstrip()
    if body.upper().startswith("#EXTM3U"):
        # keep original header block, inject our meta after first line
        lines = body.splitlines()
        head = lines[0]
        rest = "\n".join(lines[1:]).lstrip("\n")
        meta = (
            f"{head}\n"
            f"#SOURCE: {source_url}\n"
            f"#LABEL: {label}\n"
            f"#REFRESHED: {now}\n"
            f"#GENERATOR: mirror_sources.py\n"
        )
        return meta + rest + ("\n" if not rest.endswith("\n") else "")
    # no header
    return (
        f"#EXTM3U\n"
        f"#SOURCE: {source_url}\n"
        f"#LABEL: {label}\n"
        f"#REFRESHED: {now}\n"
        f"#GENERATOR: mirror_sources.py\n\n"
        + body
        + ("\n" if not body.endswith("\n") else "")
    )


def write_playlist(idx: int, label: str, source_url: str, content: str) -> dict:
    name = f"playlist{idx}"
    m3u_path = ROOT / f"{name}.m3u"
    json_path = ROOT / f"{name}.json"

    cleaned = ensure_header(content, label, source_url)
    entries = count_entries(cleaned)
    m3u_path.write_text(cleaned, encoding="utf-8")

    meta = {
        "name": name,
        "label": label,
        "source_url": source_url,
        "entries": entries,
        "bytes": len(cleaned.encode("utf-8")),
        "refreshed_utc": datetime.now(timezone.utc).isoformat(),
        "file": f"{name}.m3u",
    }
    json_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"[ok] {name}.m3u  entries={entries}  label={label}")
    return meta


def build_combined(metas: list[dict]) -> None:
    """Concat playlist1..N into combined_playlist.m3u with group-title override optional."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    out_lines = [
        "#EXTM3U",
        f"#COMBINED: {len(metas)} sources",
        f"#REFRESHED: {now}",
        "#GENERATOR: mirror_sources.py",
        "",
    ]
    total = 0
    for m in metas:
        path = ROOT / m["file"]
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        # strip leading #EXTM3U from each so we don't duplicate
        body_lines = text.splitlines()
        if body_lines and body_lines[0].strip().upper().startswith("#EXTM3U"):
            body_lines = body_lines[1:]
        out_lines.append(f"# --- {m['name']} | {m['label']} | {m['entries']} entries ---")
        out_lines.extend(body_lines)
        out_lines.append("")
        total += m["entries"]

    out = "\n".join(out_lines) + "\n"
    (ROOT / "combined_playlist.m3u").write_text(out, encoding="utf-8")
    summary = {
        "sources": len(metas),
        "total_entries": total,
        "refreshed_utc": datetime.now(timezone.utc).isoformat(),
        "playlists": metas,
    }
    (ROOT / "combined_meta.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"[ok] combined_playlist.m3u  total_entries={total}")


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
            print(f"[fail] playlist{i}: {e}")
            # keep previous file if present
            existing = ROOT / f"playlist{i}.m3u"
            if existing.exists():
                print(f"[keep] using existing {existing.name}")
                meta = {
                    "name": f"playlist{i}",
                    "label": label,
                    "source_url": url,
                    "entries": count_entries(existing.read_text(encoding="utf-8", errors="replace")),
                    "bytes": existing.stat().st_size,
                    "refreshed_utc": None,
                    "file": f"playlist{i}.m3u",
                    "error": str(e),
                }
                metas.append(meta)
            continue
        if count_entries(content) < 1 and "#EXTINF" not in content:
            print(f"[warn] playlist{i}: empty or invalid body, skipping write")
            continue
        meta = write_playlist(i, label, url, content)
        metas.append(meta)
        time.sleep(0.4)

    if metas:
        build_combined(metas)
        (ROOT / "sources_status.json").write_text(
            json.dumps(
                {
                    "refreshed_utc": datetime.now(timezone.utc).isoformat(),
                    "count": len(metas),
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
