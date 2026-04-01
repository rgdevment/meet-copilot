import threading
import time

from deep_translator import GoogleTranslator


class Translator:
    def __init__(self, source_lang: str, target_lang: str):
        self.source = source_lang
        self.target = target_lang
        self.translator = GoogleTranslator(source=source_lang, target=target_lang)

        self._latest_text = ""
        self._last_translated = ""
        self._callback = None
        self._running = True

        self._worker = threading.Thread(target=self._loop, daemon=True)
        self._worker.start()

    def translate_blocking(self, text: str) -> str:
        if not text or len(text.strip()) < 2:
            return ""
        try:
            return self.translator.translate(text)
        except Exception:
            return text

    def translate_async(self, text: str, callback):
        self._callback = callback
        self._latest_text = text

    def swap_languages(self):
        self.source, self.target = self.target, self.source
        self.translator = GoogleTranslator(source=self.source, target=self.target)
        self._last_translated = ""

    def stop(self):
        self._running = False

    def _loop(self):
        while self._running:
            text = self._latest_text
            if (
                text
                and text != self._last_translated
                and len(text.strip()) > 5
            ):
                try:
                    translated = self.translator.translate(text)
                    self._last_translated = text
                    if self._callback:
                        self._callback(translated)
                except Exception:
                    time.sleep(1)
            time.sleep(0.5)
