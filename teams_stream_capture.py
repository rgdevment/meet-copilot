import json
import os
import queue
import re
import string
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
FUZZY_THRESHOLD = 0.80

EXCLUDED_SPEAKERS = ["Usuario desconocido", "Unknown User"]


class TeamsRecorderSmart:
    def __init__(self):
        self.start_time = time.time()
        self.last_activity_time = time.time()

        # Buffer Logic
        self.committed_lines = []  # Lines that are finished/stable
        self.active_line = ""  # Current line being spoken/modified by Teams
        self.active_speaker = ""

        self.previous_context = ""
        self.snapshots = deque(maxlen=50)
        self.window_name = "Buscando Teams..."
        self.last_raw_capture = ""  # To avoid processing identical frames

        # Load Dictionary
        self.glossary_data = self._load_glossary()
        self.glossary_keys = list(self.glossary_data.keys())
        self.compiled_rules = self._compile_glossary_rules()

    def _load_glossary(self):
        path = os.path.join(os.path.dirname(__file__), "technical_glossary.json")
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except:
                return {}
        return {}

    def _compile_glossary_rules(self):
        # Compile explicit regex aliases for fast replacement
        rules = []
        for correct_word, data in self.glossary_data.items():
            aliases = data.get("aliases", [])
            live_replace = data.get("live_replace", False)
            if not aliases:
                continue

            aliases.sort(key=len, reverse=True)
            pattern_str = r"(?i)\b(" + "|".join(map(re.escape, aliases)) + r")\b"
            rules.append((re.compile(pattern_str), correct_word, live_replace))
        return rules

    # === TEXT PROCESSING UTILS ===

    def _normalize_text(self, text):
        # Strip punctuation and lowercase for logical comparison
        if not text:
            return ""
        translator = str.maketrans("", "", string.punctuation)
        return " ".join(text.translate(translator).lower().split())

    def _fix_versions_dynamic(self, text):
        # Regex for b 1 -> v1
        return re.sub(r"(?i)\b[bB]\s?[\-]?\s?(\d+)\b", r"v\1", text)

    def _generate_live_clean_text(self, text):
        # Fast cleanup for UI/Human readability
        if not text:
            return ""
        clean = text
        clean = self._fix_versions_dynamic(clean)
        for pattern, correct, do_replace in self.compiled_rules:
            if do_replace:
                clean = pattern.sub(correct, clean)
        return clean

    def _fuzzy_scan_for_hints(self, text):
        # Deep scan for AI suggestions (heavy operation, run only on commit)
        matches = set()
        words = re.findall(r"\b[a-zA-Záéíóúñ]{4,}\b", text)

        for word in words:
            for key in self.glossary_keys:
                if word.lower() == key.lower():
                    continue
                # Fuzzy matching ratio
                if (
                    SequenceMatcher(None, word.lower(), key.lower()).ratio()
                    >= FUZZY_THRESHOLD
                ):
                    matches.add((word, key))
        return matches

    def _generate_ai_suggestions(self, text):
        if not text:
            return []
        suggestions = []
        seen_concepts = set()

        # 1. Version Detection
        version_matches = re.findall(r"(?i)\b[bB]\s?[\-]?\s?(\d+)\b", text)
        for num in set(version_matches):
            concept_id = f"VER_{num}"
            if concept_id not in seen_concepts:
                suggestions.append(
                    f"- Se detectó 'b {num}' (o similar): Posiblemente sea 'v{num}'."
                )
                seen_concepts.add(concept_id)

        # 2. Explicit Alias Detection
        for pattern, correct, _ in self.compiled_rules:
            if pattern.search(text):
                concept_id = f"TERM_{correct.upper()}"
                if concept_id not in seen_concepts:
                    suggestions.append(
                        f"- Se detectó término similar a '{correct}' (según diccionario)."
                    )
                    seen_concepts.add(concept_id)

        # 3. Fuzzy Detection
        fuzzy_hits = self._fuzzy_scan_for_hints(text)
        for bad, correct in fuzzy_hits:
            concept_id = f"TERM_{correct.upper()}"
            if concept_id not in seen_concepts:
                suggestions.append(
                    f"- Se detectó '{bad}': Fonéticamente similar a '{correct}'."
                )
                seen_concepts.add(concept_id)

        return suggestions

    # === CORE CAPTURE LOGIC ===

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
                                    if txt and "Micrófono" not in txt:
                                        candidates.append((node_name.Name, txt))
                    except:
                        continue
                if candidates:
                    self.window_name = win.Name
                    return candidates[-1]
        except:
            return None, None
        return None, None

    def _count_words(self):
        # Count words in committed lines + current active line
        full_text = " ".join(self.committed_lines) + " " + self.active_line
        return len(full_text.split())

    def update(self):
        speaker, raw_text = self._get_caption()

        # Basic validation
        if not raw_text or speaker in EXCLUDED_SPEAKERS:
            return False
        clean_text = re.sub(r"\s+", " ", raw_text).strip()
        if not re.search(r"[a-zA-Z0-9]", clean_text):
            return False

        # Frame deduplication (avoid processing exact same frame)
        current_frame_signature = f"{speaker}|{clean_text}"
        if current_frame_signature == self.last_raw_capture:
            return False
        self.last_raw_capture = current_frame_signature
        self.last_activity_time = time.time()

        # === SLIDING WINDOW LOGIC ===

        # 1. Check if speaker changed
        if speaker != self.active_speaker:
            # Commit previous speaker's active line if exists
            if self.active_line:
                self.committed_lines.append(
                    f"[{self.active_speaker}]: {self.active_line}"
                )

            # Start new speaker block
            self.active_speaker = speaker
            self.active_line = clean_text
            return True

        # 2. Same speaker: Check if it's an update to the active line
        # Logic: If the new text contains the old text (growth) OR shares significant overlap
        norm_active = self._normalize_text(self.active_line)
        norm_new = self._normalize_text(clean_text)

        # Case A: Growth (Teams appended words)
        if norm_active in norm_new:
            self.active_line = clean_text  # Update active line to the fuller version
            return True

        # Case B: Correction (Teams changed words but context is same)
        # Use SequenceMatcher only if lengths are comparable to avoid heavy calc on disjoint strings
        if len(norm_new) > 0 and len(norm_active) > 0:
            similarity = SequenceMatcher(None, norm_active, norm_new).ratio()
            if similarity > 0.65:  # Loose threshold for corrections
                self.active_line = clean_text
                return True

        # Case C: New Sentence (Teams cleared buffer or started new sentence)
        # Commit the old active line and start a new one
        if self.active_line:
            self.committed_lines.append(f"[{self.active_speaker}]: {self.active_line}")

        self.active_line = clean_text
        return True

    def check_snapshot(self, force_flush=False):
        current_word_count = self._count_words()
        time_since_activity = time.time() - self.last_activity_time

        is_volume = current_word_count >= WORD_THRESHOLD
        is_silence = (time_since_activity > SILENCE_TIMEOUT) and (
            current_word_count >= MIN_WORDS_FOR_TIMEOUT
        )

        if is_volume or is_silence or (force_flush and current_word_count > 0):
            # Before committing, ensure active line is pushed to committed
            if self.active_line:
                self.committed_lines.append(
                    f"[{self.active_speaker}]: {self.active_line}"
                )
                self.active_line = ""
                self.active_speaker = ""

            return self._commit_block(current_word_count)
        return None

    def _commit_block(self, count):
        timestamp = time.strftime("%H:%M")

        # Join all committed lines
        raw_forensic = "\n".join(self.committed_lines)

        # Generate Derived Outputs
        live_clean = self._generate_live_clean_text(raw_forensic)
        hints = self._generate_ai_suggestions(raw_forensic)

        hints_block = ""
        if hints:
            hints_block = "\n--- SUGERENCIAS DEL SENSOR (GLOSARIO) ---\n" + "\n".join(
                hints
            )

        ai_payload_str = f"=== REUNIÓN: {self.window_name} ===\n"
        if self.previous_context:
            ai_payload_str += f"--- CONTEXTO PREVIO ---\n...{self.previous_context}\n"

        ai_payload_str += f"--- SEGMENTO ACTUAL ({count} palabras) ---\n{raw_forensic}"
        if hints_block:
            ai_payload_str += f"\n{hints_block}"

        # Context Handover
        words = raw_forensic.split()
        tail_words = words[-CONTEXT_OVERLAP:] if len(words) > CONTEXT_OVERLAP else words
        new_overlap = " ".join(tail_words)

        self.previous_context = new_overlap
        self.committed_lines = []  # Clear committed
        # Note: active_line is already cleared in check_snapshot
        self.start_time = time.time()

        return {
            "ts": timestamp,
            "raw_forensic": raw_forensic,
            "live_clean": live_clean,
            "ai_payload": ai_payload_str,
            "meta_header": f"--- BLOQUE {timestamp} (Words: {count}) ---",
        }

    def flush(self):
        return self.check_snapshot(force_flush=True)


# === EXPORTS ===


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
    except:
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
                    # LIVE FEED: Show committed lines + current active line
                    if on_live_update_callback:
                        # Combine history with the fluctuating active line
                        current_view = list(recorder.committed_lines[-8:])
                        if recorder.active_line:
                            current_view.append(
                                f"[{recorder.active_speaker}]: {recorder.active_line}"
                            )

                        raw_buffer = "\n".join(current_view)
                        clean_visual = recorder._generate_live_clean_text(raw_buffer)
                        on_live_update_callback(clean_visual)

                payload = recorder.check_snapshot()
                if payload:
                    block_queue.put(payload)
                time.sleep(0.1)
        finally:
            final_payload = recorder.flush()
            if final_payload:
                block_queue.put(final_payload)
            dispatch_thread.join(timeout=2)
