"""CLI entry point for tiktok-link."""

import argparse
import json
import sys

from tiktok_link.client import TikTokClient, download_media, load_cookie_string
from tiktok_link.errors import TikTokError
from tiktok_link.extractor import extract_from_api, extract_from_html, extract_status
from tiktok_link.models import rank_best, rank_candidates
from tiktok_link.resolver import (
    extract_video_id,
    is_short_link,
    normalize_url,
)


def get_video_info(url, client):
    """Resolve a TikTok URL into a VideoInfo, falling back API -> HTML."""
    if is_short_link(url):
        url = client.resolve_short_link(url)
    else:
        url = normalize_url(url)

    video_id = extract_video_id(url)
    if not video_id:
        raise TikTokError("Tidak dapat menemukan video ID pada URL tersebut.")

    try:
        payload = client.fetch_item_detail(video_id)
    except Exception:
        payload = None
    info = extract_from_api(payload) if payload else None

    if not info:
        html = client.fetch_video_page(url)
        info = extract_from_html(html)
        if not info:
            status_code, status_msg = extract_status(html)
            if status_code in (10216, 10222):
                raise TikTokError("Video private atau butuh login (statusCode %d)." % status_code)
            if status_code == 10204:
                if status_msg == "status_self_see":
                    raise TikTokError(
                        "Video private (hanya bisa dilihat pembuatnya, statusCode 10204)."
                    )
                if status_msg == "person_geo_fencing":
                    raise TikTokError(
                        "IP/region kamu diblokir oleh TikTok untuk video ini "
                        "(statusCode 10204). Coba pakai cookie login atau proxy."
                    )
                raise TikTokError(
                    "TikTok menolak akses video ini (statusCode 10204, %s)."
                    % (status_msg or "unknown")
                )
            if status_code and status_code != 0:
                raise TikTokError("TikTok menolak akses video ini (statusCode %d)." % status_code)

    if not info:
        raise TikTokError(
            "Tidak dapat menemukan link MP4. Video mungkin private, butuh login, "
            "atau IP/cookie kamu diblokir."
        )
    return info


def _pick(info, quality):
    if quality == "best":
        return rank_best(info.candidates)
    return rank_candidates(info.candidates)


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
    parser.add_argument("url", help="URL video TikTok (vm.tiktok.com/xxx atau @user/video/id)")
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
        dest = args.download or f"{info.creator_username or info.video_id}_{info.video_id}.mp4"
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


if __name__ == "__main__":
    sys.exit(main())
