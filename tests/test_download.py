import os
import tempfile
import unittest

from tiktok_link.client import download_media


class FakeResponse:
    status_code = 200
    headers = {"Content-Type": "video/mp4"}
    content = b"MP4DATA"

    def iter_content(self, chunk_size):
        yield self.content


class FakeSession:
    def __init__(self, response=None, status_code=200):
        self.response = response or FakeResponse()
        self.response.status_code = status_code

    def get(self, url, headers=None, timeout=None, stream=False):
        self.last_url = url
        self.last_headers = headers
        return self.response


class TestDownloadMedia(unittest.TestCase):
    def test_downloads_and_writes_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "video.mp4")
            session = FakeSession()
            result = download_media(session, "https://v16.tiktokcdn.com/a.mp4", dest)
            self.assertEqual(result, dest)
            with open(dest, "rb") as handle:
                self.assertEqual(handle.read(), b"MP4DATA")

    def test_sends_referer_header(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "video.mp4")
            session = FakeSession()
            download_media(session, "https://v16.tiktokcdn.com/a.mp4", dest)
            self.assertEqual(session.last_headers.get("Referer"), "https://www.tiktok.com/")

    def test_raises_on_non_video_content_type(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "video.mp4")
            response = FakeResponse()
            response.headers = {"Content-Type": "text/html"}
            session = FakeSession(response)
            with self.assertRaises(Exception):
                download_media(session, "https://v16.tiktokcdn.com/a.mp4", dest)

    def test_raises_on_http_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            dest = os.path.join(tmp, "video.mp4")
            session = FakeSession(status_code=403)
            with self.assertRaises(Exception):
                download_media(session, "https://v16.tiktokcdn.com/a.mp4", dest)
