import json
import os
import queue
import re
import threading
import time
from collections import deque
from difflib import SequenceMatcher

import uiautomation as auto

# === CONFIGURATION ===
WORD_THRESHOLD = 350
SILENCE_TIMEOUT = 20
MIN_WORDS_FOR_TIMEOUT = 50
CONTEXT_OVERLAP = 150

# Speakers to ignore to maintain log fidelity
EXCLUDED_SPEAKERS = ["Usuario desconocido", "Unknown User"]

class TeamsRecorderSmart:
    def __init__(self):
        self.start_time = time.time()
        self.last_activity_time = time.time()
        self.buffer_lines = []
        self.previous_context = ""
        self.snapshots = deque(maxlen=50)
        self.window_name = "Buscando Teams..."
        self.last_raw = ""
        self.glossary_data = self._load_glossary()
        self.compiled_glossary = self._compile_glossary()

    def _load_glossary(self):
        path = os.path.join(os.path.dirname(__file__), "technical_glossary.json")
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        return {}

    def _compile_glossary(self):
        compiled = []
        for wrong, right in self.glossary_data.items():
            pattern = re.compile(rf"\b{re.escape(wrong)}\b", re.IGNORECASE)
            compiled.append((pattern, right))
        return compiled

    def _apply_fixes(self, text):
        for pattern, right in self.compiled_glossary:
            text = pattern.sub(right, text)
        return text

    def _get_caption(self):
        try:
            roots = auto.WindowControl(
                searchDepth=1, ClassName="TeamsWebView"
            ).GetChildren()
            sorted_wins = sorted(
                roots,
                key=lambda w: 0 if "Meeting" in w.Name or "Reunión" in w.Name else 1,
            )

            for win in sorted_wins:
                if "Chat" in win.Name:
                    continue
                try:
                    if not win.Exists(0, 0):
                        continue
                    web_area = win.DocumentControl(
                        searchDepth=15, AutomationId="RootWebArea"
                    )
                    if not web_area.Exists(0, 0):
                        web_area = win
                except:
                    continue

                candidates = []
                for control, depth in auto.WalkControl(web_area, maxDepth=14):
                    try:
                        if control.ControlTypeName == "GroupControl":
                            children = control.GetChildren()
                            if len(children) >= 2:
                                node_name = children[0]
                                node_text = children[1]
                                if (
                                    node_name.ControlTypeName == "TextControl"
                                    and node_text.ControlTypeName == "TextControl"
                                ):
                                    txt = node_text.Name
                                    if txt and len(txt) > 1 and "Micrófono" not in txt:
                                        candidates.append((node_name.Name, txt))
                    except Exception:
                        continue
                if candidates:
                    self.window_name = win.Name
                    return candidates[-1]
        except Exception:
            return None, None
        return None, None

    def _is_similar(self, a, b):
        return SequenceMatcher(None, a, b).ratio() > 0.85

    def _count_words(self):
        full_text = " ".join(self.buffer_lines)
        return len(full_text.split())

    def update(self):
        speaker, raw_text = self._get_caption()
        if not raw_text or speaker in EXCLUDED_SPEAKERS:
            return False

        clean_text = re.sub(r"\s+", " ", raw_text).strip()

        # Ignore very short OCR fragments to wait for stabilization
        if len(clean_text) < 4:
            return False

        full_line = f"[{speaker}]: {clean_text}"

        if full_line == self.last_raw:
            return False

        self.last_raw = full_line
        self.last_activity_time = time.time()

        # Look-back deduplication to handle interleaved speakers
        lookback_limit = min(5, len(self.buffer_lines))
        for i in range(len(self.buffer_lines) - 1, len(self.buffer_lines) - 1 - lookback_limit, -1):
            last_saved = self.buffer_lines[i]
            if f"[{speaker}]" in last_saved:
                last_content = last_saved.split("]: ", 1)[1] if "]: " in last_saved else ""

                # Case A: New text is already part of what we saved (Ignore)
                if clean_text in last_content:
                    return False

                # Case B: Saved text is part of the new reconstruction (Replace)
                if last_content in clean_text or self._is_similar(last_content, clean_text):
                    self.buffer_lines.pop(i)
                    self.buffer_lines.append(full_line)
                    return True
                break

        self.buffer_lines.append(full_line)
        return True

    def check_snapshot(self, force_flush=False):
        current_word_count = self._count_words()
        time_since_activity = time.time() - self.last_activity_time

        is_volume = current_word_count >= WORD_THRESHOLD
        is_silence = (time_since_activity > SILENCE_TIMEOUT) and (
            current_word_count >= MIN_WORDS_FOR_TIMEOUT
        )

        if is_volume or is_silence or (force_flush and current_word_count > 0):
            return self._commit_block(current_word_count)

        return None

    def _commit_block(self, count):
        timestamp = time.strftime("%H:%M")
        raw_content = "\n".join(self.buffer_lines)

        words = raw_content.split()
        tail_words = words[-CONTEXT_OVERLAP:] if len(words) > CONTEXT_OVERLAP else words
        new_overlap = " ".join(tail_words)

        final_payload = f"=== REUNIÓN: {self.window_name} ===\n"
        if self.previous_context:
            final_payload += f"--- CONTEXTO PREVIO ---\n...{self.previous_context}\n"

        final_payload += f"--- SEGMENTO ACTUAL ({count} palabras) ---\n{raw_content}"

        header = f"--- BLOQUE {timestamp} (Words: {count}) ---"
        self.snapshots.append(f"{header}\n{final_payload}")

        self.previous_context = new_overlap
        self.buffer_lines = []
        self.start_time = time.time()

        return self._apply_fixes(final_payload)

    def flush(self):
        return self.check_snapshot(force_flush=True)

def get_meeting_name():
    try:
        with auto.UIAutomationInitializerInThread():
            roots = auto.WindowControl(
                searchDepth=1, ClassName="TeamsWebView"
            ).GetChildren()
            sorted_wins = sorted(
                roots,
                key=lambda w: 0 if "Meeting" in w.Name or "Reunión" in w.Name else 1,
            )
            for win in sorted_wins:
                if "Chat" in win.Name:
                    continue
                if win.Exists(0, 0):
                    return win.Name
    except Exception:
        pass
    return None

def start_headless_capture(
    on_block_complete_callback, on_live_update_callback, stop_event
):
    block_queue = queue.Queue()

    def worker():
        while not stop_event.is_set() or not block_queue.empty():
            try:
                payload = block_queue.get(timeout=1)
                on_block_complete_callback(payload)
                block_queue.task_done()
            except queue.Empty:
                continue

    dispatch_thread = threading.Thread(target=worker, daemon=True)
    dispatch_thread.start()

    with auto.UIAutomationInitializerInThread():
        recorder = TeamsRecorderSmart()

        try:
            while not stop_event.is_set():
                if recorder.update():
                    if on_live_update_callback:
                        current_buffer = "\n".join(recorder.buffer_lines[-8:])
                        on_live_update_callback(recorder._apply_fixes(current_buffer))

                payload = recorder.check_snapshot()
                if payload:
                    block_queue.put(payload)

                time.sleep(0.1)
        finally:
            final_payload = recorder.flush()
            if final_payload:
                block_queue.put(final_payload)
            dispatch_thread.join(timeout=2)
