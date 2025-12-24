import uiautomation as auto
import re
import time
from collections import deque
from difflib import SequenceMatcher

# === CONFIGURACIÓN ===
WORD_THRESHOLD = 350       # Palabras para enviar bloque completo
SILENCE_TIMEOUT = 20       # Segundos de silencio para enviar bloque parcial
MIN_WORDS_FOR_TIMEOUT = 50 # Mínimo de palabras para activar timeout
CONTEXT_OVERLAP = 50       # Palabras de contexto previo para la IA

class TeamsRecorderSmart:
    def __init__(self):
        self.start_time = time.time()
        self.last_activity_time = time.time()
        self.buffer_lines = []
        self.previous_context = ""
        self.snapshots = deque(maxlen=50)
        self.window_name = "Buscando Teams..."
        self.last_raw = ""

    def _get_caption(self):
        try:
            # Busca ventanas de Teams de forma segura
            roots = auto.WindowControl(searchDepth=1, ClassName="TeamsWebView").GetChildren()
            sorted_wins = sorted(roots, key=lambda w: 0 if "Meeting" in w.Name or "Reunión" in w.Name else 1)

            for win in sorted_wins:
                if "Chat" in win.Name: continue
                try:
                    if not win.Exists(0, 0): continue
                    web_area = win.DocumentControl(searchDepth=15, AutomationId="RootWebArea")
                    if not web_area.Exists(0, 0): web_area = win
                except:
                    continue

                candidates = []
                # Escaneo profundo buscando subtítulos
                for control, depth in auto.WalkControl(web_area, maxDepth=14):
                    try:
                        if control.ControlTypeName == "GroupControl":
                            children = control.GetChildren()
                            if len(children) >= 2:
                                node_name = children[0]
                                node_text = children[1]
                                if (node_name.ControlTypeName == "TextControl" and
                                    node_text.ControlTypeName == "TextControl"):
                                    txt = node_text.Name
                                    # Filtros básicos de ruido
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
        if not raw_text: return False

        clean_text = re.sub(r'\s+', ' ', raw_text).strip()
        full_line = f"[{speaker}]: {clean_text}"

        if full_line == self.last_raw: return False

        self.last_raw = full_line
        self.last_activity_time = time.time()

        # Lógica de Deduplicación
        if self.buffer_lines:
            last_saved = self.buffer_lines[-1]
            if f"[{speaker}]" in last_saved:
                last_content = last_saved.split("]: ", 1)[1] if "]: " in last_saved else ""
                if last_content in clean_text:
                    self.buffer_lines.pop()
                    self.buffer_lines.append(full_line)
                    return True
                if self._is_similar(last_content, clean_text):
                    self.buffer_lines.pop()
                    self.buffer_lines.append(full_line)
                    return True

        self.buffer_lines.append(full_line)
        return True

    def check_snapshot(self, force_flush=False):
        current_word_count = self._count_words()
        time_since_activity = time.time() - self.last_activity_time

        is_volume = current_word_count >= WORD_THRESHOLD
        is_silence = (time_since_activity > SILENCE_TIMEOUT) and (current_word_count >= MIN_WORDS_FOR_TIMEOUT)

        if is_volume or is_silence or (force_flush and current_word_count > 0):
            return self._commit_block(current_word_count)

        return None

    def _commit_block(self, count):
        timestamp = time.strftime('%H:%M')
        raw_content = "\n".join(self.buffer_lines)

        # Calcular Overlap para el siguiente bloque
        words = raw_content.split()
        tail_words = words[-CONTEXT_OVERLAP:] if len(words) > CONTEXT_OVERLAP else words
        new_overlap = " ".join(tail_words)

        # Construir Payload para IA
        final_payload = ""
        if self.previous_context:
            final_payload += f"--- CONTEXTO PREVIO (Overlap) ---\n...{self.previous_context}\n"

        final_payload += f"--- SEGMENTO ACTUAL ({count} palabras) ---\n{raw_content}"

        # Guardar snapshot interno
        header = f"--- BLOQUE {timestamp} (Words: {count}) ---"
        self.snapshots.append(f"{header}\n{final_payload}")

        # Resetear estado
        self.previous_context = new_overlap
        self.buffer_lines = []
        self.start_time = time.time()

        return final_payload

    def flush(self):
        return self.check_snapshot(force_flush=True)

# === ENTRY POINT DEL HILO ===
def start_headless_capture(on_block_complete_callback, on_live_update_callback, stop_event):
    with auto.UIAutomationInitializerInThread():
        recorder = TeamsRecorderSmart()

        try:
            while not stop_event.is_set():
                recorder.update()

                # 1. LIVE UPDATE (Solo si hay cambio visual)
                if on_live_update_callback:
                    # Enviamos solo las ultimas lineas para visualizar
                    current_buffer = "\n".join(recorder.buffer_lines[-8:])
                    on_live_update_callback(current_buffer)

                # 2. CHECK BLOCK (IA)
                payload = recorder.check_snapshot()
                if payload:
                    on_block_complete_callback(payload)

                time.sleep(0.1)

        except Exception:
            pass # Evitar romper el hilo principal si Teams falla

        finally:
            # FLUSH FINAL
            final_payload = recorder.flush()
            if final_payload:
                on_block_complete_callback(final_payload)
