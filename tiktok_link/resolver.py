"""URL normalization and metadata extraction for TikTok video links."""

import re

from urllib.parse import urlparse, urlunparse


def normalize_url(url):
    """Strip query, fragment, and trailing slash from a TikTok video URL."""
    parsed = urlparse(url)
    normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, "", "", ""))
    return normalized.rstrip("/")


def extract_video_id(url):
    """Return the numeric video ID, or None if the URL is a short link."""
    normalized = normalize_url(url)
    match = re.search(r"/video/(\d+)", normalized)
    return match.group(1) if match else None


def extract_username(url):
    """Return the @username (without @), or None if absent."""
    match = re.search(r"/@([^/]+)/", normalize_url(url))
    return match.group(1) if match else None


def is_short_link(url):
    parsed = urlparse(url)
    hostname = parsed.hostname or ""
    return hostname.startswith("vm.tiktok.com") or parsed.path.startswith("/t/")
