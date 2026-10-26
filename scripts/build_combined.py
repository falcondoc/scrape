#!/usr/bin/env python3
from __future__ import annotations
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORDER = [
    "playlist1.m3u",
    "playlist2.m3u",
    "playlist3.m3u",
    "playlist4.m3u",
    "playlist5.m3u",
]
OUT = ROOT / "combined_playlist.m3u"

def main():
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = ["#EXTM3U", "#COMBINED: playlist1+2+3+4+5", f"#REFRESHED: {now}", ""]
    total = 0
    for name in ORDER:
        path = ROOT / name
        if not path.exists():
            lines.append(f"# missing {name}")
            continue
        body = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if body and body[0].strip().upper().startswith("#EXTM3U"):
            body = body[1:]
        n = sum(1 for L in body if L.strip().startswith("http"))
        total += n
        lines.append(f"# --- {name} ({n} streams) ---")
        lines.extend(body)
        lines.append("")
    OUT.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"combined total_streams≈{total}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
