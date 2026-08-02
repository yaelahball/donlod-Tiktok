# tiktok-link

CLI pure-HTTP untuk mendapatkan link MP4 langsung dari video TikTok (tanpa browser/extension).

Fitur:
- Ambil link MP4 langsung dari URL video / short link
- Download sistematis semua video satu username dengan **state file resume-able**
  (status per video: pending/success/failed, lanjut setelah cookie mati)
- Output CLI kaya: **progress bar per file + ringkasan agregat + report berwarna** (ANSI)
- Pilih kualitas H.264 (kompatibel) atau resolusi tertinggi (HEVC)
- Cookie login dari `cookies.txt`, flag, atau env var

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

### List & download semua video dari satu username

```bash
# List semua video dari username
python -m tiktok_link --user shifaalmiraa

# List + unduh semua video (berurutan)
python -m tiktok_link --user shifaalmiraa --download-all

# Batasi jumlah video
python -m tiktok_link --user shifaalmiraa --max 30

# Bila halaman profil/API diblokir dari jaringan kamu, sediakan seed video:
python -m tiktok_link --user shifaalmiraa --seed "https://www.tiktok.com/@shifaalmiraa/video/1234"
```

### Download sistematis per username (resume-able)

Sistem 2 fase: **collect** (simpan daftar video + caption ke state file) lalu **download**
(diproses dari list dengan flag status per video). Jika cookie mati/crash di tengah,
cukup jalankan ulang — tool lanjut dari video yang belum sukses.

```bash
# FASE 1 (wajib dulu): kumpulkan daftar video + caption, simpan ke <username>_downloads.json
python -m tiktok_link --user shifaalmiraa --collect [--seed <url>] [--max N]

# FASE 2: download semua dari list (otomatis resume)
python -m tiktok_link --user shifaalmiraa --download-all [--concurrency 3] [--quality best]
```

State file `shifaalmiraa_downloads.json` menyimpan per video: `video_id`, `caption`,
`page_url`, `mp4_url`, `status (pending/success/failed)`, `error`, `size`. URL mp4
di-resolve ulang segar sebelum tiap unduh (karena URL expire ±2 jam). File yang sudah
terunduh lengkap di-skip; file hilang/partial diunduh ulang. Deteksi cookie mati: setelah
3 resolve gagal beruntun, sisa video ditandai `failed (cookie_expired)` dan batch berhenti.

### Struktur folder hasil download

Hasil download disimpan rapi per username di `downloads/<username>/`:

```
tiktok-link/
└── downloads/
    └── shifaalmiraa/
        ├── 1_7668326382128352533_shifaalmiraa.mp4
        └── 2_7664517417640627477_shifaalmiraa.mp4
```

Folder dasar bisa diganti: `--output-dir /path/lain`. File state & hasil download
tidak ikut ke git (`.gitignore`).

Opsi:

| Flag | Keterangan |
|---|---|
| `--json` | Output sebagai JSON (termasuk semua URL kandidat) |
| `--download [PATH]` | Unduh mp4 terbaik ke file (default: `<username>_<id>.mp4`) |
| `--quality {h264,best}` | `h264` (default) = terbaik dengan codec H.264; `best` = resolusi tertinggi (bisa HEVC) |
| `--user <username>` | Mode list semua video dari username |
| `--seed <url_video>` | Seed video user (untuk resolve secUid bila profil diblokir) |
| `--max <n>` | Batas jumlah video saat list user (default: semua) |
| `--collect` | Fase 1: kumpulkan daftar video + caption → simpan state file |
| `--download-all` | Fase 2: download semua video dari state file (otomatis resume) |
| `--concurrency <n>` | Jumlah download paralel (default: 3) |
| `--state <path>` | Path state file (default: `<username>_downloads.json`) |
| `--output-dir <path>` | Folder dasar hasil download (default: `downloads`, jadi `downloads/<username>/...`) |
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
5. Mode `--user`: resolve `secUid` (profil HTML → `user/detail` API → seed video), lalu
   paginate `https://www.tiktok.com/api/creator/item_list/` hingga `hasMorePrevious=false`

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
