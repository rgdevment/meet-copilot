from deep_translator import GoogleTranslator
import threading
import time

class RealTimeTranslator:
    def __init__(self, source_lang, target_lang):
        """
        source_lang: 'es' o 'en'
        target_lang: 'en' o 'es'
        """
        self.source = source_lang
        self.target = target_lang
        self.translator = GoogleTranslator(source=source_lang, target=target_lang)

        self.latest_text = ""
        self.last_translated_text = ""
        self.last_translation_result = ""
        self.callback_function = None
        self.running = True

        self.worker_thread = threading.Thread(target=self._worker_loop, daemon=True)
        self.worker_thread.start()

    def translate_text(self, text):
        """
        Traducción síncrona/bloqueante para los archivos de log (Contextos).
        Aquí no importa si tarda un poco porque es para el archivo.
        """
        if not text or len(text.strip()) < 2:
            return ""
        try:
            return self.translator.translate(text)
        except Exception:
            return text # Si falla, devuelve el original

    def translate_live_view(self, text, callback_update):
        """
        Método NO BLOQUEANTE.
        Solo actualiza la variable 'latest_text'. El hilo trabajador se encarga del resto.
        """
        self.latest_text = text
        self.callback_function = callback_update

    def _worker_loop(self):
        """
        Bucle infinito que corre en segundo plano.
        Revisa cada X ms si hay texto nuevo para traducir.
        """
        while self.running:
            # 1. Chequeo de seguridad: ¿Hay texto y es diferente al último traducido?
            # También ignoramos textos muy cortos para no saturar
            text_to_translate = self.latest_text

            if (text_to_translate and
                text_to_translate != self.last_translated_text and
                len(text_to_translate.strip()) > 2):

                try:
                    # 2. TRADUCCIÓN REAL (Aquí es donde ocurre la demora de red)
                    translated = self.translator.translate(text_to_translate)

                    # 3. Actualizar estado
                    self.last_translation_result = translated
                    self.last_translated_text = text_to_translate

                    # 4. Llamar al UI
                    if self.callback_function:
                        self.callback_function(translated)

                except Exception as e:
                    # Si falla la red, esperamos un poco más antes de reintentar
                    time.sleep(1)

            time.sleep(0.3)
