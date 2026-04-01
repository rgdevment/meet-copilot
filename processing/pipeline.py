import os
import queue
import re
import shutil
import threading
import time
from datetime import datetime

import prompts
from config import BASE_DIR, MAX_RETRIES, RETRY_DELAY, AppConfig
from providers.base import LLMProvider

PROJECT_CONTEXT_FILE = os.path.join(BASE_DIR, "project_context.txt")


def load_project_context() -> str:
    if os.path.exists(PROJECT_CONTEXT_FILE):
        try:
            with open(PROJECT_CONTEXT_FILE, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:
            pass
    return ""


def sanitize_filename(name: str) -> str:
    for char in '<>:"/\\|?*':
        name = name.replace(char, "")
    name = name.strip()[:50].strip()
    name = "_".join(name.split())
    return name if name else "reunion"


def extract_meeting_name(window_title: str) -> str | None:
    if not window_title:
        return None
    patterns = [
        r"\s*\|\s*Microsoft Teams.*$",
        r"\s*-\s*Microsoft Teams.*$",
        r"^Meeting in\s*",
        r"^Reunión en\s*",
    ]
    name = window_title
    for p in patterns:
        name = re.sub(p, "", name, flags=re.IGNORECASE)
    return name.strip() or None


class ProcessingPipeline:
    def __init__(self, config: AppConfig, provider: LLMProvider, gui_queue: queue.Queue):
        self.config = config
        self.provider = provider
        self.gui_queue = gui_queue
        self.text_queue = queue.Queue()
        self.all_minutes: list[str] = []
        self.is_shutting_down = False

        self._start_time_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        self._meeting_name = ""
        self._folder_path = ""
        self._files: dict[str, str] = {}

        # Double-pass & topic tracking
        self._project_context = load_project_context()
        self._meeting_topic = ""
        self._block_count = 0
        self._running_notes: list[str] = []

    def initialize(self, meeting_name: str | None = None):
        self._meeting_name = meeting_name or "Meeting"
        self._folder_path = self._setup_folder()
        self._files = self._generate_paths()
        self._init_log_files()
        self.gui_queue.put(
            ("status", f"Ready. Folder: {os.path.basename(self._folder_path)}")
        )

    def enqueue_block(self, payload: dict):
        self.text_queue.put(payload)

    def update_meeting_name(self, name: str):
        if name and name != self._meeting_name:
            self._meeting_name = name
            new_folder = self._setup_folder()
            # Move existing files to new folder
            for key, path in self._files.items():
                if os.path.exists(path):
                    shutil.move(path, new_folder)
            if os.path.exists(self._folder_path) and self._folder_path != new_folder:
                try:
                    os.rmdir(self._folder_path)
                except OSError:
                    pass
            self._folder_path = new_folder
            self._files = self._generate_paths()
            self.gui_queue.put(("status", f"Meeting: {name}"))

    def add_context_note(self, note: str):
        self._running_notes.append(note)
        if len(self._running_notes) > 50:
            self._running_notes = self._running_notes[-50:]

    def _build_correction_prompt(self) -> str:
        parts = [self._project_context] if self._project_context else []
        if self._meeting_topic:
            parts.append(f"Meeting Topic: {self._meeting_topic}")
        if self._running_notes:
            parts.append("Runtime Notes:\n" + "\n".join(f"- {n}" for n in self._running_notes))
        context = "\n\n".join(parts) or "(No project context provided)"
        return prompts.CORRECTION_SYSTEM_PROMPT.format(project_context=context)

    def run(self, stop_event: threading.Event):
        while not stop_event.is_set() or not self.text_queue.empty():
            try:
                if self.is_shutting_down:
                    self.gui_queue.put(
                        ("status", f"Shutdown: Processing {self.text_queue.qsize()} blocks...")
                    )
                packet = self.text_queue.get(timeout=0.5)
                self._process_packet(packet)
                self.text_queue.task_done()
            except queue.Empty:
                continue
            except Exception as e:
                self.gui_queue.put(("status", f"Pipeline Error: {e}"))

        self._finalize()

    def _process_packet(self, packet: dict):
        ts = packet.get("ts", "00:00")
        raw_forensic = packet.get("raw_forensic", "")
        live_clean = packet.get("live_clean", "")
        meta_header = packet.get("meta_header", "")
        self._block_count += 1

        if not self.is_shutting_down:
            self.gui_queue.put(("status", f"Correcting block {ts}..."))

        # Log raw data
        with open(self._files["forensic"], "a", encoding="utf-8") as f:
            f.write(f"{meta_header}\n{raw_forensic}\n\n")
        with open(self._files["live"], "a", encoding="utf-8") as f:
            f.write(f"{meta_header}\n{live_clean}\n\n")

        # === PASS 1: Correction (fast/cheap model) ===
        hints = packet.get("hints", "")
        correction_input = raw_forensic
        if hints:
            correction_input += f"\n{hints}"
        corrected_text = self._call_ai(
            self._build_correction_prompt(), correction_input, temperature=0.1, timeout=30
        )

        # Log corrected input
        with open(self._files["ai_input"], "a", encoding="utf-8") as f:
            f.write(f"{meta_header}\n[CORRECTED]\n{corrected_text}\n\n")

        # === TOPIC EXTRACTION (after first block) ===
        if self._block_count == 1 and corrected_text:
            topic_prompt = prompts.TOPIC_EXTRACTION_PROMPT.format(
                text=corrected_text[:1500]
            )
            self._meeting_topic = self._call_ai(
                "You extract meeting topics.", topic_prompt,
                temperature=0.1, max_tokens=100, timeout=15
            ).strip()
            if self._meeting_topic:
                self.gui_queue.put(("topic", self._meeting_topic))

        # === PASS 2: Technical minute (main model, clean text) ===
        if not self.is_shutting_down:
            self.gui_queue.put(("status", f"Analyzing block {ts}..."))

        segment_input = ""
        if self._meeting_topic:
            segment_input += f"--- TEMA DE LA REUNIÓN ---\n{self._meeting_topic}\n\n"
        if self.all_minutes:
            last_minutes = "\n".join(self.all_minutes[-2:])
            segment_input += f"--- MINUTAS PREVIAS ---\n{last_minutes}\n\n"
        if packet.get("previous_context"):
            segment_input += f"--- CONTEXTO PREVIO (RAW) ---\n{packet['previous_context']}\n\n"
        segment_input += f"--- SEGMENTO ACTUAL ---\n{corrected_text}"

        minute_txt = self._call_ai(
            prompts.SMART_SEGMENT_SYSTEM_PROMPT, segment_input, timeout=45
        )
        formatted = f"\n## ⏱️ {ts}\n{minute_txt}\n"
        self.all_minutes.append(formatted)

        with open(self._files["minuta"], "a", encoding="utf-8") as f:
            f.write(formatted)

        clean_ui = (
            minute_txt.replace("### ", "")
            .replace("**", "")
            .replace("labels:", "")
            .strip()
        )
        self.gui_queue.put(("ai_new", f"⏱️ {ts}\n{clean_ui}\n{'-' * 40}\n"))

    def _finalize(self):
        if not self.all_minutes:
            self.gui_queue.put(("status", "Finished without data."))
            self.gui_queue.put(("shutdown_complete", True))
            return

        full_text = "".join(self.all_minutes)

        self.gui_queue.put(("status", "Generating Final Summary..."))
        summary = self._call_ai(
            prompts.FINAL_SUMMARY_SYSTEM_PROMPT, full_text, temperature=0.4, timeout=120
        )

        self.gui_queue.put(("status", "Generating smart name..."))
        ai_name = self._suggest_name(full_text)

        if ai_name:
            self.gui_queue.put(("status", f"Renaming to: {ai_name}"))
            self._folder_path = self._rename_all(ai_name)
            self._files = self._generate_paths()
            self._meeting_name = ai_name

        final_content = (
            f"# MINUTA: {self._meeting_name}\n"
            f"**Start Date:** {self._start_time_str}\n\n"
            f"{'=' * 60}\n# EXECUTIVE SUMMARY\n{'=' * 60}\n\n{summary}\n\n"
            f"{'=' * 60}\n# CHRONOLOGICAL LOG\n{'=' * 60}\n{full_text}"
        )
        with open(self._files["minuta"], "w", encoding="utf-8") as f:
            f.write(final_content)

        self.gui_queue.put(
            ("status", f"Saved in: {os.path.basename(self._folder_path)}")
        )
        self.gui_queue.put(("shutdown_complete", self._files["minuta"]))

    def _call_ai(self, system: str, user: str, temperature=0.2, max_tokens=None, timeout=45) -> str:
        for attempt in range(MAX_RETRIES):
            try:
                return self.provider.chat(
                    system=system,
                    user=user,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                )
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    self.gui_queue.put(
                        ("status", f"AI Retry {attempt + 1}/{MAX_RETRIES}...")
                    )
                    time.sleep(RETRY_DELAY)
                else:
                    return f"AI Error (Final): {e}"
        return ""

    def _suggest_name(self, text: str) -> str | None:
        for attempt in range(MAX_RETRIES):
            try:
                result = self.provider.chat(
                    system=prompts.MEETING_NAME_SYSTEM_PROMPT,
                    user=prompts.MEETING_NAME_USER_PROMPT + text[:2000],
                    temperature=0.2,
                    max_tokens=30,
                    timeout=20,
                )
                suggested = result.strip().strip("\"'")
                return suggested if suggested else None
            except Exception:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(2)
        return None

    def _setup_folder(self) -> str:
        os.makedirs(self.config.output_dir, exist_ok=True)
        safe_name = sanitize_filename(self._meeting_name)
        folder = os.path.join(
            self.config.output_dir, f"{safe_name}_{self._start_time_str}"
        )
        os.makedirs(folder, exist_ok=True)
        return folder

    def _generate_paths(self) -> dict[str, str]:
        safe = sanitize_filename(self._meeting_name)
        return {
            "forensic": os.path.join(self._folder_path, f"{safe}_RAW_FORENSE.txt"),
            "live": os.path.join(self._folder_path, f"{safe}_LOG_VIVO.txt"),
            "ai_input": os.path.join(self._folder_path, f"{safe}_IA_INPUT.txt"),
            "minuta": os.path.join(self._folder_path, f"{safe}_MINUTA.md"),
        }

    def _init_log_files(self):
        header = f"# LOG - {self._meeting_name} - Start: {self._start_time_str}\n\n"
        labels = {
            "forensic": "RAW FORENSE",
            "live": "LOG VIVO",
            "ai_input": "AI INPUT",
            "minuta": "TECHNICAL MINUTE",
        }
        for key, label in labels.items():
            with open(self._files[key], "w", encoding="utf-8") as f:
                f.write(f"# {label} {header}")

    def _rename_all(self, new_name: str) -> str:
        try:
            safe_old = sanitize_filename(self._meeting_name)
            safe_new = sanitize_filename(new_name)

            new_folder = os.path.join(
                self.config.output_dir, f"{safe_new}_{self._start_time_str}"
            )
            if self._folder_path != new_folder:
                os.rename(self._folder_path, new_folder)

            if os.path.exists(new_folder):
                for filename in os.listdir(new_folder):
                    if safe_old in filename:
                        new_filename = filename.replace(safe_old, safe_new, 1)
                        os.rename(
                            os.path.join(new_folder, filename),
                            os.path.join(new_folder, new_filename),
                        )
            return new_folder
        except Exception as e:
            print(f"Rename error: {e}")
            return self._folder_path
