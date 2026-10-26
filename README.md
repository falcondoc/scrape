# Independent multi-playlist repo

No dependency on another GitHub raw playlist. Each `playlistN` is built by its own scraper/prober.

| File | Source (scraped/probed) | Workflow | Default mode time |
|------|-------------------------|----------|-------------------|
| `playlist1.m3u` | **kaamdesi.com** | Update playlist1 | refresh ~1–3 min |
| `playlist2.m3u` | **desihub.org** | Update playlist2 | ~2–5 min |
| `playlist3.m3u` | **pornhao.com** | Update playlist3 | ~3–8 min (8 models × 8 videos) |
| `playlist4.m3u` | **local live_catalog** (probe only) | Update playlist4 | ~1–3 min |

## Why this is independent + fast

- No Selenium / Chrome (the old 15‑min sniffer path).
- HTTP scrapers with parallel workers.
- Incremental **refresh** for playlist1; limited pages/models for 2 & 3.
- playlist4 keeps a local catalog and only publishes streams that still answer.

Dropped / not auto-scraped (hosts dead or blocked from Actions IPs):

- unitv20.com movie dumps (403)
- hmaal.net ullu/alt (timeout)
- antik/dash DRM packs (404 / DRM keys)

You can still expand playlist4 catalog with any external M3U once via workflow input `import_url`.

## Setup

1. Unzip into a public repo (e.g. `falcondoc/scrape`).
2. Push.
3. Run each workflow once (playlist2 needs a first run to fill).
4. Cron keeps them warm every 6h (staggered minutes).

## Raw URLs

```
https://raw.githubusercontent.com/<you>/<repo>/main/playlist1.m3u
https://raw.githubusercontent.com/<you>/<repo>/main/playlist2.m3u
https://raw.githubusercontent.com/<you>/<repo>/main/playlist3.m3u
https://raw.githubusercontent.com/<you>/<repo>/main/playlist4.m3u
```

## Local

```bash
pip install -r requirements.txt
python scripts/scrape_desi.py --mode refresh
python scripts/scrape_desihub.py --pages 5
python scripts/scrape_pornhao.py --max-models 8 --max-per-model 8
python scripts/refresh_live_iptv.py
```

18+ only.
