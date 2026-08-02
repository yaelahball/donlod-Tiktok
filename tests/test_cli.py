import unittest
import unittest.mock

from tiktok_link.cli import get_video_info
from tiktok_link.errors import TikTokError
from tests.test_extractor import API_PAYLOAD

HTML_WITH_DATA = (
    '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
    + __import__("json").dumps(API_PAYLOAD)
    + "</script></html>"
)


class FakeClient:
    def __init__(self, item_detail=API_PAYLOAD, page=HTML_WITH_DATA):
        self.item_detail = item_detail
        self.page = page
        self.requests = []

    def resolve_short_link(self, url):
        self.requests.append(("resolve", url))
        return "https://www.tiktok.com/@dave.xp/video/7234567890123456789"

    def fetch_item_detail(self, video_id):
        self.requests.append(("detail", video_id))
        if self.item_detail is False:
            raise RuntimeError("HTTP 403")
        return self.item_detail

    def fetch_video_page(self, url):
        self.requests.append(("page", url))
        return self.page


class TestGetVideoInfo(unittest.TestCase):
    def test_full_url_uses_api(self):
        info = get_video_info(
            "https://www.tiktok.com/@dave.xp/video/7234567890123456789", FakeClient()
        )
        self.assertEqual(info.video_id, "7234567890123456789")
        self.assertEqual(info.creator_username, "dave.xp")

    def test_short_link_is_resolved_first(self):
        client = FakeClient()
        info = get_video_info("https://vm.tiktok.com/ZMabcXYZ/", client)
        self.assertEqual(client.requests[0], ("resolve", "https://vm.tiktok.com/ZMabcXYZ/"))
        self.assertEqual(info.video_id, "7234567890123456789")

    def test_api_failure_falls_back_to_html(self):
        client = FakeClient(item_detail=False, page=HTML_WITH_DATA)
        info = get_video_info(
            "https://www.tiktok.com/@dave.xp/video/7234567890123456789", client
        )
        self.assertEqual(info.video_id, "7234567890123456789")
        self.assertIn(("page", unittest.mock.ANY), [(r[0], r[1]) for r in client.requests])

    def test_empty_api_falls_back_to_html(self):
        client = FakeClient(item_detail={}, page=HTML_WITH_DATA)
        info = get_video_info(
            "https://www.tiktok.com/@dave.xp/video/7234567890123456789", client
        )
        self.assertEqual(info.video_id, "7234567890123456789")

    def test_all_sources_fail_raises_error(self):
        client = FakeClient(item_detail={}, page="<html>no data</html>")
        with self.assertRaises(TikTokError):
            get_video_info(
                "https://www.tiktok.com/@dave.xp/video/7234567890123456789", client
            )

    def test_geo_blocked_status_code_reported(self):
        geo_html = (
            '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
            '{"__DEFAULT_SCOPE__": {"webapp.video-detail": '
            '{"statusCode": 10204, "statusMsg": "person_geo_fencing"}}}'
            "</script></html>"
        )
        client = FakeClient(item_detail={}, page=geo_html)
        with self.assertRaises(TikTokError) as ctx:
            get_video_info(
                "https://www.tiktok.com/@dave.xp/video/7234567890123456789", client
            )
        self.assertIn("10204", str(ctx.exception))

    def test_private_self_see_status_reported(self):
        private_html = (
            '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
            '{"__DEFAULT_SCOPE__": {"webapp.video-detail": '
            '{"statusCode": 10204, "statusMsg": "status_self_see"}}}'
            "</script></html>"
        )
        client = FakeClient(item_detail={}, page=private_html)
        with self.assertRaises(TikTokError) as ctx:
            get_video_info(
                "https://www.tiktok.com/@dave.xp/video/7234567890123456789", client
            )
        self.assertIn("private", str(ctx.exception).lower())

    def test_private_status_code_reported(self):
        private_html = (
            '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
            '{"__DEFAULT_SCOPE__": {"webapp.video-detail": {"statusCode": 10216}}}'
            "</script></html>"
        )
        client = FakeClient(item_detail={}, page=private_html)
        with self.assertRaises(TikTokError) as ctx:
            get_video_info(
                "https://www.tiktok.com/@dave.xp/video/7234567890123456789", client
            )
        self.assertIn("10216", str(ctx.exception))

    def test_invalid_url_raises_error(self):
        client = FakeClient()
        with self.assertRaises(TikTokError):
            get_video_info("https://example.com/not-tiktok", client)
