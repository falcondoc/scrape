# Multi-source adult playlists (playlist1 / playlist2 / …)

Mirrors external M3U sources into this repo as numbered playlists so you can
extend / combine them for OTT Navigator.

## Raw URLs (after first successful Actions run)

```
https://raw.githubusercontent.com/<you>/<repo>/main/playlist1.m3u
https://raw.githubusercontent.com/<you>/<repo>/main/playlist2.m3u
https://raw.githubusercontent.com/<you>/<repo>/main/playlist3.m3u
https://raw.githubusercontent.com/<you>/<repo>/main/playlist4.m3u
https://raw.githubusercontent.com/<you>/<repo>/main/combined_playlist.m3u
```

## Mapping (default sources.json)

| File | Source | Content |
|------|--------|---------|
| `playlist1.m3u` | falcondoc/above18 `playlist1.m3u` | Desi / Kaamdesi VOD |
| `playlist2.m3u` | falcondoc/above18 `s.m3u` | Adult live + VOD |
| `playlist3.m3u` | falcondoc/above18 `u.m3u` | MPD / DRM adult TV |
| `playlist4.m3u` | falcondoc/above18 `x.m3u` | XXX movie catalog |
| `combined_playlist.m3u` | all of the above | single file concat |

Edit `sources.json` to add/remove/reorder sources. Numbering is always
`playlist1` … `playlistN` in list order.

## Actions

- Workflow: **Update Source Playlists**
- Cron: every 6 hours
- Manual: Actions → Update Source Playlists → Run workflow

## Local

```bash
python scripts/mirror_sources.py
```

Writes `playlistN.m3u` + `playlistN.json` meta + `combined_playlist.m3u`.

## Extend

1. Add a new object to `sources.json` with `"label"` + `"url"`.
2. Push / wait for Actions (or run the script locally and commit).
3. New file appears as the next `playlistN.m3u`.

## Notes

- This package only **mirrors** remote M3Us. It does not re-scrape sites.
- Your existing pornhao performer scraper package stays separate
  (`playlist.m3u` from `build_master_m3u.py`).
- 18+ only.
