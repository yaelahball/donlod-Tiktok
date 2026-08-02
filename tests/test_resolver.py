import unittest

from tiktok_link.resolver import (
    normalize_url,
    extract_video_id,
    extract_username,
    is_short_link,
)


class TestNormalizeUrl(unittest.TestCase):
    def test_full_url_with_query_and_fragment(self):
        url = "https://www.tiktok.com/@user/video/7234567890123456789?lang=en&is_copy_url=1#foo"
        result = normalize_url(url)
        self.assertEqual(
            result, "https://www.tiktok.com/@user/video/7234567890123456789"
        )

    def test_url_without_username(self):
        url = "https://www.tiktok.com/video/7234567890123456789"
        self.assertEqual(
            normalize_url(url), "https://www.tiktok.com/video/7234567890123456789"
        )

    def test_trailing_slash_removed(self):
        self.assertEqual(
            normalize_url("https://www.tiktok.com/@user/video/723/"),
            "https://www.tiktok.com/@user/video/723",
        )


class TestExtractVideoId(unittest.TestCase):
    def test_from_full_url(self):
        self.assertEqual(
            extract_video_id("https://www.tiktok.com/@user/video/7234567890123456789"),
            "7234567890123456789",
        )

    def test_from_url_without_username(self):
        self.assertEqual(
            extract_video_id("https://www.tiktok.com/video/7234567890123456789"),
            "7234567890123456789",
        )

    def test_from_short_link_returns_none(self):
        self.assertIsNone(extract_video_id("https://vm.tiktok.com/ZMabcXYZ/"))


class TestExtractUsername(unittest.TestCase):
    def test_username_from_full_url(self):
        self.assertEqual(
            extract_username("https://www.tiktok.com/@dave.xp/video/7234567890123456789"),
            "dave.xp",
        )

    def test_no_username_returns_none(self):
        self.assertIsNone(
            extract_username("https://www.tiktok.com/video/7234567890123456789")
        )


class TestIsShortLink(unittest.TestCase):
    def test_vm_tiktok(self):
        self.assertTrue(is_short_link("https://vm.tiktok.com/ZMabcXYZ/"))

    def test_tiktok_t_slash(self):
        self.assertTrue(is_short_link("https://www.tiktok.com/t/ZMabcXYZ"))

    def test_full_url_is_not_short(self):
        self.assertFalse(
            is_short_link("https://www.tiktok.com/@user/video/7234567890123456789")
        )
