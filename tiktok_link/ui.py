"""Rich CLI output: ANSI colors, progress bars, and batch reports."""

import os
import sys
import threading

RESET = "\033[0m"
COLORS = {
    "cyan": "\033[36m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "red": "\033[31m",
    "dim": "\033[2m",
    "bold": "\033[1m",
}


def _enable_ansi_on_windows():
    if os.name == "nt":
        os.system("")


def format_bytes(value):
    value = max(0, int(value or 0))
    if value < 1024:
        return "%d B" % value
    amount = float(value)
    for unit in ("KB", "MB", "GB", "TB"):
        amount /= 1024.0
        if amount < 1024:
            return "%.1f %s" % (amount, unit)
    return "%.1f %s" % (amount, "TB")


def format_elapsed(seconds):
    seconds = int(seconds)
    minutes, secs = divmod(seconds, 60)
    if minutes:
        return "%d:%02d" % (minutes, secs)
    return "%ds" % secs


class ProgressBar:
    FILL = "█"
    EMPTY = "░"

    @staticmethod
    def render(percent, width=24):
        percent = max(0, min(100, int(percent)))
        filled = int(round(percent / 100.0 * width))
        return "[%s%s]" % (ProgressBar.FILL * filled, ProgressBar.EMPTY * (width - filled))


class BatchReporter:
    """Thread-safe console reporter with a single active progress line."""

    def __init__(self, stream=None, use_color=None):
        self.stream = stream or sys.stdout
        self.lock = threading.Lock()
        if use_color is None:
            use_color = hasattr(self.stream, "isatty") and self.stream.isatty()
        self.use_color = use_color
        if use_color:
            _enable_ansi_on_windows()

    def _color(self, text, name):
        if not self.use_color:
            return text
        return COLORS.get(name, "") + text + RESET

    def _write(self, text):
        self.stream.write(text)
        self.stream.flush()

    def start(self, username, total, concurrency, state_path):
        with self.lock:
            self._write("\n")
            self._write(self._color("⠿ TikTok Link Getter — Batch Download", "bold") + "\n")
            self._write("   %s: @%s\n" % (self._color("Username", "dim"), username))
            self._write("   %s: %d video\n" % (self._color("Total", "dim"), total))
            self._write("   %s: %d\n" % (self._color("Concurrency", "dim"), concurrency))
            self._write("   %s: %s\n" % (self._color("State", "dim"), state_path))
            self._write("\n")

    def begin_video(self, index, total, filename):
        with self.lock:
            self._write(self._color("→ [%d/%d] %s\n" % (index, total, filename), "yellow"))

    def progress(self, received, total, speed):
        percent = int(received * 100.0 / total) if total else 0
        bar = ProgressBar.render(percent)
        text = "%s %3d%%  %s/%s  %s/s" % (
            bar, percent, format_bytes(received), format_bytes(total), format_bytes(speed),
        )
        with self.lock:
            if self.use_color:
                self._write("\r\033[2K" + self._color(text, "dim"))
            else:
                self._write("\r" + text)

    def success(self, index, total, filename, size=None):
        size_text = " (%s)" % format_bytes(size) if size else ""
        with self.lock:
            self._write("\r\033[2K")
            self._write(self._color("✓ [%d/%d] %s%s\n" % (index, total, filename, size_text), "green"))

    def fail(self, index, total, filename, reason):
        with self.lock:
            self._write("\r\033[2K")
            self._write(self._color("✗ [%d/%d] %s → %s\n" % (index, total, filename, reason), "red"))

    def overall(self, done, total, active):
        percent = int(done * 100.0 / total) if total else 0
        bar = ProgressBar.render(percent)
        text = "%s %d/%d selesai (%d%%) · aktif: %d" % (bar, done, total, percent, active)
        with self.lock:
            if self.use_color:
                self._write("\r\033[2K" + self._color(text, "cyan"))
            else:
                self._write("\r" + text)

    def finish(self, total, success, failed, skipped, total_size, elapsed, failures=None, state_path=None):
        with self.lock:
            self._write("\n")
            line = "=" * 46
            self._write(self._color(line, "dim") + "\n")
            self._write(self._color("  Report", "bold") + "\n")
            self._write(self._color(line, "dim") + "\n")
            self._write("  Total video     : %d\n" % total)
            self._write("  Sukses          : %d  %s\n" % (success, self._color("✓", "green")))
            self._write("  Gagal           : %d  %s\n" % (failed, self._color("✗", "red")))
            self._write("  Lewati (sudah)  : %d\n" % skipped)
            self._write("  Ukuran total    : %s\n" % format_bytes(total_size))
            self._write("  Waktu           : %s\n" % format_elapsed(elapsed))
            if failures:
                self._write("  %s\n" % self._color("── Daftar gagal ──", "yellow"))
                for filename, reason in failures:
                    self._write("   · %s → %s\n" % (filename, reason))
            if state_path:
                self._write("  %s\n" % self._color("State disimpan: %s (siap resume)" % state_path, "dim"))
            self._write(self._color(line, "dim") + "\n")
