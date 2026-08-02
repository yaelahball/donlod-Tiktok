import io
import os
import tempfile
import unittest

from tiktok_link.cli import build_entries, prepare_download_batch, process_download_batch
from tiktok_link.models import DownloadEntry, load_state
from tiktok_link.ui import BatchReporter
from tests.test_download import FakeSession
from tests.test_extractor import API_PAYLOAD

HTML_WITH_DATA = (
    '<html><script id="__UNIVERSAL_DATA_FOR_REHYDRATION__">'
    + __import__("json").dumps(API_PAYLOAD)
    + "</script></html>"
)


class FakeBatchClient:
    def __init__(self, page=HTML_WITH_DATA, fail_resolve=False):
        self.page = page
        self.fail_resolve = fail_resolve
        self.session = FakeSession()

    def fetch_item_detail(self, video_id):
        return {}

    def fetch_video_page(self, url):
        if self.fail_resolve:
            raise RuntimeError("blocked")
        return self.page

    def resolve_short_link(self, url):
        return url


def _video(video_id):
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


class TestBuildEntries(unittest.TestCase):
    def test_builds_pending_entries(self):
        from tiktok_link.extractor import extract_videos_from_list

        videos = extract_videos_from_list({"itemList": [_video("1"), _video("2")]})
        entries = build_entries("dave.xp", videos)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].status, "pending")
        self.assertEqual(entries[0].filename, "1_1_dave.xp.mp4")
        self.assertEqual(entries[1].filename, "2_2_dave.xp.mp4")
        self.assertEqual(entries[0].caption, "caption 1")
        self.assertTrue(entries[0].mp4_url.startswith("https://"))


class TestPrepareDownloadBatch(unittest.TestCase):
    def test_existing_files_marked_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v1.mp4")
            with open(path, "wb") as handle:
                handle.write(b"\x00\x00\x00\x18ftypisom" + b"x" * 2000)
            entries = [
                DownloadEntry(index=1, video_id="1", filename="v1.mp4", status="pending"),
                DownloadEntry(index=2, video_id="2", filename="v2.mp4", status="pending"),
            ]
            old = os.getcwd()
            os.chdir(tmp)
            try:
                to_process, skipped = prepare_download_batch(entries)
            finally:
                os.chdir(old)
            self.assertEqual(entries[0].status, "success")
            self.assertEqual(skipped, 1)
            self.assertEqual(len(to_process), 1)
            self.assertEqual(to_process[0].video_id, "2")

    def test_partial_file_not_marked_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "v1.mp4")
            with open(path, "wb") as handle:
                handle.write(b"\x00\x00\x00\x18ftypisom" + b"x" * 3000)
            entries = [
                DownloadEntry(
                    index=1, video_id="1", filename="v1.mp4",
                    status="pending", expected_size=100000,
                )
            ]
            old = os.getcwd()
            os.chdir(tmp)
            try:
                to_process, skipped = prepare_download_batch(entries)
            finally:
                os.chdir(old)
            self.assertEqual(skipped, 0)
            self.assertEqual(len(to_process), 1)
            self.assertEqual(entries[0].status, "pending")


    def test_success_entry_with_missing_file_is_redownloaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            entries = [
                DownloadEntry(index=1, video_id="1", filename="gone.mp4",
                              status="success", size=100, expected_size=100),
            ]
            old = os.getcwd()
            os.chdir(tmp)
            try:
                to_process, skipped = prepare_download_batch(entries)
            finally:
                os.chdir(old)
            self.assertEqual(skipped, 0)
            self.assertEqual(len(to_process), 1)
            self.assertEqual(entries[0].status, "pending")


class TestProcessDownloadBatch(unittest.TestCase):
    def test_all_success(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            os.chdir(tmp)
            try:
                entries = [
                    DownloadEntry(index=1, video_id="1", filename="dave.xp_1.mp4",
                                  page_url="https://www.tiktok.com/@dave.xp/video/7234567890123456789",
                                  caption="caption 1", status="pending"),
                    DownloadEntry(index=2, video_id="2", filename="dave.xp_2.mp4",
                                  page_url="https://www.tiktok.com/@dave.xp/video/7234567890123456789",
                                  status="pending"),
                ]
                state_path = "state.json"
                reporter = BatchReporter(stream=io.StringIO(), use_color=False)
                result = process_download_batch(entries, FakeBatchClient(), concurrency=1,
                                                quality="h264", reporter=reporter,
                                                state_path=state_path, username="dave.xp")
                self.assertEqual(result["success"], 2)
                self.assertEqual(result["failed"], 0)
                self.assertTrue(os.path.exists("dave.xp_1.mp4"))
                state = load_state(state_path)
                self.assertEqual(state["videos"][0]["status"], "success")
            finally:
                os.chdir(old)

    def test_resolve_failure_marks_all_failed(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = os.getcwd()
            os.chdir(tmp)
            try:
                entries = [
                    DownloadEntry(index=i, video_id=str(i), filename="v%d.mp4" % i,
                                  page_url="https://www.tiktok.com/@dave.xp/video/123", status="pending")
                    for i in range(1, 4)
                ]
                reporter = BatchReporter(stream=io.StringIO(), use_color=False)
                result = process_download_batch(entries, FakeBatchClient(fail_resolve=True),
                                                concurrency=1, quality="h264", reporter=reporter,
                                                state_path="state.json", username="dave.xp")
                self.assertEqual(result["success"], 0)
                self.assertEqual(result["failed"], 3)
                self.assertTrue(all(e.status == "failed" for e in entries))
            finally:
                os.chdir(old)
