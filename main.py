import queue
import sys
import threading

__version__ = "2.0"

if "--version" in sys.argv:
    print(__version__)
    sys.exit(0)

REQUIRED_PACKAGES = {
    "openai": "openai",
    "anthropic": "anthropic",
    "google.generativeai": "google-generativeai",
    "deep_translator": "deep-translator",
    "customtkinter": "customtkinter",
}

if sys.platform == "win32":
    REQUIRED_PACKAGES["uiautomation"] = "uiautomation"
elif sys.platform == "darwin":
    REQUIRED_PACKAGES["ApplicationServices"] = "pyobjc-framework-ApplicationServices"
    REQUIRED_PACKAGES["Quartz"] = "pyobjc-framework-Quartz"


def check_dependencies():
    missing = []
    for module, package in REQUIRED_PACKAGES.items():
        try:
            __import__(module)
        except ImportError:
            missing.append(package)
    if missing:
        print("\n[ERROR] Missing required packages:\n")
        for pkg in missing:
            print(f"  - {pkg}")
        print("\nRun:  pip install -r requirements.txt\n")
        sys.exit(1)


check_dependencies()

from capture.manager import create_capture_source, start_capture
from config import AppConfig
from processing.glossary import GlossaryProcessor
from processing.pipeline import ProcessingPipeline, extract_meeting_name
from processing.translator import Translator
from providers import create_provider
from ui.app import MeetingApp
from ui.config_dialog import ConfigDialog

gui_queue = queue.Queue()
ai_stop_event = threading.Event()
capture_stop_event = threading.Event()


def setup_logging(output_dir: str):
    import logging
    import os

    diag_dir = os.path.join(output_dir, "_diag")
    os.makedirs(diag_dir, exist_ok=True)
    level = logging.DEBUG if os.environ.get("MEETCOPILOT_DEBUG") else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(
                os.path.join(diag_dir, "meetcopilot.log"), encoding="utf-8"
            )
        ],
    )


def perform_shutdown(pipeline: ProcessingPipeline, translator: Translator):
    pipeline.is_shutting_down = True
    translator.stop()
    capture_stop_event.set()
    ai_stop_event.set()


def main():
    config = AppConfig.load()
    dialog = ConfigDialog(config)
    config = dialog.run()
    if config is None:
        return

    setup_logging(config.output_dir)

    provider = create_provider(config)
    glossary = GlossaryProcessor(passive=config.glossary_passive)
    translator = Translator(config.source_lang, config.target_lang)
    source = create_capture_source(config.platform)
    pipeline = ProcessingPipeline(config, provider, gui_queue, glossary=glossary)

    pipeline.initialize(None)

    def capture_worker():
        def on_block(payload):
            pipeline.enqueue_block(payload)

        def on_live(text):
            gui_queue.put(("live", text))
            if len(text) > 2:
                translator.translate_async(
                    text[-600:], lambda t: gui_queue.put(("trans", t))
                )

        import os

        diag_dir = os.path.join(config.output_dir, "_diag")

        # start_capture calls source.initialize() internally
        start_capture(
            source, glossary, on_block, on_live, capture_stop_event,
            on_meeting_name_callback=lambda name: pipeline.update_meeting_name(
                extract_meeting_name(name) or name
            ),
            diag_dir=diag_dir,
            read_all_nodes=config.capture_all_nodes,
            on_status_callback=lambda msg: gui_queue.put(("status", msg)),
        )

    def ai_worker():
        pipeline.run(ai_stop_event)

    threading.Thread(target=ai_worker, daemon=True).start()
    threading.Thread(target=capture_worker, daemon=True).start()

    app = MeetingApp(
        config=config,
        gui_queue=gui_queue,
        translator=translator,
        shutdown_callback=lambda: perform_shutdown(pipeline, translator),
    )
    app.on_note_callback = pipeline.add_context_note
    app.mainloop()


def hide_console():
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)


if __name__ == "__main__":
    hide_console()
    main()
