import io
import os
import tempfile
import unittest
from unittest.mock import patch

from tiktok_link.cli import (
    classify_resolve_error,
    fetch_page_with_retry,
    process_download_batch,
)
from tiktok_link.errors import TikTokError
from tiktok_link.models import DownloadEntry
from tiktok_link.ui import BatchReporter
from tests.test_download import FakeSession

HTML_WITH_DATA = (
    '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
    '{"__DEFAULT_SCOPE__": {"webapp.video-detail": {"statusCode": 0, "itemInfo": {"itemStruct": '
    '{"id": "1", "author": {"uniqueId": "dave.xp"}, "video": {'
    '"bitrateInfo": [{"GearName": "normal_540_0", "CodecType": "h264", '
    '"PlayAddr": {"UrlList": ["https://v19.tiktokcdn.com/1.mp4"]}}]}}}}}}'
    "</script></html>"
)
GEO_HTML = (
    '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
    '{"__DEFAULT_SCOPE__": {"webapp.video-detail": {"statusCode": 10204, "statusMsg": "person_geo_fencing"}}}'
    "</script></html>"
)
SHELL_HTML = "<html><body>bot check shell</body></html>"


class FakePageClient:
    def __init__(self, page):
        self.page = page
        self.session = FakeSession()

    def fetch_item_detail(self, video_id):
        return {}

    def fetch_video_page(self, url):
        return self.page

    def resolve_short_link(self, url):
        return url


def _entry(i):
    return DownloadEntry(
        index=i, video_id=str(i), filename="v%d.mp4" % i,
        page_url="https://www.tiktok.com/@dave.xp/video/123", status="pending",
    )


def _fast_retry(client, url, retries=3, delay=1.0):
    try:
        return client.fetch_video_page(url)
    except Exception:
        return ""


class TestClassifyResolveError(unittest.TestCase):
    def test_geo_is_soft(self):
        kind, _ = classify_resolve_error(TikTokError("Video dibatasi region (person_geo_fencing, statusCode 10204)."))
        self.assertEqual(kind, "soft")

    def test_private_is_soft(self):
        kind, _ = classify_resolve_error(TikTokError("Video private atau butuh login (statusCode 10216)."))
        self.assertEqual(kind, "soft")

    def test_no_candidates_is_soft(self):
        kind, _ = classify_resolve_error(TikTokError("tidak ada kandidat mp4"))
        self.assertEqual(kind, "soft")

    def test_generic_shell_is_hard(self):
        kind, _ = classify_resolve_error(TikTokError("Tidak dapat menemukan link MP4. Video mungkin private, butuh login, atau IP/cookie kamu diblokir."))
        self.assertEqual(kind, "hard")

    def test_http_403_is_hard(self):
        kind, _ = classify_resolve_error(RuntimeError("HTTP 403"))
        self.assertEqual(kind, "hard")


class TestFetchPageWithRetry(unittest.TestCase):
    def test_retries_until_data_appears(self):
        class Flaky:
            def __init__(self):
                self.calls = 0

            def fetch_video_page(self, url):
                self.calls += 1
                if self.calls < 2:
                    raise RuntimeError("403")
                return HTML_WITH_DATA

        client = Flaky()
        html = fetch_page_with_retry(client, "url", retries=3, delay=0)
        self.assertIn("__UNIVERSAL_DATA_FOR_REHYDRATION__", html)
        self.assertEqual(client.calls, 2)

    def test_gives_up_after_all_retries(self):
        class AlwaysFail:
            def fetch_video_page(self, url):
                raise RuntimeError("403")

        self.assertEqual(fetch_page_with_retry(AlwaysFail(), "url", retries=3, delay=0), "")


class TestBatchRobustness(unittest.TestCase):
    def test_hard_failures_below_threshold_do_not_abort(self):
        entries = [_entry(i) for i in range(1, 4)]  # 3 < threshold 5
        reporter = BatchReporter(stream=io.StringIO(), use_color=False)
        with patch("tiktok_link.cli.fetch_page_with_retry", side_effect=_fast_retry):
            result = process_download_batch(
                entries, FakePageClient(SHELL_HTML), concurrency=1, quality="h264",
                reporter=reporter, state_path="s.json", username="dave.xp", rate_delay=0,
            )
        self.assertEqual(result["success"], 0)
        self.assertEqual(result["failed"], 3)
        self.assertTrue(all("cookie_expired" not in (e.error or "") for e in entries))
        self.assertTrue(all("Tidak dapat menemukan" in (e.error or "") for e in entries))

    def test_soft_failures_keep_real_reason(self):
        entries = [_entry(i) for i in range(1, 4)]
        reporter = BatchReporter(stream=io.StringIO(), use_color=False)
        with patch("tiktok_link.cli.fetch_page_with_retry", side_effect=_fast_retry):
            result = process_download_batch(
                entries, FakePageClient(GEO_HTML), concurrency=1, quality="h264",
                reporter=reporter, state_path="s.json", username="dave.xp", rate_delay=0,
            )
        self.assertEqual(result["failed"], 3)
        self.assertTrue(all("geo_fencing" in (e.error or "") for e in entries))

    def test_canary_healthy_prevents_abort(self):
        entries = [_entry(i) for i in range(1, 7)]  # 6 > threshold 5
        reporter = BatchReporter(stream=io.StringIO(), use_color=False)
        with patch("tiktok_link.cli.fetch_page_with_retry", side_effect=_fast_retry), \
             patch("tiktok_link.cli.probe_is_healthy", return_value=True):
            result = process_download_batch(
                entries, FakePageClient(SHELL_HTML), concurrency=1, quality="h264",
                reporter=reporter, state_path="s.json", username="dave.xp", rate_delay=0,
            )
        self.assertEqual(result["failed"], 6)
        self.assertTrue(all("cookie_expired" not in (e.error or "") for e in entries))

    def test_canary_death_confirms_abort(self):
        entries = [_entry(i) for i in range(1, 7)]
        reporter = BatchReporter(stream=io.StringIO(), use_color=False)
        with patch("tiktok_link.cli.fetch_page_with_retry", side_effect=_fast_retry), \
             patch("tiktok_link.cli.probe_is_healthy", return_value=False):
            result = process_download_batch(
                entries, FakePageClient(SHELL_HTML), concurrency=1, quality="h264",
                reporter=reporter, state_path="s.json", username="dave.xp", rate_delay=0,
            )
        self.assertEqual(result["failed"], 6)
        cookie_deaths = sum(1 for e in entries if (e.error or "") == "cookie_expired")
        self.assertGreater(cookie_deaths, 0)

    def test_creates_output_folder_before_download(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            os.chdir(tmp)
            try:
                entry = DownloadEntry(
                    index=1, video_id="1",
                    filename="downloads/dave.xp/1_1_dave.xp.mp4",
                    page_url="https://www.tiktok.com/@dave.xp/video/7234567890123456789",
                    status="pending",
                )
                reporter = BatchReporter(stream=io.StringIO(), use_color=False)
                process_download_batch([entry], FakePageClient(HTML_WITH_DATA), concurrency=1,
                                       quality="h264", reporter=reporter,
                                       state_path="state.json", username="dave.xp", rate_delay=0)
                self.assertTrue(os.path.isfile("downloads/dave.xp/1_1_dave.xp.mp4"))
                self.assertEqual(entry.status, "success")
            finally:
                os.chdir(old)
