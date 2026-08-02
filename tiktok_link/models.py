"""Data models for TikTok video extraction."""

from dataclasses import dataclass, field


@dataclass
class MediaCandidate:
    url: str
    source: str
    quality: int = 0
    bitrate: int = 0
    width: int = 0
    height: int = 0
    codec: str = ""


@dataclass
class VideoInfo:
    video_id: str
    creator_username: str = ""
    creator_display_name: str = ""
    caption: str = ""
    duration: int = 0
    cover_url: str = ""
    sec_uid: str = ""
    candidates: list = field(default_factory=list)


def _is_h264(codec):
    return "h264" in codec or "avc" in codec


def _is_hevc(codec):
    return "hevc" in codec or "h265" in codec


def _quality_score(candidate):
    return (candidate.quality or 0) * 1_000_000 + (candidate.bitrate or 0)


def rank_candidates(candidates):
    """Return candidates sorted: H.264 first, then by quality score descending."""
    valid = [c for c in candidates if c.url and "dash" not in c.url.lower()]
    return sorted(
        valid,
        key=lambda c: (
            not _is_h264(c.codec),
            _is_hevc(c.codec),
            -_quality_score(c),
        ),
    )


def rank_best(candidates):
    """Return candidates sorted purely by quality score (highest resolution first)."""
    valid = [c for c in candidates if c.url and "dash" not in c.url.lower()]
    return sorted(valid, key=lambda c: -_quality_score(c))
