import os
import queue
import re
import sys
import threading
import time
from datetime import datetime

from openai import OpenAI

import prompts
import realtime_translator as rt
import teams_stream_capture as tsc
from gui_module import MeetCopilotApp, ask_config_gui

# === CONFIGURATION ===
LM_STUDIO_URL = "http://localhost:1234/v1"
MODEL_NAME = "local-model"
OUTPUT_DIR = "reuniones_logs"

MAX_RETRIES = 3
RETRY_DELAY = 5


class AppState:
    def __init__(self):
        self.status = "Waiting for configuration..."
        self.source_lang = "es"
        self.target_lang = "en"
        self.is_shutting_down = False
        self.source_name = "Teams Capture"


state = AppState()
gui_queue = queue.Queue()
text_process_queue = queue.Queue()

ai_stop_event = threading.Event()
capture_stop_event = threading.Event()


def get_llm_client():
    return OpenAI(base_url=LM_STUDIO_URL, api_key="lm-studio")


def sanitize_filename(name):
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "")
    name = name.strip()[:50].strip()
    name = "_".join(name.split())
    return name if name else "reunion"


def extract_meeting_name_from_window(window_title):
    if not window_title:
        return None
    patterns_to_remove = [
        r"\s*\|\s*Microsoft Teams.*$",
        r"\s*-\s*Microsoft Teams.*$",
        r"^Meeting in\s*",
        r"^Reunión en\s*",
    ]
    name = window_title
    for pattern in patterns_to_remove:
        name = re.sub(pattern, "", name, flags=re.IGNORECASE)
    return name.strip() if name.strip() else None


def setup_meeting_folder(meeting_name, fixed_timestamp):
    """Creates a dedicated folder for the meeting using start time"""
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)

    safe_name = sanitize_filename(meeting_name) if meeting_name else "Meeting"
    folder_name = f"{safe_name}_{fixed_timestamp}"
    folder_path = os.path.join(OUTPUT_DIR, folder_name)

    if not os.path.exists(folder_path):
        os.makedirs(folder_path)

    return folder_path


def generate_file_paths(folder_path):
    """Generates paths for the 4 files inside the dedicated folder"""
    return {
        "forensic": os.path.join(folder_path, "RAW_FORENSE.txt"),
        "live": os.path.join(folder_path, "LOG_VIVO.txt"),
        "ai_input": os.path.join(folder_path, "IA_INPUT.txt"),
        "minuta": os.path.join(folder_path, "MINUTA.md"),
    }


def suggest_meeting_name_with_ai(client, summary_text):
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": prompts.MEETING_NAME_SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": prompts.MEETING_NAME_USER_PROMPT
                        + summary_text[:2000],
                    },
                ],
                temperature=0.2,
                max_tokens=30,
                timeout=20,
            )
            suggested = response.choices[0].message.content.strip()
            return suggested.strip("\"'") if suggested else None
        except Exception:
            if attempt < MAX_RETRIES - 1:
                time.sleep(2)
                continue
            return None


def rename_meeting_folder(current_folder_path, new_name, fixed_timestamp):
    """Renames the entire folder, preserving the original start timestamp"""
    try:
        safe_name = sanitize_filename(new_name)
        new_folder_name = f"{safe_name}_{fixed_timestamp}"
        new_folder_path = os.path.join(OUTPUT_DIR, new_folder_name)

        if current_folder_path != new_folder_path:
            os.rename(current_folder_path, new_folder_path)
            return new_folder_path
        return current_folder_path
    except Exception as e:
        print(f"Error renaming folder: {e}")
        return current_folder_path


def process_smart_segment(client, full_payload):
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": prompts.SMART_SEGMENT_SYSTEM_PROMPT},
                    {"role": "user", "content": full_payload},
                ],
                temperature=0.2,
                timeout=45,
            )
            return response.choices[0].message.content
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                gui_queue.put(("status", f"⚠️ AI Retry {attempt + 1}/{MAX_RETRIES}..."))
                time.sleep(RETRY_DELAY)
                continue
            return f"Error IA (Final): {str(e)}"


def generate_final_summary(client, full_minutes_text):
    gui_queue.put(("status", "🧠 Generando Resumen Final..."))
    for attempt in range(MAX_RETRIES):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": prompts.FINAL_SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": full_minutes_text},
                ],
                temperature=0.4,
                timeout=120,
            )
            return response.choices[0].message.content
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                gui_queue.put(
                    ("status", f"⚠️ Summary Retry {attempt + 1}/{MAX_RETRIES}...")
                )
                time.sleep(RETRY_DELAY * 2)
                continue
            return f"Error Resumen (Final): {str(e)}"


def ai_worker(initial_meeting_name=None):
    client = get_llm_client()
    all_minutes_text = []

    # 1. Capture START time once (Fixed Timestamp)
    start_time_str = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

    # 2. Setup folder and file paths
    current_folder = setup_meeting_folder(initial_meeting_name, start_time_str)
    files = generate_file_paths(current_folder)

    meeting_title = initial_meeting_name or "Meeting"

    # Initialize files headers
    header = f"# LOG - {meeting_title} - Start: {start_time_str}\n\n"

    with open(files["forensic"], "w", encoding="utf-8") as f:
        f.write(f"# RAW FORENSE (Pure Data) {header}")
    with open(files["live"], "w", encoding="utf-8") as f:
        f.write(f"# LOG VIVO (Aggressive Clean) {header}")
    with open(files["ai_input"], "w", encoding="utf-8") as f:
        f.write(f"# AI INPUT (Context + Hints) {header}")
    with open(files["minuta"], "w", encoding="utf-8") as f:
        f.write(f"# TECHNICAL MINUTE {header}")

    gui_queue.put(
        ("status", f"🟢 Ready. Saving to: {os.path.basename(current_folder)}")
    )

    while not ai_stop_event.is_set() or not text_process_queue.empty():
        try:
            if state.is_shutting_down:
                gui_queue.put(
                    (
                        "status",
                        f"🛑 Shutdown: Processing {text_process_queue.qsize()} blocks...",
                    )
                )

            packet = text_process_queue.get(timeout=0.5)

            # Unpack
            ts = packet.get("ts", "00:00")
            raw_forensic = packet.get("raw_forensic", "")
            live_clean = packet.get("live_clean", "")
            ai_payload = packet.get("ai_payload", "")
            meta_header = packet.get("meta_header", "")

            if not state.is_shutting_down:
                gui_queue.put(("status", f"⚡ Processing block {ts}..."))

            # Write logs (Append mode)
            with open(files["forensic"], "a", encoding="utf-8") as f:
                f.write(f"{meta_header}\n{raw_forensic}\n\n")

            with open(files["live"], "a", encoding="utf-8") as f:
                f.write(f"{meta_header}\n{live_clean}\n\n")

            with open(files["ai_input"], "a", encoding="utf-8") as f:
                f.write(f"{meta_header}\n{ai_payload}\n\n")

            # Process AI
            minute_txt = process_smart_segment(client, ai_payload)
            formatted_entry = f"\n## ⏱️ {ts}\n{minute_txt}\n"
            all_minutes_text.append(formatted_entry)

            # Write Minute
            with open(files["minuta"], "a", encoding="utf-8") as f:
                f.write(formatted_entry)
                f.flush()
                os.fsync(f.fileno())

            # Update UI
            clean_ui = (
                minute_txt.replace("### ", "")
                .replace("**", "")
                .replace("labels:", "")
                .strip()
            )
            gui_queue.put(("ai_new", f"⏱️ {ts}\n{clean_ui}\n{'-' * 40}\n"))

            text_process_queue.task_done()
        except queue.Empty:
            continue
        except Exception as e:
            gui_queue.put(("status", f"AI Thread Error: {e}"))

    # Post-meeting processing
    if all_minutes_text:
        full_text = "".join(all_minutes_text)
        summary = generate_final_summary(client, full_text)

        gui_queue.put(("status", "🏷️ Generating smart name..."))
        ai_suggested_name = suggest_meeting_name_with_ai(client, full_text)

        if ai_suggested_name:
            gui_queue.put(("status", f"📝 Renaming folder: {ai_suggested_name}"))
            # Rename folder logic
            new_folder_path = rename_meeting_folder(
                current_folder, ai_suggested_name, start_time_str
            )
            # Update file paths to point to new folder location for final write
            files = generate_file_paths(new_folder_path)

        # Write Final MD
        meeting_title = initial_meeting_name or ai_suggested_name or "Meeting"
        final_content = (
            f"# 📋 MINUTA: {meeting_title}\n"
            f"**Start Date:** {start_time_str}\n\n"
            f"{'=' * 60}\n# 🎯 EXECUTIVE SUMMARY\n{'=' * 60}\n\n{summary}\n\n"
            f"{'=' * 60}\n# 📝 CHRONOLOGICAL LOG\n{'=' * 60}\n{full_text}"
        )

        with open(files["minuta"], "w", encoding="utf-8") as f:
            f.write(final_content)

        gui_queue.put(
            (
                "status",
                f"✅ Saved in: {os.path.basename(new_folder_path if ai_suggested_name else current_folder)}",
            )
        )
    else:
        gui_queue.put(("status", "⚠️ Finished without data."))

    gui_queue.put(("shutdown_complete", True))


def capture_worker(translator):
    def on_smart_block(payload):
        text_process_queue.put(payload)

    def on_live_feed(text_buffer):
        gui_queue.put(("live", text_buffer))
        if len(text_buffer) > 2:
            translator.translate_live_view(
                text_buffer[-600:], lambda trans: gui_queue.put(("trans", trans))
            )

    state.source_name = "Teams Capture"
    tsc.start_headless_capture(on_smart_block, on_live_feed, capture_stop_event)


def perform_shutdown_sequence():
    capture_stop_event.set()
    ai_stop_event.set()


def main():
    s_lang, t_lang = ask_config_gui()
    state.source_lang, state.target_lang = s_lang, t_lang

    translator = rt.RealTimeTranslator(state.source_lang, state.target_lang)

    initial_meeting_name = None
    try:
        teams_window_title = tsc.get_meeting_name()
        if teams_window_title:
            initial_meeting_name = extract_meeting_name_from_window(teams_window_title)
    except Exception:
        pass

    threading.Thread(
        target=ai_worker, args=(initial_meeting_name,), daemon=True
    ).start()
    threading.Thread(target=capture_worker, args=(translator,), daemon=True).start()

    app = MeetCopilotApp(
        s_lang, t_lang, gui_queue, state, translator, perform_shutdown_sequence
    )
    app.mainloop()


def hide_console():
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)


if __name__ == "__main__":
    hide_console()
    main()
