# tiktok-link

CLI pure-HTTP untuk mendapatkan link MP4 langsung dari video TikTok (tanpa browser/extension).

## Instalasi

```bash
pip install -r requirements.txt
```

## Penggunaan

```bash
python -m tiktok_link "https://www.tiktok.com/@user/video/7234567890123456789"
python -m tiktok_link "https://vm.tiktok.com/ZMabcXYZ/" --json
python -m tiktok_link "https://www.tiktok.com/@user/video/1234" --cookie "ms_token=..." --download
```

Opsi:

| Flag | Keterangan |
|---|---|
| `--json` | Output sebagai JSON (termasuk semua URL kandidat) |
| `--download [PATH]` | Unduh mp4 terbaik ke file (default: `<username>_<id>.mp4`) |
| `--quality {h264,best}` | `h264` (default) = terbaik dengan codec H.264; `best` = resolusi tertinggi (bisa HEVC) |
| `--cookie "ms_token=...; tt_webid=..."` | Cookie login TikTok |
| `--cookies-file cookies.txt` | Path file cookie (format `name=value; ...`) |

> **Penting saat mengunduh:** membuka link mp4 langsung di browser sering `Access Denied`
> karena CDN TikTok memvalidasi header `Referer`. Gunakan `--download` (tool mengirim
> `Referer: https://www.tiktok.com/` + cookie secara otomatis), atau unduh manual dengan:
> ```
> curl -L -H "Referer: https://www.tiktok.com/" -H "User-Agent: <UA Chrome>" -b "ms_token=..." <url_mp4> -o video.mp4
> ```

## Sumber Cookie (prioritas)

1. Flag `--cookie`
2. Env var `TIKTOK_COOKIE`
3. File `cookies.txt`

Cara ambil cookie: buka TikTok di browser → DevTools → Network → klik request
`item/detail` → Copy as cURL → salin nilai `ms_token` dari header Cookie.

## Cara kerja

1. Normalisasi URL (dukung short link `vm.tiktok.com` / `/t/` dan link penuh)
2. Jalur utama: web API `https://www.tiktok.com/api/item/detail/?aid=1988&itemId=...`
   dengan impersonate Chrome TLS (`curl_cffi`) + cookie `ms_token`
3. Fallback: parse `<script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">` dari halaman video
   (jalur paling andal — biasanya bekerja hanya dengan cookie `ms_token`)
4. Ranking kandidat: H.264 didahulukan, lalu resolusi (dari `GearName`) & bitrate tertinggi

> Catatan: endpoint `item/detail` bisa balas kosong dari beberapa jaringan. Jalur HTML
> (universal data) yang terbukti stabil. Cookie `ms_token` diambil dari browser login kamu.

## Error umum

- `statusCode 10204` + `person_geo_fencing` — IP/region diblokir TikTok. Gunakan proxy.
- `statusCode 10204` + `status_self_see` — video private (hanya untuk pembuatnya).
- `10216`/`10222` — butuh login / private.
- Pesan generic — video tak punya URL mp4 (slideshow/audio-only) atau cookie expired.

## Test

```bash
python -m unittest discover -s tests -v
```
