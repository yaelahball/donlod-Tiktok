import unittest

from tiktok_link.cli import list_user_videos, resolve_sec_uid
from tiktok_link.errors import TikTokError
from tiktok_link.extractor import (
    extract_sec_uid_from_html,
    extract_sec_uid_from_user_detail,
    extract_user_embed_video_ids,
    extract_videos_from_list,
)
from tests.test_extractor import API_PAYLOAD

USER_HTML = (
    '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
    '{"__DEFAULT_SCOPE__": {"webapp.user-detail": {"userInfo": '
    '{"user": {"secUid": "MS4wLjABAAAAabc", "uniqueId": "dave.xp"}}}}}'
    "</script></html>"
)

USER_DETAIL_PAYLOAD = {
    "userInfo": {"user": {"secUid": "MS4wLjABAAAAxyz", "uniqueId": "dave.xp"}}
}


class TestExtractSecUidFromHtml(unittest.TestCase):
    def test_extracts_sec_uid_from_profile_page(self):
        self.assertEqual(extract_sec_uid_from_html(USER_HTML), "MS4wLjABAAAAabc")

    def test_returns_none_when_missing(self):
        self.assertIsNone(extract_sec_uid_from_html("<html></html>"))
        self.assertIsNone(
            extract_sec_uid_from_html(
                '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{"a":1}</script></html>'
            )
        )


class TestExtractSecUidFromUserDetail(unittest.TestCase):
    def test_extracts_from_api_payload(self):
        self.assertEqual(
            extract_sec_uid_from_user_detail(USER_DETAIL_PAYLOAD), "MS4wLjABAAAAxyz"
        )

    def test_returns_none_when_missing(self):
        self.assertIsNone(extract_sec_uid_from_user_detail({}))
        self.assertIsNone(extract_sec_uid_from_user_detail(None))


class TestExtractVideosFromList(unittest.TestCase):
    def test_extracts_all_items(self):
        payload = {"itemList": [API_PAYLOAD["itemInfo"]["itemStruct"], API_PAYLOAD["itemInfo"]["itemStruct"]]}
        videos = extract_videos_from_list(payload)
        self.assertEqual(len(videos), 2)
        self.assertEqual(videos[0].video_id, "7234567890123456789")

    def test_empty_list_returns_empty(self):
        self.assertEqual(extract_videos_from_list({}), [])
        self.assertEqual(extract_videos_from_list({"itemList": []}), [])


EMBED_USER_HTML = (
    '<script id="__FRONTITY_CONNECT_STATE__">'
    '{"source": {"data": {"/embed/@dave.xp": {"videoList": [{"id": "111"}, {"id": "222"}]}}}}'
    "</script>"
)


class TestExtractUserEmbedVideoIds(unittest.TestCase):
    def test_returns_video_ids(self):
        self.assertEqual(extract_user_embed_video_ids(EMBED_USER_HTML), ["111", "222"])

    def test_returns_empty_when_missing(self):
        self.assertEqual(extract_user_embed_video_ids("<html></html>"), [])
        self.assertEqual(
            extract_user_embed_video_ids(
                '<script id="__FRONTITY_CONNECT_STATE__">{"source": {"data": {}}}</script>'
            ),
            [],
        )


class FakeListClient:
    def __init__(self, pages, sec_uid="MS4wLjABAAAAabc"):
        self.pages = pages
        self.sec_uid = sec_uid
        self.calls = []

    def fetch_profile_page(self, username):
        self.calls.append(("profile", username))
        return USER_HTML

    def fetch_user_detail(self, username):
        self.calls.append(("detail", username))
        return {}

    def fetch_creator_item_list(self, sec_uid, cursor, count=15):
        self.calls.append(("items", sec_uid, cursor))
        return self.pages.pop(0)
class TestResolveSecUid(unittest.TestCase):
    def test_uses_profile_html_first(self):
        client = FakeListClient(pages=[])
        self.assertEqual(resolve_sec_uid("dave.xp", client), "MS4wLjABAAAAabc")

    def test_falls_back_to_user_detail(self):
        class DetailOnly(FakeListClient):
            def fetch_profile_page(self, username):
                return "<html></html>"

            def fetch_user_detail(self, username):
                return USER_DETAIL_PAYLOAD

        self.assertEqual(resolve_sec_uid("dave.xp", DetailOnly(pages=[])), "MS4wLjABAAAAxyz")

    def test_raises_when_unresolvable(self):
        class Empty(FakeListClient):
            def fetch_profile_page(self, username):
                return "<html></html>"

        with self.assertRaises(TikTokError):
            resolve_sec_uid("dave.xp", Empty(pages=[]))

    def test_solves_waf_then_reads_profile(self):
        class WafThenData(FakeListClient):
            def __init__(self):
                super().__init__(pages=[])
                self.solved = False
                self.challenge_cookie = None

            def fetch_profile_page(self, username):
                if not self.solved:
                    return '<html><p id="wci" class="_wafchallengeid"></p></html>'
                return USER_HTML

            def solve_waf_challenge(self, html):
                self.solved = True
                return True

        client = WafThenData()
        self.assertEqual(resolve_sec_uid("dave.xp", client), "MS4wLjABAAAAabc")
        self.assertTrue(client.solved)


def _item(video_id):
    return {
        "id": video_id,
        "desc": "caption %s" % video_id,
        "author": {"uniqueId": "dave.xp", "nickname": "Dave"},
        "video": {
            "duration": 5000,
            "bitrateInfo": [
                {
                    "QualityType": 20,
                    "GearName": "normal_540_0",
                    "CodecType": "h264",
                    "PlayAddr": {"UrlList": ["https://v19.tiktokcdn.com/%s.mp4" % video_id]},
                }
            ],
        },
    }


class TestListUserVideos(unittest.TestCase):
    def test_paginates_until_no_more(self):
        page1 = ([_item("1"), _item("2")], True, "100")
        page2 = ([_item("3")], False, "200")
        client = FakeListClient(pages=[page1, page2])
        videos = list_user_videos("dave.xp", client)
        self.assertEqual([v.video_id for v in videos], ["1", "2", "3"])
        self.assertEqual(len(client.calls), 3)  # profile + 2 pages

    def test_max_limit_stops_pagination(self):
        page1 = ([_item("1"), _item("2"), _item("3")], True, "100")
        page2 = ([_item("4")], False, "200")
        client = FakeListClient(pages=[page1, page2])
        videos = list_user_videos("dave.xp", client, max_count=2)
        self.assertEqual([v.video_id for v in videos], ["1", "2"])
        self.assertEqual(len(client.calls), 2)  # only 1 page fetched
