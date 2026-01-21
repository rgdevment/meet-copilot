import threading
import time

from deep_translator import GoogleTranslator


class RealTimeTranslator:
    def __init__(self, source_lang, target_lang):
        self.source = source_lang
        self.target = target_lang
        self.translator = GoogleTranslator(source=source_lang, target=target_lang)

        self.latest_text = ""
        self.last_translated_text = ""
        self.callback_function = None
        self.running = True

        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def translate_text(self, text):
        # Blocking call for logs
        if not text or len(text.strip()) < 2:
            return ""
        try:
            return self.translator.translate(text)
        except Exception:
            return text

    def translate_live_view(self, text, callback_update):
        # Non-blocking update
        self.latest_text = text
        self.callback_function = callback_update

    def _worker_loop(self):
        while self.running:
            text_to_translate = self.latest_text

            # Avoid redundant translation and small noise
            if (
                text_to_translate
                and text_to_translate != self.last_translated_text
                and len(text_to_translate.strip()) > 5
            ):
                try:
                    translated = self.translator.translate(text_to_translate)
                    self.last_translated_text = text_to_translate

                    if self.callback_function:
                        self.callback_function(translated)

                except Exception:
                    time.sleep(1)

            # Throttle to match human reading speed and reduce API pressure
            time.sleep(0.5)
