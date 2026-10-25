# above18 — performer VOD playlist

Auto-refreshed M3U of adult VOD streams grouped by performer.  
Built for OTT Navigator / TiviMate / VLC / any player that takes a raw M3U URL.

## Raw playlist URL

After you push this repo to GitHub:

```
https://raw.githubusercontent.com/<YOUR_USER>/<YOUR_REPO>/main/playlist.m3u
```

Paste that into OTT Navigator → Playlists → Add URL.

## What’s inside

| File | Role |
|------|------|
| `playlist.m3u` | Master playlist (performer groups) |
| `playlist.json` | Run metadata (counts, timestamps) |
| `performers.txt` | Who to scrape (edit this) |
| `scripts/build_master_m3u.py` | Scraper |
| `.github/workflows/update-playlist.yml` | Cron refresh every 6h + manual button |

## Local run

```bash
python scripts/build_master_m3u.py -p "Angela White" "Brandi Love" --pages 5
# or whole list from performers.txt logic / top models:
python scripts/build_master_m3u.py --max-models 40 --pages 4
```

Writes `playlist.m3u` + `playlist.json` in the current directory.

## GitHub Actions

1. Create a **public** repo (raw URLs need public, or use a tokenized private URL).
2. Upload everything in this folder to the repo root.
3. Actions → **Update Playlist** → Run workflow (or wait for the 6-hour cron).
4. Tokens on CDN links expire after a few days — the workflow keeps them fresh.

### Manual dispatch options

- **performers** — comma list override (`angela-white,brandi-love`)
- **pages** — depth per performer (default 5)

## OTT Navigator tips

- Add as **VOD** or **Live** playlist (both work; VOD is cleaner).
- Groups = performer names (`group-title`).
- Logos = `tvg-logo` from pornhao thumbs.
- If a stream dies mid-session, re-pull the playlist (or wait for next Actions run).

## Notes

- Source: pornhao.com → pornocdn signed MP4s.
- No API keys. Stdlib + optional urllib3.
- 18+ only. Watch at your own risk.
