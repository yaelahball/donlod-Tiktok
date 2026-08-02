"""HTTP client with Chrome TLS impersonation and cookie handling."""

import os
import random
import string

from curl_cffi.requests import Session

API_ITEM_DETAIL = "https://www.tiktok.com/api/item/detail/"


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


def download_media(session, url, dest, referer="https://www.tiktok.com/"):
    """Download a media URL to dest using the given session. Returns dest."""
    response = session.get(
        url,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
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
    with open(dest, "wb") as handle:
        if hasattr(response, "iter_content"):
            for chunk in response.iter_content(chunk_size=65536):
                if chunk:
                    handle.write(chunk)
        else:
            handle.write(response.content)
    return dest


class TikTokClient:
    def __init__(self, cookie_string=None):
        cookies = parse_cookie_string(cookie_string)
        self.session = Session(impersonate="chrome")
        if cookies:
            self.session.cookies.update(cookies)
        self.verify_fp = generate_verify_fp()

    def _common_headers(self, referer="https://www.tiktok.com/"):
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
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

    def fetch_video_page(self, page_url):
        response = self.session.get(page_url, headers=self._common_headers(page_url), timeout=20)
        response.raise_for_status()
        return response.text

    def resolve_short_link(self, url):
        response = self.session.get(url, headers=self._common_headers(), timeout=20, allow_redirects=True)
        return response.url
