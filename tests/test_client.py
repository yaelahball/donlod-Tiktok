import unittest

from tiktok_link.client import parse_cookie_string, generate_verify_fp


class TestParseCookieString(unittest.TestCase):
    def test_parses_semicolon_list(self):
        cookies = parse_cookie_string("ms_token=abc123; tt_webid=xyz; sid_tt=def")
        self.assertEqual(cookies, {"ms_token": "abc123", "tt_webid": "xyz", "sid_tt": "def"})

    def test_ignores_empty_segments_and_spaces(self):
        cookies = parse_cookie_string("  ms_token = abc ; ; tt_webid=xyz  ")
        self.assertEqual(cookies, {"ms_token": "abc", "tt_webid": "xyz"})

    def test_empty_returns_empty_dict(self):
        self.assertEqual(parse_cookie_string(""), {})
        self.assertEqual(parse_cookie_string(None), {})


class TestGenerateVerifyFp(unittest.TestCase):
    def test_matches_verify_prefix(self):
        self.assertTrue(generate_verify_fp().startswith("verify_"))

    def test_has_random_suffix(self):
        self.assertNotEqual(generate_verify_fp(), generate_verify_fp())
