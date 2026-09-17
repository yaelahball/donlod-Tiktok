"""CLI entry point for tiktok-link."""

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from tiktok_link.client import TikTokClient, UA_MOBILE, download_media, load_cookie_string
from tiktok_link.errors import TikTokError
from tiktok_link.extractor import (
    extract_from_api,
    extract_from_api_data,
    extract_from_embed,
    extract_from_html,
    extract_sec_uid_from_html,
    extract_sec_uid_from_user_detail,
    extract_status,
    extract_user_embed_video_ids,
    extract_videos_from_list,
)
from tiktok_link.models import (
    DownloadEntry,
    default_state_path,
    load_state,
    rank_best,
    rank_candidates,
    save_state,
)
from tiktok_link.resolver import (
    extract_video_id,
    is_short_link,
    normalize_url,
)
from tiktok_link.ui import BatchReporter


def _is_waf_block(html):
    return bool(html) and "wafchallengeid" in html and "__UNIVERSAL_DATA_FOR_REHYDRATION__" not in html


def _fetch_page_waf_aware(client, url):
    """Fetch a page, solving the WAF challenge if the first response is blocked."""
    html = client.fetch_video_page(url)
    if _is_waf_block(html) and client.solve_waf_challenge(html):
        html = client.fetch_video_page(url)
    return html


def _resolve_via_mobile(client, url):
    """Fetch the video page with a mobile UA and parse the `api-data` script."""
    html = client.fetch_video_page(url, user_agent=UA_MOBILE)
    return extract_from_api_data(html)


def _resolve_via_embed(client, video_id):
    html = client.fetch_embed_page(video_id)
    return extract_from_embed(html)


def _resolve_via_html(client, url):
    """Fetch the desktop page (richest metadata), solving the WAF challenge if needed."""
    html = _fetch_page_waf_aware(client, url)
    info = extract_from_html(html)
    return info, html


def get_video_info(url, client):
    """Resolve a TikTok URL into a VideoInfo using layered fallbacks.

    Order: desktop HTML (richest candidates, WAF-solved) -> web API -> mobile
    page (`api-data`) -> embed page.
    """
    if is_short_link(url):
        url = client.resolve_short_link(url)
    else:
        url = normalize_url(url)

    video_id = extract_video_id(url)
    if not video_id:
        raise TikTokError("Tidak dapat menemukan video ID pada URL tersebut.")

    try:
        info, html = _resolve_via_html(client, url)
    except Exception:
        info, html = None, ""
    if info:
        return info

    try:
        payload = client.fetch_item_detail(video_id)
    except Exception:
        payload = None
    info = extract_from_api(payload) if payload else None
    if info:
        return info

    for resolver in (
        lambda: _resolve_via_mobile(client, url),
        lambda: _resolve_via_embed(client, video_id),
    ):
        try:
            info = resolver()
        except Exception:
            info = None
        if info:
            return info

    if html:
        status_code, status_msg = extract_status(html)
        if status_code in (10216, 10222):
            raise _tagged_error("Video private atau butuh login (statusCode %d)." % status_code, "soft")
        if status_code == 10204:
            if status_msg == "status_self_see":
                raise _tagged_error(
                    "Video private (hanya bisa dilihat pembuatnya, statusCode 10204).", "soft"
                )
            if status_msg == "person_geo_fencing":
                raise _tagged_error(
                    "Video dibatasi region (person_geo_fencing, statusCode 10204).", "soft"
                )
            raise _tagged_error(
                "TikTok menolak akses video ini (statusCode 10204, %s)." % (status_msg or "unknown"),
                "hard",
            )
        if status_code and status_code != 0:
            raise _tagged_error(
                "TikTok menolak akses video ini (statusCode %d)." % status_code, "hard"
            )

    raise _tagged_error(
        "Tidak dapat menemukan link MP4. Video mungkin private, butuh login, "
        "atau IP/cookie kamu diblokir.",
        "hard",
    )


def _pick(info, quality):
    if quality == "best":
        return rank_best(info.candidates)
    return rank_candidates(info.candidates)


def _fetch_profile_waf_aware(client, username):
    """Fetch a profile page, solving the WAF challenge if needed."""
    html = client.fetch_profile_page(username)
    if _is_waf_block(html) and client.solve_waf_challenge(html):
        html = client.fetch_profile_page(username)
    return html


def resolve_sec_uid(username, client, seed_url=None):
    """Resolve a username to its secUid.

    Falls back through: seed video -> profile HTML (WAF-solved) -> user/detail API
    -> profile embed's first video (re-resolved via a video page).
    """
    username = username.lstrip("@")

    if seed_url:
        try:
            html = fetch_page_with_retry(client, seed_url, retries=3, delay=1.0)
            info = extract_from_html(html) or extract_from_api_data(html)
            if info and info.sec_uid:
                return info.sec_uid
        except Exception:
            pass

    try:
        html = _fetch_profile_waf_aware(client, username)
        sec_uid = extract_sec_uid_from_html(html)
        if sec_uid:
            return sec_uid
    except Exception:
        pass

    try:
        payload = client.fetch_user_detail(username)
        sec_uid = extract_sec_uid_from_user_detail(payload)
        if sec_uid:
            return sec_uid
    except Exception:
        pass

    try:
        embed_html = client.fetch_user_embed_page(username)
        video_ids = extract_user_embed_video_ids(embed_html)
        if video_ids:
            info = get_video_info(
                "https://www.tiktok.com/@%s/video/%s" % (username, video_ids[0]), client
            )
            if info and info.sec_uid:
                return info.sec_uid
    except Exception:
        pass

    raise TikTokError(
        "Tidak dapat menemukan secUid untuk @%s. Halaman profil/API diblokir dari jaringan ini. "
        "Coba sediakan salah satu video user sebagai seed: --seed <url_video>." % username
    )


def list_user_videos(username, client, max_count=None, seed_url=None):
    """Fetch all (or up to max_count) videos from a user's profile."""
    sec_uid = resolve_sec_uid(username, client, seed_url=seed_url)
    videos = []
    cursor = str(int(time.time() * 1000))
    seen_cursors = set()

    while True:
        items, has_more, next_cursor = client.fetch_creator_item_list(sec_uid, cursor)
        infos = extract_videos_from_list({"itemList": items})
        videos.extend(infos)

        if max_count and len(videos) >= max_count:
            videos = videos[:max_count]
            break
        if not has_more or not next_cursor or str(next_cursor) in seen_cursors:
            break
        seen_cursors.add(str(next_cursor))
        cursor = str(next_cursor)

    return videos


def _format_plain(info, quality="h264"):
    best = _pick(info, quality)
    lines = [
        f"Video ID : {info.video_id}",
        f"Creator  : @{info.creator_username or '-'} ({info.creator_display_name or '-'})",
        f"Caption  : {info.caption or '-'}",
        f"Durasi   : {info.duration}s",
        "",
        "MP4 link terbaik:",
        best[0].url if best else "(tidak ada)",
    ]
    if best:
        lines += ["", "Semua kandidat:"]
        for candidate in best:
            codec = candidate.codec or "?"
            quality = f"{candidate.quality}p " if candidate.quality else ""
            bitrate = f"{candidate.bitrate // 1000}kbps " if candidate.bitrate else ""
            lines.append(f"  [{candidate.source}] {quality}{bitrate}{codec} {candidate.url}")
    return "\n".join(lines)


def _format_json(info, quality="h264"):
    best = _pick(info, quality)
    return json.dumps(
        {
            "video_id": info.video_id,
            "creator_username": info.creator_username,
            "creator_display_name": info.creator_display_name,
            "caption": info.caption,
            "duration": info.duration,
            "cover_url": info.cover_url,
            "best_url": best[0].url if best else None,
            "candidates": [c.__dict__ for c in best],
        },
        ensure_ascii=False,
        indent=2,
    )


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

    parser = argparse.ArgumentParser(prog="tiktok-link", description="Dapatkan link MP4 TikTok via HTTP murni")
    parser.add_argument("url", nargs="?", default=None,
                        help="URL video TikTok (vm.tiktok.com/xxx atau @user/video/id)")
    parser.add_argument("--user", default=None, help="Username TikTok (mis. shifaalmiraa) untuk list semua video")
    parser.add_argument("--seed", default=None, help="URL salah satu video user sebagai seed untuk resolve secUid (bila profil diblokir)")
    parser.add_argument("--max", type=int, default=None, help="Batas maksimal video saat list user (default: semua)")
    parser.add_argument("--download-all", action="store_true", help="Unduh semua video dari state file (otomatis resume)")
    parser.add_argument("--collect", action="store_true", help="Fase 1: kumpulkan daftar video + caption lalu simpan ke state file")
    parser.add_argument("--concurrency", type=int, default=3, help="Jumlah download paralel (default: 3)")
    parser.add_argument("--state", default=None, help="Path state file (default: <username>_downloads.json)")
    parser.add_argument("--output-dir", default="downloads", help="Folder dasar hasil download (default: downloads, jadi downloads/<username>/...)")
    parser.add_argument("--rate-delay", type=float, default=0.4, help="Jeda detik antar-resolve video untuk hindari rate-limit (default: 0.4)")
    parser.add_argument("--json", action="store_true", help="Output sebagai JSON")
    parser.add_argument("--download", nargs="?", const="", default=None,
                        help="Unduh mp4 terbaik. Bisa diikuti path tujuan (default: <username>_<id>.mp4)")
    parser.add_argument("--quality", choices=["h264", "best"], default="h264",
                        help="Pilih kualitas: h264 = terbaik dengan codec H.264 (default), best = resolusi tertinggi")
    parser.add_argument("--cookie", default=None, help='Cookie string, contoh: "ms_token=...; tt_webid=..."')
    parser.add_argument("--cookies-file", default="cookies.txt", help="Path file cookie (default: cookies.txt)")
    args = parser.parse_args(argv)

    cookie_string = load_cookie_string(args.cookie, file_path=args.cookies_file)
    client = TikTokClient(cookie_string="; ".join(f"{k}={v}" for k, v in cookie_string.items()))

    if args.user:
        return run_user_mode(args, client)

    if not args.url:
        parser.error("butuh argument url ATAU --user")

    try:
        info = get_video_info(args.url, client)
    except TikTokError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1

    if args.download is not None:
        best = _pick(info, args.quality)
        if not best:
            print("Error: tidak ada kandidat mp4 untuk diunduh.", file=sys.stderr)
            return 1
        user = info.creator_username or "unknown"
        if args.download:
            dest = args.download
        else:
            folder = os.path.join(args.output_dir, user)
            dest = os.path.join(folder, f"{user}_{info.video_id}.mp4")
        directory = os.path.dirname(dest)
        if directory:
            os.makedirs(directory, exist_ok=True)
        try:
            download_media(client.session, best[0].url, dest)
            print(f"Tersimpan: {dest}")
            return 0
        except Exception as error:
            print(f"Error unduh: {error}", file=sys.stderr)
            return 1

    if args.json:
        print(_format_json(info, args.quality))
    else:
        print(_format_plain(info, args.quality))
    return 0


def _format_user_list(videos):
    lines = [f"Total video: {len(videos)}", ""]
    for index, video in enumerate(videos, 1):
        lines.append(
            f"{index:>3}. {video.video_id}  @{video.creator_username or '-'}  "
            f"{video.caption[:40] or '-'}  {video.duration}s"
        )
    return "\n".join(lines)


def _format_user_list_json(videos):
    return json.dumps(
        [
            {
                "video_id": v.video_id,
                "creator_username": v.creator_username,
                "caption": v.caption,
                "duration": v.duration,
                "best_url": _pick(v, "h264")[0].url if v.candidates else None,
            }
            for v in videos
        ],
        ensure_ascii=False,
        indent=2,
    )


def run_user_mode(args, client):
    if args.collect:
        return run_collect(args, client)
    if args.download_all:
        return run_download_all(args, client)
    try:
        videos = list_user_videos(args.user, client, max_count=args.max, seed_url=args.seed)
    except TikTokError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    if args.json:
        print(_format_user_list_json(videos))
    else:
        print(_format_user_list(videos))
    return 0


def build_entries(username, videos, output_dir="downloads"):
    """Convert VideoInfo list into DownloadEntry list (all status=pending)."""
    username = username.lstrip("@")
    entries = []
    for index, video in enumerate(videos, 1):
        best = _pick(video, "h264")
        user = video.creator_username or username
        page_url = "https://www.tiktok.com/@%s/video/%s" % (user, video.video_id)
        folder = os.path.join(output_dir, user)
        filename = os.path.join(folder, "%d_%s_%s.mp4" % (index, video.video_id, user)).replace("\\", "/")
        entries.append(
            DownloadEntry(
                index=index,
                video_id=video.video_id,
                caption=video.caption or "",
                page_url=page_url,
                mp4_url=best[0].url if best else "",
                captured_at=int(time.time()),
                filename=filename,
                status="pending",
            )
        )
    return entries


def _has_ftyp(path):
    try:
        with open(path, "rb") as handle:
            return handle.read(8)[4:8] == b"ftyp"
    except OSError:
        return False


def _is_complete(path, expected_size=None):
    """A download counts as done only if it matches the expected size (when known)."""
    try:
        size = os.path.getsize(path)
    except OSError:
        return False
    if size <= 1024 or not _has_ftyp(path):
        return False
    if expected_size:
        return size >= expected_size * 0.99
    return True


def prepare_download_batch(entries):
    """Mark complete files as success; re-queue missing files; return (to_process, skipped)."""
    to_process = []
    skipped = 0
    for entry in entries:
        if entry.status == "success":
            if entry.filename and _is_complete(entry.filename, entry.expected_size):
                skipped += 1
                continue
            entry.status = "pending"
            entry.error = None
            to_process.append(entry)
            continue
        if entry.status in ("pending", "failed"):
            if entry.filename and _is_complete(entry.filename, entry.expected_size):
                entry.status = "success"
                entry.size = os.path.getsize(entry.filename)
                entry.error = None
                skipped += 1
                continue
            to_process.append(entry)
    return to_process, skipped


def _tagged_error(message, kind):
    error = TikTokError(message)
    error.kind = kind
    return error


HARD_FAILURE_THRESHOLD = 5


def fetch_page_with_retry(client, url, retries=3, delay=1.0):
    """Fetch a video page, retrying and solving the WAF challenge when needed."""
    html = ""
    for attempt in range(max(1, retries)):
        try:
            html = client.fetch_video_page(url)
            if _is_waf_block(html) and client.solve_waf_challenge(html):
                html = client.fetch_video_page(url)
        except Exception:
            html = ""
        if "__UNIVERSAL_DATA_FOR_REHYDRATION__" in html:
            return html
        if attempt < retries - 1:
            time.sleep(delay)
    return html


def classify_resolve_error(error):
    """Return ("soft"|"hard", reason).

    soft = per-video permanent failure (geo/private/no-candidates) - never aborts batch.
    hard = IP/cookie/rate-limit level (shell/no-data, 403/429, etc.) - may abort after threshold.
    """
    message = str(error).lower()
    kind = getattr(error, "kind", None)
    if kind in ("soft", "hard"):
        return kind, str(error)[:120]
    if "tidak dapat menemukan link mp4" in message:
        return "hard", str(error)[:120]
    soft_keywords = (
        "status_self_see", "private", "kandidat", "candidate",
        "butuh login", "person_geo_fencing", "geo_fencing",
    )
    if any(keyword in message for keyword in soft_keywords):
        return "soft", str(error)[:120]
    return "hard", str(error)[:120]


def probe_is_healthy(client, entries, retries=3, delay=1.0):
    """Canary probe: if ANY video page still returns data, the session is alive."""
    probes = [e for e in entries if e.page_url]
    if not probes:
        return False
    for entry in probes[:3]:
        html = fetch_page_with_retry(client, entry.page_url, retries=retries, delay=delay)
        if "__UNIVERSAL_DATA_FOR_REHYDRATION__" in html:
            return True
    return False


def process_download_batch(entries, client, concurrency, quality, reporter, state_path, username,
                           rate_delay=0.4):
    """Download pending/failed entries with a thread pool. Returns stats dict."""
    to_process, skipped = prepare_download_batch(entries)
    total = len(entries)
    success = failed = total_size = 0
    done = skipped
    consecutive_hard = 0
    stop = threading.Event()
    canary_in_progress = threading.Lock()
    canary_checked = False
    lock = threading.Lock()
    failures = []
    active = [0]

    save_state(state_path, username, entries, concurrency)

    def maybe_abort(entry, filename, reason):
        """Abort the batch only if a canary probe confirms cookie/IP death."""
        nonlocal consecutive_hard, canary_checked
        with canary_in_progress:
            if stop.is_set() or canary_checked:
                return
            canary_checked = True
        healthy = probe_is_healthy(client, entries, retries=3, delay=1.0)
        if healthy:
            with lock:
                consecutive_hard = 0
            reporter.fail(index=entry.index, total=total, filename=filename,
                          reason="%s (sementara)" % reason)
            return
        stop.set()

    def work(entry):
        nonlocal success, failed, total_size, done, consecutive_hard
        index, filename = entry.index, entry.filename
        try:
            if stop.is_set():
                reason = "cookie_expired"
                entry.status = "failed"
                entry.error = reason
                with lock:
                    failed += 1
                    done += 1
                    failures.append((filename, reason))
                    save_state(state_path, username, entries, concurrency)
                reporter.fail(index, total, filename, reason)
                return

            if rate_delay > 0:
                time.sleep(rate_delay)

            reporter.begin_video(index, total, filename)
            info = get_video_info(entry.page_url, client)
            best = _pick(info, quality)
            if not best:
                raise _tagged_error("tidak ada kandidat mp4", "soft")
            with lock:
                consecutive_hard = 0

            entry.status = "downloading"
            expected = {"size": 0}
            directory = os.path.dirname(filename)
            if directory:
                os.makedirs(directory, exist_ok=True)

            def on_progress(received, total_bytes, speed):
                if total_bytes:
                    expected["size"] = total_bytes
                reporter.progress(received, total_bytes, speed)

            received = download_media(client.session, best[0].url, filename, on_progress=on_progress)
            entry.status = "success"
            entry.error = None
            entry.size = received
            entry.expected_size = expected["size"] or received
            with lock:
                success += 1
                total_size += entry.size or 0
                done += 1
                save_state(state_path, username, entries, concurrency)
            reporter.success(index, total, filename, entry.size)
        except Exception as error:
            kind, reason = classify_resolve_error(error)
            entry.status = "failed"
            entry.error = reason
            with lock:
                if kind == "hard":
                    consecutive_hard += 1
                else:
                    consecutive_hard = 0
                failed += 1
                done += 1
                failures.append((filename, reason))
                save_state(state_path, username, entries, concurrency)
                hit_threshold = consecutive_hard >= HARD_FAILURE_THRESHOLD
            reporter.fail(index, total, filename, reason)
            if hit_threshold:
                maybe_abort(entry, filename, reason)
        finally:
            with lock:
                reporter.overall(done, total, max(0, active[0] - 1))

    def worker(entry):
        with lock:
            active[0] += 1
        try:
            work(entry)
        finally:
            with lock:
                active[0] -= 1

    if to_process:
        with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
            list(pool.map(worker, to_process))

    return {
        "total": total,
        "success": success,
        "failed": failed,
        "skipped": skipped,
        "total_size": total_size,
        "failures": failures,
    }


def run_collect(args, client):
    username = args.user.lstrip("@")
    try:
        videos = list_user_videos(args.user, client, max_count=args.max, seed_url=args.seed)
    except TikTokError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 1
    if not videos:
        print(f"Tidak ada video ditemukan untuk @{username}.")
        return 1
    entries = build_entries(username, videos, output_dir=args.output_dir)
    state_path = args.state or default_state_path(username)
    save_state(state_path, username, entries, args.concurrency)
    print(f"Tersimpan {len(entries)} video ke {state_path}")
    if args.json:
        print(_format_user_list_json(videos))
    else:
        print(_format_user_list(videos))
    return 0


def run_download_all(args, client):
    username = args.user.lstrip("@")
    state_path = args.state or default_state_path(username)
    state = load_state(state_path)
    if not state:
        print(
            f"Error: state file {state_path} tidak ditemukan. Jalankan --collect dulu.",
            file=sys.stderr,
        )
        return 1
    entries = [DownloadEntry.from_dict(v) for v in state.get("videos", []) if isinstance(v, dict)]
    if not entries:
        print("Error: state file kosong.", file=sys.stderr)
        return 1

    concurrency = max(1, args.concurrency)
    reporter = BatchReporter()
    reporter.start(username, len(entries), concurrency, state_path)
    start_time = time.time()
    result = process_download_batch(
        entries, client, concurrency, args.quality, reporter, state_path, username,
        rate_delay=args.rate_delay,
    )
    elapsed = time.time() - start_time
    reporter.finish(
        total=result["total"],
        success=result["success"],
        failed=result["failed"],
        skipped=result["skipped"],
        total_size=result["total_size"],
        elapsed=elapsed,
        failures=result["failures"],
        state_path=state_path,
    )
    return 1 if result["failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
