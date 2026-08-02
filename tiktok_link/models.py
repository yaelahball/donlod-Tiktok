"""Data models for TikTok video extraction."""

import json
import os
import tempfile

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


@dataclass
class DownloadEntry:
    index: int
    video_id: str
    caption: str = ""
    page_url: str = ""
    mp4_url: str = ""
    captured_at: int = 0
    filename: str = ""
    status: str = "pending"  # pending | downloading | success | failed
    error: str = None
    size: int = None
    expected_size: int = None

    def to_dict(self):
        return {
            "index": self.index,
            "video_id": self.video_id,
            "caption": self.caption,
            "page_url": self.page_url,
            "mp4_url": self.mp4_url,
            "captured_at": self.captured_at,
            "filename": self.filename,
            "status": self.status,
            "error": self.error,
            "size": self.size,
            "expected_size": self.expected_size,
        }

    @staticmethod
    def from_dict(data):
        if not isinstance(data, dict):
            return None
        return DownloadEntry(
            index=data.get("index", 0),
            video_id=data.get("video_id", ""),
            caption=data.get("caption", ""),
            page_url=data.get("page_url", ""),
            mp4_url=data.get("mp4_url", ""),
            captured_at=data.get("captured_at", 0),
            filename=data.get("filename", ""),
            status=data.get("status", "pending"),
            error=data.get("error"),
            size=data.get("size"),
            expected_size=data.get("expected_size"),
        )


def default_state_path(username):
    return "%s_downloads.json" % username.lstrip("@")


def save_state(path, username, entries, concurrency=1):
    """Atomically write the download state file."""
    payload = {
        "username": username.lstrip("@"),
        "created_at": int(__import__("time").time()),
        "concurrency": concurrency,
        "videos": [entry.to_dict() for entry in entries],
    }
    directory = os.path.dirname(os.path.abspath(path))
    fd, tmp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
        os.replace(tmp_path, path)
    finally:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)


def load_state(path):
    """Load a download state file. Returns dict or None if missing/invalid."""
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError):
        return None
