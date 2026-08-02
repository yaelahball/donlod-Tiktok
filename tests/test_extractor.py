import unittest

from tiktok_link.extractor import extract_from_api, extract_from_html
from tiktok_link.models import rank_best, rank_candidates

API_PAYLOAD = {
    "itemInfo": {
        "itemStruct": {
            "id": "7234567890123456789",
            "desc": "test caption #fyp",
            "createTime": 1700000000,
            "author": {"uniqueId": "dave.xp", "nickname": "Dave"},
            "video": {
                "duration": 15300,
                "cover": "https://p16-va.tiktokcdn.com/img.jpg",
                "bitrateInfo": [
                    {
                        "QualityType": 720,
                        "Bitrate": 2323456,
                        "CodecType": "h264",
                        "PlayAddr": {
                            "UrlList": [
                                "https://v19.tiktokcdn.com/video/tos/720.mp4?a=1",
                                "https://v16.tiktokcdn.com/video/tos/720.mp4?a=2",
                            ],
                            "Height": 1280,
                            "Width": 720,
                            "DataSize": 5000000,
                        },
                    },
                    {
                        "QualityType": 540,
                        "Bitrate": 1000000,
                        "CodecType": "h265",
                        "PlayAddr": {
                            "UrlList": ["https://v19.tiktokcdn.com/video/tos/540.mp4"],
                            "Height": 960,
                            "Width": 540,
                        },
                    },
                ],
                "playAddr": {"UrlList": ["https://v19.tiktokcdn.com/video/tos/play.mp4"]},
                "downloadAddr": {"UrlList": ["https://v19.tiktokcdn.com/video/tos/dl.mp4"]},
            },
        }
    }
}


class TestExtractFromApi(unittest.TestCase):
    def test_extracts_video_info(self):
        info = extract_from_api(API_PAYLOAD)
        self.assertIsNotNone(info)
        self.assertEqual(info.video_id, "7234567890123456789")
        self.assertEqual(info.creator_username, "dave.xp")
        self.assertEqual(info.caption, "test caption #fyp")

    def test_extracts_candidates_from_bitrate_info(self):
        info = extract_from_api(API_PAYLOAD)
        self.assertGreaterEqual(len(info.candidates), 3)

    def test_returns_none_for_empty_payload(self):
        self.assertIsNone(extract_from_api({}))
        self.assertIsNone(extract_from_api(None))

    def test_quality_prefers_gear_name_resolution(self):
        payload = {
            "itemInfo": {
                "itemStruct": {
                    "id": "1234567890",
                    "video": {
                        "bitrateInfo": [
                            {
                                "QualityType": 20,
                                "GearName": "normal_540_0",
                                "CodecType": "h264",
                                "PlayAddr": {"UrlList": ["https://v19.tiktokcdn.com/540.mp4"]},
                            },
                            {
                                "QualityType": 20,
                                "GearName": "normal_1080_0",
                                "CodecType": "h264",
                                "PlayAddr": {"UrlList": ["https://v19.tiktokcdn.com/1080.mp4"]},
                            },
                        ]
                    },
                }
            }
        }
        info = extract_from_api(payload)
        ranked = rank_candidates(info.candidates)
        self.assertEqual(ranked[0].url, "https://v19.tiktokcdn.com/1080.mp4")
        self.assertEqual(ranked[0].quality, 1080)


class TestExtractFromHtml(unittest.TestCase):
    def test_parses_universal_data_script(self):
        html = (
            '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
            + __import__("json").dumps(API_PAYLOAD)
            + "</script></html>"
        )
        info = extract_from_html(html)
        self.assertIsNotNone(info)
        self.assertEqual(info.video_id, "7234567890123456789")

    def test_returns_none_when_script_missing(self):
        self.assertIsNone(extract_from_html("<html><body>no data</body></html>"))


class TestRankCandidates(unittest.TestCase):
    def test_h264_higher_than_hevc(self):
        info = extract_from_api(API_PAYLOAD)
        ranked = rank_candidates(info.candidates)
        self.assertEqual(ranked[0].codec, "h264")

    def test_rank_returns_copy_sorted_by_quality(self):
        info = extract_from_api(API_PAYLOAD)
        ranked = rank_candidates(info.candidates)
        self.assertEqual(len(ranked), len(info.candidates))
        self.assertEqual(ranked[0].url, "https://v19.tiktokcdn.com/video/tos/720.mp4?a=1")

    def test_dash_and_blank_urls_removed(self):
        info = extract_from_api(API_PAYLOAD)
        info.candidates.append(__import__("tiktok_link.models", fromlist=["MediaCandidate"]).MediaCandidate(
            url="https://www.tiktok.com/api/dash", source="dash", quality=0, bitrate=0,
            width=0, height=0, codec=""
        ))
        info.candidates.append(__import__("tiktok_link.models", fromlist=["MediaCandidate"]).MediaCandidate(
            url="", source="x", quality=0, bitrate=0, width=0, height=0, codec=""
        ))
        ranked = rank_candidates(info.candidates)
        self.assertTrue(all(c.url for c in ranked))
        self.assertNotIn("dash", " ".join(c.url for c in ranked))


class TestRankBest(unittest.TestCase):
    def test_prefers_higher_resolution_even_if_hevc(self):
        from tiktok_link.models import MediaCandidate

        candidates = [
            MediaCandidate(url="https://x/540-h264.mp4", source="b", quality=540,
                           bitrate=538389, width=576, height=1024, codec="h264"),
            MediaCandidate(url="https://x/720-h265.mp4", source="b", quality=720,
                           bitrate=691228, width=720, height=1280, codec="h265_hvc1"),
        ]
        ranked = rank_best(candidates)
        self.assertEqual(ranked[0].url, "https://x/720-h265.mp4")

    def test_empty_returns_empty(self):
        self.assertEqual(rank_best([]), [])
