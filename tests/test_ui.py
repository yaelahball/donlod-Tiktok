import io
import unittest

from tiktok_link.ui import BatchReporter, ProgressBar, format_bytes


class TestFormatBytes(unittest.TestCase):
    def test_bytes(self):
        self.assertEqual(format_bytes(0), "0 B")
        self.assertEqual(format_bytes(512), "512 B")

    def test_kb(self):
        self.assertEqual(format_bytes(600796), "586.7 KB")

    def test_mb(self):
        self.assertEqual(format_bytes(48200000), "46.0 MB")


class TestProgressBar(unittest.TestCase):
    def test_render_percent(self):
        self.assertEqual(ProgressBar.render(50, 10), "[█████░░░░░]")

    def test_render_zero(self):
        self.assertEqual(ProgressBar.render(0, 4), "[░░░░]")

    def test_render_full(self):
        self.assertEqual(ProgressBar.render(100, 4), "[████]")

    def test_clamps_out_of_range(self):
        self.assertEqual(ProgressBar.render(150, 4), "[████]")
        self.assertEqual(ProgressBar.render(-5, 4), "[░░░░]")


class TestBatchReporter(unittest.TestCase):
    def _reporter(self):
        stream = io.StringIO()
        return BatchReporter(stream=stream, use_color=False), stream

    def test_start_prints_header(self):
        reporter, stream = self._reporter()
        reporter.start("shifaalmiraa", 47, 3, "shifaalmiraa_downloads.json")
        out = stream.getvalue()
        self.assertIn("shifaalmiraa", out)
        self.assertIn("47", out)
        self.assertIn("shifaalmiraa_downloads.json", out)

    def test_success_and_fail_lines(self):
        reporter, stream = self._reporter()
        reporter.success(1, 47, "a.mp4", 600796)
        reporter.fail(2, 47, "b.mp4", "cookie_expired")
        out = stream.getvalue()
        self.assertIn("✓", out)
        self.assertIn("586.7 KB", out)
        self.assertIn("✗", out)
        self.assertIn("cookie_expired", out)

    def test_finish_prints_report(self):
        reporter, stream = self._reporter()
        reporter.finish(total=2, success=1, failed=1, skipped=0, total_size=600796, elapsed=30)
        out = stream.getvalue()
        self.assertIn("Report", out)
        self.assertIn("1", out)
        self.assertIn("30s", out)

    def test_progress_uses_carriage_return(self):
        reporter, stream = self._reporter()
        reporter.progress(300000, 600796, 2000000)
        out = stream.getvalue()
        self.assertIn("\r", out)
        self.assertIn("%", out)
