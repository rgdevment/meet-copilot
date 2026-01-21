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

MAX_RETRIES = 3  # Number of attempts before giving up
RETRY_DELAY = 5  # Seconds to wait between attempts


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


def generate_filename(prefix, extension="md", meeting_name=None):
    if not os.path.exists(OUTPUT_DIR):
        os.makedirs(OUTPUT_DIR)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    if meeting_name:
        safe_name = sanitize_filename(meeting_name)
        return f"{OUTPUT_DIR}/{safe_name}-{timestamp}.{extension}"
    return f"{OUTPUT_DIR}/{prefix}_{timestamp}.{extension}"


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


def rename_meeting_files(old_raw, old_min, new_name):
    try:
        safe_name = sanitize_filename(new_name)
        match = re.search(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2})", old_raw)
        if not match:
            return old_raw, old_min

        timestamp = match.group(1)
        new_raw = f"{OUTPUT_DIR}/{safe_name}-{timestamp}.txt"
        new_min = f"{OUTPUT_DIR}/{safe_name}-{timestamp}.md"

        if os.path.exists(old_raw) and old_raw != new_raw:
            os.rename(old_raw, new_raw)
        if os.path.exists(old_min) and old_min != new_min:
            os.rename(old_min, new_min)
        return new_raw, new_min
    except Exception:
        return old_raw, old_min


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
                timeout=45,  # Prevent infinite hanging
            )
            return response.choices[0].message.content
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                # Notify GUI of the retry attempt
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
                timeout=120,  # Final summary needs more time
            )
            return response.choices[0].message.content
        except Exception as e:
            if attempt < MAX_RETRIES - 1:
                gui_queue.put(
                    ("status", f"⚠️ Summary Retry {attempt + 1}/{MAX_RETRIES}...")
                )
                time.sleep(RETRY_DELAY * 2)  # Longer wait for heavy processing
                continue
            return f"Error Resumen (Final): {str(e)}"


def ai_worker(file_min, file_raw, initial_meeting_name=None):
    client = get_llm_client()
    all_minutes_text = []
    current_file_min, current_file_raw = file_min, file_raw

    meeting_title = initial_meeting_name or "Meeting"
    # Create initial files
    with open(current_file_raw, "w", encoding="utf-8") as f:
        f.write(f"# RAW DATA - {meeting_title} - {datetime.now()}\n\n")
    with open(current_file_min, "w", encoding="utf-8") as f:
        f.write(f"# TECHNICAL LOG - {meeting_title} - {datetime.now()}\n\n")

    gui_queue.put(("status", "🟢 Systems Ready. Listening..."))

    while not ai_stop_event.is_set() or not text_process_queue.empty():
        try:
            if state.is_shutting_down:
                gui_queue.put(
                    (
                        "status",
                        f"🛑 Shutdown: Processing {text_process_queue.qsize()} blocks...",
                    )
                )

            payload_text = text_process_queue.get(timeout=0.5)
            ts = datetime.now().strftime("%H:%M")

            if not state.is_shutting_down:
                gui_queue.put(("status", f"⚡ Processing block {ts}..."))

            # Save faithful RAW immediately as delivered by sensor
            with open(current_file_raw, "a", encoding="utf-8") as f:
                f.write(f"\n{payload_text}\n")
                f.flush()
                os.fsync(f.fileno())

            # Generate smart segment with IA
            minute_txt = process_smart_segment(client, payload_text)
            formatted_entry = f"\n## ⏱️ {ts}\n{minute_txt}\n"
            all_minutes_text.append(formatted_entry)

            # Persist technical minute
            with open(current_file_min, "a", encoding="utf-8") as f:
                f.write(formatted_entry)
                f.flush()
                os.fsync(f.fileno())

            # Update UI (LIFO display)
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
            gui_queue.put(("status", f"📝 Renaming: {ai_suggested_name}"))
            current_file_raw, current_file_min = rename_meeting_files(
                current_file_raw, current_file_min, ai_suggested_name
            )

        # Re-structure final document
        meeting_title = initial_meeting_name or ai_suggested_name or "Meeting"
        final_content = (
            f"# 📋 MINUTA: {meeting_title}\n"
            f"**Date:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
            f"{'=' * 60}\n# 🎯 EXECUTIVE SUMMARY\n{'=' * 60}\n\n{summary}\n\n"
            f"{'=' * 60}\n# 📝 CHRONOLOGICAL LOG\n{'=' * 60}\n{full_text}"
        )

        with open(current_file_min, "w", encoding="utf-8") as f:
            f.write(final_content)
            f.flush()
            os.fsync(f.fileno())

        gui_queue.put(("status", f"✅ Saved: {os.path.basename(current_file_min)}"))
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


# main_meeting_ai.py (Ajuste en la inicialización)

def main():
    """Punto de entrada principal actualizado para la nueva GUI"""
    s_lang, t_lang = ask_config_gui()
    state.source_lang, state.target_lang = s_lang, t_lang

    # 1. Creamos el traductor primero
    translator = rt.RealTimeTranslator(state.source_lang, state.target_lang)

    initial_meeting_name = None
    try:
        teams_window_title = tsc.get_meeting_name()
        if teams_window_title:
            initial_meeting_name = extract_meeting_name_from_window(teams_window_title)
    except Exception:
        pass

    file_raw = generate_filename("RAW", "txt", initial_meeting_name)
    file_min = generate_filename("MINUTA", "md", initial_meeting_name)

    # 2. Iniciamos los hilos (workers)
    threading.Thread(
        target=ai_worker, args=(file_min, file_raw, initial_meeting_name), daemon=True
    ).start()
    threading.Thread(target=capture_worker, args=(translator,), daemon=True).start()

    # 3. PASAR EL TRANSLATOR A LA APP (Cambio crítico aquí)
    app = MeetCopilotApp(
        s_lang,
        t_lang,
        gui_queue,
        state,
        translator, # <-- Añadimos esto para el botón de cambio de idioma
        perform_shutdown_sequence
    )
    app.mainloop()


def hide_console():
    if sys.platform == "win32":
        import ctypes

        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)


if __name__ == "__main__":
    hide_console()
    main()
