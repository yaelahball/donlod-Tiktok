"""HTTP client with Chrome TLS impersonation and cookie handling."""

import base64
import hashlib
import json
import os
import random
import re
import string
import time

from curl_cffi.requests import Session

API_ITEM_DETAIL = "https://www.tiktok.com/api/item/detail/"

UA_DESKTOP = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
)
UA_MOBILE = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1"
)


def generate_verify_fp():
    return "verify_" + "".join(random.choices(string.hexdigits, k=7))


def parse_cookie_string(value):
    """Parse a 'name=value; name2=value2' cookie string into a dict."""
    cookies = {}
    if not value:
        return cookies
    for segment in value.split(";"):
        segment = segment.strip()
        if "=" not in segment:
            continue
        name, _, val = segment.partition("=")
        name = name.strip()
        val = val.strip()
        if name:
            cookies[name] = val
    return cookies


def load_cookie_string(cookie_flag, env_name="TIKTOK_COOKIE", file_path="cookies.txt"):
    """Resolve cookie source by priority: flag > env > file."""
    if cookie_flag:
        return parse_cookie_string(cookie_flag)
    env_value = os.environ.get(env_name)
    if env_value:
        return parse_cookie_string(env_value)
    if os.path.isfile(file_path):
        with open(file_path, "r", encoding="utf-8") as handle:
            return parse_cookie_string(handle.read().strip())
    return {}


def download_media(session, url, dest, referer="https://www.tiktok.com/", on_progress=None):
    """Download a media URL to dest using the given session. Returns dest."""
    response = session.get(
        url,
        headers={
            "User-Agent": UA_DESKTOP,
            "Referer": referer,
        },
        timeout=60,
        stream=True,
    )
    if response.status_code != 200:
        raise RuntimeError("Download gagal dengan status %s" % response.status_code)
    content_type = response.headers.get("Content-Type", "")
    if "video" not in content_type.lower() and "octet-stream" not in content_type.lower():
        raise RuntimeError("Respons bukan video (Content-Type: %s)" % content_type)
    total = int(response.headers.get("Content-Length") or 0) or 0
    received = 0
    start = time.time()
    with open(dest, "wb") as handle:
        if hasattr(response, "iter_content"):
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    handle.write(chunk)
                    received += len(chunk)
                    if on_progress:
                        elapsed = time.time() - start
                        speed = received / elapsed if elapsed > 0 else 0
                        on_progress(received, total, speed)
        else:
            data = response.content
            handle.write(data)
            received = len(data)
            if on_progress:
                on_progress(received, received, 0)
    return received


class TikTokClient:
    def __init__(self, cookie_string=None):
        cookies = parse_cookie_string(cookie_string)
        self.session = Session(impersonate="chrome")
        if cookies:
            self.session.cookies.update(cookies)
        self.verify_fp = generate_verify_fp()

    def _common_headers(self, referer="https://www.tiktok.com/", user_agent=UA_DESKTOP):
        return {
            "User-Agent": user_agent,
            "Accept": "application/json, text/plain, */*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": referer,
        }

    def fetch_item_detail(self, video_id):
        params = {
            "aid": "1988",
            "itemId": video_id,
            "verifyFp": self.verify_fp,
        }
        response = self.session.get(
            API_ITEM_DETAIL, params=params, headers=self._common_headers(), timeout=20
        )
        response.raise_for_status()
        return response.json()

    def fetch_video_page(self, page_url, user_agent=UA_DESKTOP):
        response = self.session.get(
            page_url,
            headers=self._common_headers(page_url, user_agent=user_agent),
            timeout=20,
        )
        response.raise_for_status()
        return response.text

    def fetch_embed_page(self, video_id):
        """Fetch the public embed page, which usually bypasses the video WAF."""
        url = f"https://www.tiktok.com/embed/v2/{video_id}"
        response = self.session.get(
            url,
            headers=self._common_headers("https://www.tiktok.com/"),
            timeout=20,
        )
        response.raise_for_status()
        return response.text

    def solve_waf_challenge(self, html):
        """Solve TikTok's Slardar proof-of-work challenge and set the cookies.

        Returns True if challenge cookies were set, False otherwise.
        Pure Python (hashlib) implementation, no browser required.
        """
        if not html or "wafchallengeid" not in html:
            return False

        cs_match = re.search(
            r'<p[^>]+id=["\']cs["\'][^>]*class=["\']([^"\']+)["\']', html, re.IGNORECASE
        )
        wci_match = re.search(
            r'<p[^>]+id=["\']wci["\'][^>]*class=["\']([^"\']+)["\']', html, re.IGNORECASE
        )
        if not cs_match or not wci_match:
            return False

        try:
            challenge = json.loads(base64.b64decode(cs_match.group(1) + "==="))
            expected = base64.b64decode(challenge["v"]["c"])
            base_hash = hashlib.sha256(base64.b64decode(challenge["v"]["a"]))
        except (KeyError, ValueError, TypeError):
            return False

        for number in range(1_000_001):
            test_hash = base_hash.copy()
            test_hash.update(str(number).encode())
            if test_hash.digest() == expected:
                challenge["d"] = base64.b64encode(str(number).encode()).decode()
                break
        else:
            return False

        cookie_name = wci_match.group(1)
        cookie_value = base64.b64encode(
            json.dumps(challenge, separators=(",", ":")).encode()
        ).decode()
        self.session.cookies.set(cookie_name, cookie_value, domain=".tiktok.com")
        return True

    def fetch_profile_page(self, username):
        username = username.lstrip("@")
        response = self.session.get(
            f"https://www.tiktok.com/@{username}",
            headers=self._common_headers(f"https://www.tiktok.com/@{username}"),
            timeout=20,
            allow_redirects=True,
        )
        response.raise_for_status()
        return response.text

    def fetch_user_detail(self, unique_id):
        params = {
            "uniqueId": unique_id.lstrip("@"),
            "aid": "1988",
            "app_language": "en",
            "app_name": "tiktok_web",
            "browser_language": "en-US",
            "browser_name": "Mozilla",
            "browser_online": "true",
            "browser_platform": "Win32",
            "browser_version": "5.0 (Windows)",
            "channel": "tiktok_web",
            "cookie_enabled": "true",
            "device_platform": "web_pc",
            "focus_state": "true",
            "history_len": "2",
            "is_fullscreen": "false",
            "is_page_visible": "true",
            "language": "en",
            "os": "windows",
            "priority_region": "",
            "region": "US",
            "screen_height": "1080",
            "screen_width": "1920",
            "tz_name": "UTC",
            "verifyFp": self.verify_fp,
            "webcast_language": "en",
        }
        response = self.session.get(
            "https://www.tiktok.com/api/user/detail/",
            params=params,
            headers=self._common_headers(),
            timeout=20,
        )
        response.raise_for_status()
        return response.json()

    def fetch_creator_item_list(self, sec_uid, cursor, count=15):
        params = {
            "aid": "1988",
            "app_language": "en",
            "app_name": "tiktok_web",
            "browser_language": "en-US",
            "browser_name": "Mozilla",
            "browser_online": "true",
            "browser_platform": "Win32",
            "browser_version": "5.0 (Windows)",
            "channel": "tiktok_web",
            "cookie_enabled": "true",
            "count": str(count),
            "cursor": str(cursor),
            "device_platform": "web_pc",
            "focus_state": "true",
            "from_page": "user",
            "history_len": "2",
            "is_fullscreen": "false",
            "is_page_visible": "true",
            "language": "en",
            "os": "windows",
            "priority_region": "",
            "referer": "",
            "region": "US",
            "screen_height": "1080",
            "screen_width": "1920",
            "secUid": sec_uid,
            "type": "1",
            "tz_name": "UTC",
            "verifyFp": self.verify_fp,
            "webcast_language": "en",
        }
        response = self.session.get(
            "https://www.tiktok.com/api/creator/item_list/",
            params=params,
            headers=self._common_headers(),
            timeout=20,
        )
        response.raise_for_status()
        body = response.json()
        items = body.get("itemList") or []
        has_more = bool(body.get("hasMorePrevious"))
        if items:
            create_time = items[-1].get("createTime")
            next_cursor = int(create_time * 1000) if create_time else None
        else:
            next_cursor = None
        return items, has_more, next_cursor

    def resolve_short_link(self, url):
        response = self.session.get(url, headers=self._common_headers(), timeout=20, allow_redirects=True)
        return response.url
