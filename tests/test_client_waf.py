import base64
import hashlib
import json
import unittest

from tiktok_link.client import TikTokClient


def make_challenge_html(answer):
    base = b"basevalue-for-test"
    expected = hashlib.sha256(base + str(answer).encode()).digest()
    challenge = {
        "v": {
            "a": base64.b64encode(base).decode(),
            "c": base64.b64encode(expected).decode(),
        },
        "s": "sig",
    }
    cs = base64.b64encode(json.dumps(challenge, separators=(",", ":")).encode()).decode()
    return (
        "<html><body>"
        "<p id=\"wci\" class=\"_wafchallengeid\"></p>"
        "<p id=\"cs\" class=\"" + cs + "\"></p>"
        "</body></html>"
    )


class TestWafSolver(unittest.TestCase):
    def test_solves_and_sets_challenge_cookie(self):
        client = TikTokClient()
        html = make_challenge_html(4242)
        self.assertTrue(client.solve_waf_challenge(html))
        cookies = {c.name: c.value for c in client.session.cookies.jar}
        self.assertIn("_wafchallengeid", cookies)
        decoded = json.loads(base64.b64decode(cookies["_wafchallengeid"]))
        self.assertEqual(base64.b64decode(decoded["d"]), b"4242")

    def test_returns_false_without_challenge(self):
        client = TikTokClient()
        self.assertFalse(client.solve_waf_challenge("<html>normal page</html>"))
        self.assertFalse(client.solve_waf_challenge(""))

    def test_returns_false_when_elements_missing(self):
        client = TikTokClient()
        self.assertFalse(
            client.solve_waf_challenge('<p id="wci" class="x"></p>')
        )


if __name__ == "__main__":
    unittest.main()
