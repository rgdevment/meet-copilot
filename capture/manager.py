import logging
import queue
import re
import string
import threading
import time
from difflib import SequenceMatcher

from config import CAPTURE_DEFAULTS, EXCLUDED_SPEAKERS

from .base import CaptureSource

logger = logging.getLogger(__name__)


class CaptureManager:
    """
    Platform-agnostic capture manager that uses a CaptureSource to read
    captions and handles buffering, deduplication, block commitment.
    """

    def __init__(self, source: CaptureSource, glossary_processor=None):
        self.source = source
        self.glossary = glossary_processor

        self.start_time = time.time()
        self.last_activity_time = time.time()

        self.committed_lines: list[str] = []
        self.active_line = ""
        self.active_speaker = ""

        self.previous_context = ""
        self.window_name = ""
        self.last_raw_capture = ""

        self.word_threshold = CAPTURE_DEFAULTS["word_threshold"]
        self.silence_timeout = CAPTURE_DEFAULTS["silence_timeout"]
        self.min_words_for_timeout = CAPTURE_DEFAULTS["min_words_for_timeout"]
        self.context_overlap = CAPTURE_DEFAULTS["context_overlap"]

    def _normalize_text(self, text: str) -> str:
        if not text:
            return ""
        translator = str.maketrans("", "", string.punctuation)
        return " ".join(text.translate(translator).lower().split())

    def _count_words(self) -> int:
        full_text = " ".join(self.committed_lines) + " " + self.active_line
        return len(full_text.split())

    def update(self) -> bool:
        speaker, raw_text = self.source.get_caption()

        if not raw_text or speaker in EXCLUDED_SPEAKERS:
            return False
        clean_text = re.sub(r"\s+", " ", raw_text).strip()
        if not re.search(r"[a-zA-Z0-9]", clean_text):
            return False

        frame_sig = f"{speaker}|{clean_text}"
        if frame_sig == self.last_raw_capture:
            return False
        self.last_raw_capture = frame_sig
        self.last_activity_time = time.time()

        if hasattr(self.source, "window_name"):
            self.window_name = self.source.window_name

        if speaker != self.active_speaker:
            if self.active_line:
                self.committed_lines.append(
                    f"[{self.active_speaker}]: {self.active_line}"
                )
            self.active_speaker = speaker or ""
            self.active_line = clean_text
            return True

        norm_active = self._normalize_text(self.active_line)
        norm_new = self._normalize_text(clean_text)

        if norm_active in norm_new:
            self.active_line = clean_text
            return True

        if len(norm_new) > 0 and len(norm_active) > 0:
            similarity = SequenceMatcher(None, norm_active, norm_new).ratio()
            if similarity > 0.65:
                self.active_line = clean_text
                return True

        if self.active_line:
            self.committed_lines.append(
                f"[{self.active_speaker}]: {self.active_line}"
            )
        self.active_line = clean_text
        return True

    def check_snapshot(self, force_flush=False) -> dict | None:
        count = self._count_words()
        elapsed = time.time() - self.last_activity_time

        is_volume = count >= self.word_threshold
        is_silence = (elapsed > self.silence_timeout) and (
            count >= self.min_words_for_timeout
        )

        if is_volume or is_silence or (force_flush and count > 0):
            if self.active_line:
                self.committed_lines.append(
                    f"[{self.active_speaker}]: {self.active_line}"
                )
                self.active_line = ""
                self.active_speaker = ""
            return self._commit_block(count)
        return None

    def _commit_block(self, count: int) -> dict:
        timestamp = time.strftime("%H:%M")
        raw_forensic = "\n".join(self.committed_lines)

        live_clean = raw_forensic
        hints_block = ""
        if self.glossary:
            live_clean = self.glossary.apply_live_corrections(raw_forensic)
            hints = self.glossary.generate_ai_suggestions(raw_forensic)
            if hints:
                hints_block = (
                    "\n--- SUGERENCIAS DEL SENSOR (GLOSARIO) ---\n"
                    + "\n".join(hints)
                )

        words = raw_forensic.split()
        tail = (
            words[-self.context_overlap :]
            if len(words) > self.context_overlap
            else words
        )
        prev_ctx = self.previous_context
        self.previous_context = " ".join(tail)
        self.committed_lines = []
        self.start_time = time.time()

        return {
            "ts": timestamp,
            "raw_forensic": raw_forensic,
            "live_clean": live_clean,
            "hints": hints_block,
            "previous_context": prev_ctx,
            "meta_header": f"--- BLOQUE {timestamp} (Words: {count}) ---",
        }

    def flush(self) -> dict | None:
        return self.check_snapshot(force_flush=True)

    def get_live_view(self) -> str:
        current_view = list(self.committed_lines[-8:])
        if self.active_line:
            current_view.append(f"[{self.active_speaker}]: {self.active_line}")

        raw_buffer = "\n".join(current_view)
        if self.glossary:
            return self.glossary.apply_live_corrections(raw_buffer)
        return raw_buffer


def create_capture_source(platform: str) -> CaptureSource:
    import sys

    is_win = sys.platform == "win32"
    is_mac = sys.platform == "darwin"

    if platform == "auto":
        return _auto_detect_source(is_win, is_mac)

    if platform == "teams":
        if is_win:
            from .teams_windows import TeamsWindowsCapture
            return TeamsWindowsCapture()
        if is_mac:
            from .teams_mac import TeamsCaptureMac
            return TeamsCaptureMac()

    if platform == "zoom":
        if is_win:
            from .zoom_windows import ZoomWindowsCapture
            return ZoomWindowsCapture()
        if is_mac:
            raise NotImplementedError("Zoom Mac capture not yet implemented")

    raise ValueError(f"Unsupported platform/OS: {platform}/{sys.platform}")


def _auto_detect_source(is_win: bool, is_mac: bool) -> CaptureSource:
    """Try each platform capturer and return the first one that finds a meeting."""
    candidates = []

    if is_win:
        from .teams_windows import TeamsWindowsCapture
        from .zoom_windows import ZoomWindowsCapture
        candidates = [ZoomWindowsCapture(), TeamsWindowsCapture()]
    elif is_mac:
        from .teams_mac import TeamsCaptureMac
        candidates = [TeamsCaptureMac()]

    import uiautomation as auto
    init = auto.UIAutomationInitializerInThread()
    init.__enter__()
    try:
        for source in candidates:
            source._thread_init = init
            if source.is_available():
                source._thread_init = None
                logger.info(f"Auto-detected: {source.__class__.__name__}")
                return source
            source._thread_init = None
    finally:
        init.__exit__(None, None, None)

    # No meeting found yet — return first candidate; it will retry in the capture loop
    if candidates:
        logger.info("No active meeting found, defaulting to first candidate")
        return candidates[0]
    raise ValueError("No capture sources available for this OS")


def start_capture(
    source: CaptureSource,
    glossary_processor,
    on_block_callback,
    on_live_callback,
    stop_event: threading.Event,
    on_meeting_name_callback=None,
):
    block_queue = queue.Queue()

    def dispatch_worker():
        while not stop_event.is_set() or not block_queue.empty():
            try:
                payload = block_queue.get(timeout=1)
                on_block_callback(payload)
                block_queue.task_done()
            except queue.Empty:
                continue

    dispatch_thread = threading.Thread(target=dispatch_worker, daemon=True)
    dispatch_thread.start()

    source.initialize()
    manager = CaptureManager(source, glossary_processor)

    if on_meeting_name_callback:
        try:
            name = source.get_meeting_name()
            if name:
                on_meeting_name_callback(name)
        except Exception:
            pass

    try:
        while not stop_event.is_set():
            if manager.update():
                if on_live_callback:
                    on_live_callback(manager.get_live_view())

            payload = manager.check_snapshot()
            if payload:
                block_queue.put(payload)
            time.sleep(0.1)
    finally:
        final = manager.flush()
        if final:
            block_queue.put(final)
        source.cleanup()
        dispatch_thread.join(timeout=2)
