"""Parse TikTok web API JSON and page HTML into VideoInfo."""

import json
import re

from tiktok_link.models import MediaCandidate, VideoInfo


def _first_int(*values):
    for value in values:
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number > 0:
            return number
    return 0


def _quality_from_gear(gear_name, fallback):
    """Parse resolution like 'normal_540_0' -> 540, else fallback."""
    if gear_name:
        match = re.search(r"(\d{3,4})", str(gear_name))
        if match:
            return int(match.group(1))
    return fallback


def _extract_candidates(video):
    candidates = []
    seen = set()

    def push(url, source, quality=0, bitrate=0, width=0, height=0, codec=""):
        if not url or url in seen:
            return
        seen.add(url)
        candidates.append(
            MediaCandidate(
                url=url, source=source, quality=quality, bitrate=bitrate,
                width=width, height=height, codec=codec,
            )
        )

    bitrate_info = video.get("bitrateInfo") or video.get("bitrate_info") or []
    for entry in bitrate_info:
        if not isinstance(entry, dict):
            continue
        play_addr = entry.get("PlayAddr") or entry.get("playAddr") or entry.get("play_addr") or {}
        url_list = play_addr.get("UrlList") or play_addr.get("url_list") or play_addr.get("urlList") or []
        for url in url_list:
            push(
                url,
                "bitrateInfo",
                _quality_from_gear(
                    entry.get("GearName"),
                    _first_int(entry.get("QualityType"), entry.get("qualityType")),
                ),
                _first_int(entry.get("Bitrate"), entry.get("bitrate")),
                _first_int(play_addr.get("Width"), play_addr.get("width")),
                _first_int(play_addr.get("Height"), play_addr.get("height")),
                str(entry.get("CodecType") or entry.get("codecType") or entry.get("codec") or "").lower(),
            )

    for key, source in (("playAddr", "playAddr"), ("play_addr", "playAddr"),
                        ("downloadAddr", "downloadAddr"), ("download_addr", "downloadAddr")):
        addr = video.get(key) or {}
        if isinstance(addr, str):
            push(addr, source)
            continue
        url_list = addr.get("UrlList") or addr.get("url_list") or addr.get("urlList") or []
        for url in url_list:
            push(
                url, source,
                _first_int(addr.get("Height")), 0,
                _first_int(addr.get("Width")), _first_int(addr.get("Height")),
                str(addr.get("codecType") or "").lower(),
            )

    return candidates


def _build_video_info(item_struct):
    if not isinstance(item_struct, dict):
        return None
    video_id = item_struct.get("id") or item_struct.get("aweme_id")
    if not video_id:
        return None

    author = item_struct.get("author") or {}
    video = item_struct.get("video") or {}
    candidates = _extract_candidates(video)

    return VideoInfo(
        video_id=str(video_id),
        creator_username=author.get("uniqueId") or author.get("unique_id") or "",
        creator_display_name=author.get("nickname") or "",
        caption=item_struct.get("desc") or "",
        duration=_first_int(video.get("duration"), item_struct.get("createTime")),
        cover_url=(video.get("cover") or {}).get("urlList", [""])[0] if isinstance(video.get("cover"), dict) else str(video.get("cover") or ""),
        candidates=candidates,
    )


def extract_from_api(payload):
    """Extract VideoInfo from a web API JSON payload."""
    if not isinstance(payload, dict):
        return None
    item_struct = (
        payload.get("itemInfo", {}).get("itemStruct")
        or payload.get("itemInfo", {}).get("item_struct")
        or payload.get("itemStruct")
        or payload.get("item_struct")
    )
    if item_struct:
        return _build_video_info(item_struct)

    item_list = payload.get("itemList") or payload.get("item_list") or []
    for item in item_list:
        info = _build_video_info(item)
        if info:
            return info
    return None


def extract_status(html):
    """Return (statusCode, statusMsg) from page HTML, or (None, None)."""
    match = re.search(
        r'<script[^>]+id=["\']__UNIVERSAL_DATA_FOR_REHYDRATION__["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None, None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None, None
    detail = (data.get("__DEFAULT_SCOPE__") or {}).get("webapp.video-detail") or {}
    code = detail.get("statusCode")
    return (code if isinstance(code, int) else None), detail.get("statusMsg")


def extract_from_html(html):
    """Extract VideoInfo from a TikTok video page's universal data script."""
    match = re.search(
        r'<script[^>]+id=["\']__UNIVERSAL_DATA_FOR_REHYDRATION__["\'][^>]*>(.*?)</script>',
        html,
        re.DOTALL | re.IGNORECASE,
    )
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None

    scope = (data or {}).get("__DEFAULT_SCOPE__") or {}
    detail = scope.get("webapp.video-detail") or {}
    return extract_from_api(detail or data)
