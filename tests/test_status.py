import unittest

from tiktok_link.extractor import extract_status


class TestExtractStatus(unittest.TestCase):
    def test_returns_code_and_msg_from_universal_data(self):
        html = (
            '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
            '{"__DEFAULT_SCOPE__": {"webapp.video-detail": '
            '{"statusCode": 10204, "statusMsg": "person_geo_fencing"}}}'
            "</script></html>"
        )
        self.assertEqual(extract_status(html), (10204, "person_geo_fencing"))

    def test_returns_none_when_script_missing(self):
        self.assertEqual(extract_status("<html></html>"), (None, None))

    def test_returns_none_when_no_detail(self):
        html = (
            '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">{"a": 1}</script></html>'
        )
        self.assertEqual(extract_status(html), (None, None))

    def test_msg_none_when_detail_has_no_msg(self):
        html = (
            '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
            '{"__DEFAULT_SCOPE__": {"webapp.video-detail": {"statusCode": 0}}}'
            "</script></html>"
        )
        self.assertEqual(extract_status(html), (0, None))
