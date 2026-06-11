import logging
import queue
import re
import string
import threading
import time
from collections import deque
from difflib import SequenceMatcher

from config import CAPTURE_DEFAULTS, EXCLUDED_SPEAKERS

from .base import CaptureSource

logger = logging.getLogger(__name__)

_PUNCT_TABLE = str.maketrans("", "", string.punctuation)


class CaptureManager:
    """
    Platform-agnostic capture manager. Reads captions from a CaptureSource and
    reconciles the volatile caption stream (lines that grow and get rewritten
    in place) into a stable transcript.

    Reconciliation keeps one in-flight line per speaker; an incoming frame for a
    speaker is merged into their line when it is a prefix/high-similarity
    continuation (keeping the longer text so words are never dropped), and only
    starts a new line when it clearly diverges. A line is committed once it has
    been stable for `line_debounce_sec`, so block boundaries never cut an open
    line.
    """

    def __init__(
        self,
        source: CaptureSource,
        glossary_processor=None,
        recorder=None,
        read_all_nodes: bool = True,
    ):
        self.source = source
        self.glossary = glossary_processor
        self.recorder = recorder
        self.read_all_nodes = read_all_nodes

        self.start_time = time.time()
        self.last_activity_time = time.time()
        self.last_caption_time = time.time()

        self.committed_lines: list[str] = []
        # speaker -> {"text": str, "ts": last-change time}
        self.tracks: dict[str, dict] = {}
        # Recently committed (speaker, normalized-text) signatures. Reading all
        # visible nodes re-emits already-scrolled history lines every poll; this
        # guards against re-committing them.
        self.recent_committed: deque = deque(maxlen=80)

        self.previous_context = ""
        self.window_name = ""

        self.word_threshold = CAPTURE_DEFAULTS["word_threshold"]
        self.silence_timeout = CAPTURE_DEFAULTS["silence_timeout"]
        self.min_words_for_timeout = CAPTURE_DEFAULTS["min_words_for_timeout"]
        self.context_overlap = CAPTURE_DEFAULTS["context_overlap"]
        self.debounce = CAPTURE_DEFAULTS["line_debounce_sec"]
        self.merge_similarity = CAPTURE_DEFAULTS["merge_similarity"]

        # Health counters (Fase 0)
        self.reads = 0
        self.discarded = 0

    def _normalize_text(self, text: str) -> str:
        if not text:
            return ""
        return " ".join(text.translate(_PUNCT_TABLE).lower().split())

    @staticmethod
    def _common_prefix_len(a: str, b: str) -> int:
        n = 0
        for ca, cb in zip(a, b):
            if ca != cb:
                break
            n += 1
        return n

    def _count_words(self) -> int:
        # Block size counts only completed lines. The volatile caption node holds
        # the whole growing line, so committing a still-open line would duplicate
        # it next poll; a non-stop monologue therefore stays one in-flight line
        # until the speaker pauses (debounce) and commits once. No data is lost.
        return len(" ".join(self.committed_lines).split())

    def _record(self, speaker, text, decision):
        if self.recorder:
            self.recorder.log(speaker, text, decision)

    def update(self) -> bool:
        if self.read_all_nodes:
            observations = self.source.get_captions()
        else:
            speaker, text = self.source.get_caption()
            observations = [(speaker, text)] if text else []

        if hasattr(self.source, "window_name"):
            self.window_name = self.source.window_name

        changed = False
        now = time.time()
        for speaker, raw_text in observations:
            self.reads += 1
            if not raw_text or speaker in EXCLUDED_SPEAKERS:
                self.discarded += 1
                self._record(speaker, raw_text, "excluded_speaker")
                continue
            clean_text = re.sub(r"\s+", " ", raw_text).strip()
            if not re.search(r"[a-zA-Z0-9]", clean_text):
                self.discarded += 1
                self._record(speaker, clean_text, "no_alnum")
                continue
            self.last_caption_time = now
            if self._ingest(speaker or "", clean_text, now):
                changed = True

        if self._commit_stale(now):
            changed = True
        return changed

    def _ingest(self, speaker: str, text: str, now: float) -> bool:
        track = self.tracks.get(speaker)
        if track is None:
            self.tracks[speaker] = {"text": text, "ts": now}
            self.last_activity_time = now
            self._record(speaker, text, "new_open")
            return True

        prev = track["text"]
        if text == prev:
            self._record(speaker, text, "dup_exact")
            return False

        np_, nt = self._normalize_text(prev), self._normalize_text(text)

        if np_ == nt:
            # Same content, different casing/punctuation — keep the longer form.
            if len(text) > len(prev):
                track["text"] = text
                self._record(speaker, text, "dup_norm_longer")
                return True
            self._record(speaker, text, "dup_norm")
            return False

        if np_ and (nt.startswith(np_) or np_ in nt):
            track["text"] = text
            track["ts"] = now
            self.last_activity_time = now
            self._record(speaker, text, "grow")
            return True

        # Same line being rewritten as it grows (e.g. "bakloc" → "backlog
        # grooming"): a long shared prefix is a more robust signal than a global
        # ratio, which a simultaneous correction+growth drags below threshold.
        shorter = min(len(np_), len(nt))
        prefix_ratio = self._common_prefix_len(np_, nt) / shorter if shorter else 0.0
        ratio = SequenceMatcher(None, np_, nt).ratio() if np_ and nt else 0.0
        if prefix_ratio >= 0.5 or ratio >= self.merge_similarity:
            # Keep the newest emission — it carries the correction even if shorter.
            track["text"] = text
            track["ts"] = now
            self.last_activity_time = now
            self._record(speaker, text, f"merge_p{prefix_ratio:.2f}_r{ratio:.2f}")
            return True

        # Divergent: the previous line is done, this is a new one.
        self._commit_line(speaker, prev)
        self.tracks[speaker] = {"text": text, "ts": now}
        self.last_activity_time = now
        self._record(speaker, text, "newline")
        return True

    def _commit_line(self, speaker: str, text: str):
        if not text:
            return
        sig = (speaker, self._normalize_text(text))
        if sig in self.recent_committed:
            self._record(speaker, text, "dup_committed_skip")
            return
        self.recent_committed.append(sig)
        self.committed_lines.append(f"[{speaker}]: {text}")
        self._record(speaker, text, "committed")

    def _commit_stale(self, now: float) -> bool:
        stale = [
            (sp, tr)
            for sp, tr in self.tracks.items()
            if now - tr["ts"] >= self.debounce
        ]
        if not stale:
            return False
        for speaker, track in sorted(stale, key=lambda kv: kv[1]["ts"]):
            self._commit_line(speaker, track["text"])
            del self.tracks[speaker]
        return True

    def _commit_all_tracks(self):
        for speaker, track in sorted(self.tracks.items(), key=lambda kv: kv[1]["ts"]):
            self._commit_line(speaker, track["text"])
        self.tracks = {}

    def check_snapshot(self, force_flush=False) -> dict | None:
        if force_flush:
            self._commit_all_tracks()

        count = self._count_words()
        elapsed = time.time() - self.last_activity_time

        is_volume = count >= self.word_threshold
        is_silence = (elapsed > self.silence_timeout) and (
            count >= self.min_words_for_timeout
        )

        if is_volume or is_silence or (force_flush and count > 0):
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
        for speaker, track in sorted(self.tracks.items(), key=lambda kv: kv[1]["ts"]):
            current_view.append(f"[{speaker}]: {track['text']}")

        raw_buffer = "\n".join(current_view)
        if self.glossary:
            return self.glossary.apply_live_corrections(raw_buffer)
        return raw_buffer

    def seconds_since_caption(self) -> float:
        return time.time() - self.last_caption_time


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
    diag_dir: str | None = None,
    read_all_nodes: bool = True,
    on_status_callback=None,
):
    from .recorder import RawRecorder

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
    recorder = RawRecorder(diag_dir) if diag_dir else None
    manager = CaptureManager(
        source, glossary_processor, recorder=recorder, read_all_nodes=read_all_nodes
    )

    if on_meeting_name_callback:
        try:
            name = source.get_meeting_name()
            if name:
                on_meeting_name_callback(name)
        except Exception:
            logger.debug("get_meeting_name failed", exc_info=True)

    warn_after = CAPTURE_DEFAULTS["no_caption_warn_sec"]
    warned = False
    try:
        while not stop_event.is_set():
            if manager.update():
                warned = False
                if on_live_callback:
                    on_live_callback(manager.get_live_view())
            elif on_status_callback and not warned:
                # Window present but no captions for a while → likely structure
                # change or captions off, not just silence.
                if manager.seconds_since_caption() > warn_after:
                    try:
                        if source.is_available():
                            on_status_callback(
                                "Ventana encontrada pero sin subtítulos. "
                                "¿Subtítulos activados? Usa 🩺 para diagnosticar."
                            )
                            warned = True
                    except Exception:
                        logger.debug("availability check failed", exc_info=True)

            payload = manager.check_snapshot()
            if payload:
                block_queue.put(payload)
            time.sleep(0.1)
    finally:
        final = manager.flush()
        if final:
            block_queue.put(final)
        if recorder:
            recorder.close()
        source.cleanup()
        dispatch_thread.join(timeout=2)
