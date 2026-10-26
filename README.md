# falcondoc/scrape — fixed independent playlists

Same filenames / order. No dependency on other repos for day-to-day updates.

| File | Content | Update job |
|------|---------|------------|
| `playlist1.m3u` | Kaamdesi / Desi VOD (scrape) | Update playlist1 |
| `playlist2.m3u` | Adult live IPTV (local catalog, **soft probe**) | Update playlist2 |
| `playlist3.m3u` | Pornhao performers (scrape) | Update playlist3 |
| `playlist4.m3u` | XXX movies catalog (local, soft) | Update playlist4 |
| `combined_playlist.m3u` | 1+2+3+4 | rebuilt by every job |

## Why playlist4 went empty

Hard probe from GitHub runners hit dead/blocked IPTV hosts and wrote `#ALIVE: 0`.  
**Soft probe** now: if every stream fails from the runner IP, the catalog is still published (player may still open some links).

## Push this package

Overwrite repo files with this zip contents, then:

1. Actions → **Update playlist2** once (rewrites non-empty p2)
2. Actions → **Update playlist4** once (rewrites non-empty p4)
3. Or just commit the seeded `playlist2.m3u` / `playlist4.m3u` / `combined_playlist.m3u` from this zip

Raw URLs stay:

```
https://raw.githubusercontent.com/falcondoc/scrape/main/playlist1.m3u
https://raw.githubusercontent.com/falcondoc/scrape/main/playlist2.m3u
https://raw.githubusercontent.com/falcondoc/scrape/main/playlist3.m3u
https://raw.githubusercontent.com/falcondoc/scrape/main/playlist4.m3u
https://raw.githubusercontent.com/falcondoc/scrape/main/combined_playlist.m3u
```
