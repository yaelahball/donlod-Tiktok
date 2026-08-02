import os
import tempfile
import unittest

from tiktok_link.models import (
    DownloadEntry,
    default_state_path,
    load_state,
    save_state,
)


class TestDownloadEntry(unittest.TestCase):
    def test_from_dict_handles_missing_keys(self):
        entry = DownloadEntry.from_dict({"index": 1, "video_id": "123"})
        self.assertEqual(entry.index, 1)
        self.assertEqual(entry.video_id, "123")
        self.assertEqual(entry.status, "pending")
        self.assertIsNone(entry.error)

    def test_to_dict_roundtrip(self):
        entry = DownloadEntry.from_dict(
            DownloadEntry(
                index=2, video_id="456", caption="halo", status="success",
                size=100, filename="user_456.mp4",
            ).to_dict()
        )
        self.assertEqual(entry.index, 2)
        self.assertEqual(entry.status, "success")
        self.assertEqual(entry.size, 100)


class TestStateFile(unittest.TestCase):
    def test_default_path_per_username(self):
        self.assertEqual(default_state_path("shifaalmiraa"), "shifaalmiraa_downloads.json")

    def test_save_and_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            entries = [
                DownloadEntry(index=1, video_id="1", caption="a", status="success", size=100),
                DownloadEntry(index=2, video_id="2", caption="b", status="pending"),
            ]
            save_state(path, "shifaalmiraa", entries, concurrency=3)

            state = load_state(path)
            self.assertEqual(state["username"], "shifaalmiraa")
            self.assertEqual(state["concurrency"], 3)
            self.assertEqual(len(state["videos"]), 2)
            self.assertEqual(state["videos"][0]["status"], "success")
            self.assertEqual(state["videos"][0]["size"], 100)
            self.assertEqual(state["videos"][1]["caption"], "b")

    def test_load_missing_returns_none(self):
        self.assertIsNone(load_state(os.path.join(tempfile.gettempdir(), "does-not-exist.json")))

    def test_save_is_atomic(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "state.json")
            save_state(path, "u", [DownloadEntry(index=1, video_id="1")], concurrency=1)
            self.assertTrue(os.path.exists(path))
            self.assertFalse(any(f.endswith(".tmp") for f in os.listdir(tmp)))
