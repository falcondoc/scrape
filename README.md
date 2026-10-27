# Multi-source adult playlists (live-filtered)

Mirrors external M3U sources into numbered playlists and **keeps only channels that still answer**.

Every refresh:
1. fetch upstream M3U
2. parse every `#EXTINF` block
3. probe the stream URL (HEAD → short GET)
4. drop timeouts, 403/404, DNS failures, HTML error pages
5. write `playlistN.m3u` with survivors only
6. if a run returns almost nothing, keep the previous good file

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
| `playlist3.m3u` | falcondoc/above18 `u.m3u` | MPD / DRM adult TV + cams |
| `playlist4.m3u` | falcondoc/above18 `x.m3u` | XXX movie catalog |
| `combined_playlist.m3u` | all of the above | single live-filtered concat |

## Actions

- Workflow: **Update Source Playlists**
- Cron: every 6 hours
- Manual: Actions → Update Source Playlists → Run workflow

## Local

```bash
python scripts/mirror_sources.py
```

Writes `playlistN.m3u` + `playlistN.json` meta + `combined_playlist.m3u` + `sources_status.json`.

## Behaviour

- **Live filter**: only HTTP 2xx media responses are kept
- **Antik**: uses Smart-TV UA + Referer so DASH manifests answer
- **Last-known-good**: if a source suddenly returns near-zero live channels, the previous file is kept
- **DRM props**: original `#KODIPROP` / `#EXTHTTP` lines are preserved on surviving entries
- No site scraping — this package only mirrors + health-checks remote M3Us

## Extend

1. Add a new object to `sources.json` with `"label"` + `"url"`.
2. Push / wait for Actions (or run the script locally and commit).
3. New file appears as the next `playlistN.m3u`.

## Notes

- 18+ only
- Widevine / ClearKey channels still need a player that supports DASH + DRM
- Free linear streams die; this setup just stops serving the corpses
