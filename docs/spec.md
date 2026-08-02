# tiktok-link — Pure-HTTP TikTok MP4 Link Getter (CLI)

Date: 2026-08-01
Status: Approved by user (approach A)

## Purpose

A Python CLI that takes a TikTok video URL and prints the direct MP4 CDN link(s) + metadata,
using only HTTP requests (no browser, no extension). Based on the patterns used by
yt-dlp's TikTok extractor and the parsing logic of the TikTok Bulk Video Downloader extension.

## Approach

- Primary: Web API `https://www.tiktok.com/api/item/detail/?aid=1988&itemId={id}&verifyFp=verify_xxx`
  with `ms_token` login cookie and Chrome TLS impersonation (`curl_cffi`).
- Fallback: fetch video page HTML and parse `<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">`.
- Out of scope (future): Android app API (`aweme/v1`) for 1080p/H.265.

## Components

| File | Responsibility |
|---|---|
| `models.py` | `VideoInfo`, `MediaCandidate` dataclasses |
| `resolver.py` | URL normalization, short-link resolve, videoId/username extraction |
| `client.py` | `curl_cffi` session with impersonation + cookie loading; `fetch_item_detail`, `fetch_video_page` |
| `extractor.py` | Parse web API JSON and HTML universal data into `VideoInfo` |
| `cli.py` | argparse entry; prints metadata + mp4 links; `--json` flag |

## Flow

```
URL → resolver.normalize → short link? redirect → extract videoId+username
→ client.fetch_item_detail(videoId) → extractor → candidates
  └─ empty? → client.fetch_video_page(url) → extractor(HTML) → candidates
→ rank (H.264 first, highest bitrate) → print creator/caption/duration/all mp4 URLs
```

## Errors

- HTTP 403 or empty data → clear message: IP blocked or ms_token invalid/expired
- statusCode 10216/10222 → private/login required
- no bitrateInfo → slideshow/audio-only message
- all fallbacks fail → non-zero exit

## Cookie sources (priority)

1. `--cookie "ms_token=..."` flag
2. `TIKTOK_COOKIE` env var
3. `cookies.txt` file (format `name=value;`)

## Testing

- Unit: `unittest` for resolver + extractor with fixture JSON/HTML (no network)
- Manual E2E: one run with a real URL + cookie (user-provided) to verify live behavior
