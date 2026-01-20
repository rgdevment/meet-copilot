import os
import queue
import re
import sys
import threading
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, scrolledtext

from openai import OpenAI

import realtime_translator as rt
import teams_stream_capture as tsc

# === CONFIGURACIÓN ===
LM_STUDIO_URL = "http://localhost:1234/v1"
MODEL_NAME = "local-model"
OUTPUT_DIR = "reuniones_logs"

# === PALETA DE COLORES (VS CODE DARK THEME) ===
COLORS = {
    "bg_main": "#1e1e1e",  # Fondo principal
    "bg_panel": "#252526",  # Fondo cajas texto
    "fg_text": "#d4d4d4",  # Texto normal
    "fg_accent": "#007acc",  # Azul VS Code
    "fg_live": "#4ec9b0",  # Verde Cybertruck
    "fg_trans": "#ce9178",  # Naranja suave
    "fg_ai": "#9cdcfe",  # Azul claro
    "fg_dim": "#858585",  # Gris logs
    "border": "#3e3e42",  # Bordes sutiles
}


# === ESTADO GLOBAL ===
class AppState:
    def __init__(self):
        self.status = "Esperando configuración..."
        self.source_lang = "es"
        self.target_lang = "en"
        self.is_shutting_down = False
        self.source_name = "Teams Capture"


state = AppState()
# Colas Thread-Safe
gui_queue = queue.Queue()
text_process_queue = queue.Queue()

ai_stop_event = threading.Event()
capture_stop_event = threading.Event()


# === HELPERS ===
def get_llm_client():
    return OpenAI(base_url=LM_STUDIO_URL, api_key="lm-studio")


def sanitize_filename(name):
    """Limpia un string para usarlo como nombre de archivo."""
    # Remover caracteres no válidos para Windows
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, "")
    # Limitar longitud y limpiar espacios
    name = name.strip()[:50].strip()
    # Reemplazar espacios múltiples y caracteres especiales
    name = "_".join(name.split())
    return name if name else "reunion"


def extract_meeting_name_from_window(window_title):
    if not window_title:
        return None
    # Patrones comunes de Teams: "Nombre Reunión | Microsoft Teams"
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
    prompt = """
    Basándote en este resumen de reunión, genera un nombre corto y descriptivo (máximo 5 palabras).
    El nombre debe capturar el tema principal de la reunión.
    Responde SOLO con el nombre, sin explicaciones ni puntuación extra.

    Ejemplos de buenos nombres:
    - "Seguimiento de discovery API"
    - "Revisión Bugs Producción"
    - "Arquitectura Microservicios Auth"
    - "Daily Standup Equipo Mobile"

    Resumen:
    """
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {
                    "role": "system",
                    "content": "Eres un asistente que genera nombres cortos y descriptivos para reuniones técnicas.",
                },
                {"role": "user", "content": prompt + summary_text[:2000]},
            ],
            temperature=0.2,
            max_tokens=30,
        )
        suggested = response.choices[0].message.content.strip()
        suggested = suggested.strip("\"'")
        return suggested if suggested else None
    except Exception:
        return None


def rename_meeting_files(old_raw, old_min, new_name):
    try:
        safe_name = sanitize_filename(new_name)

        # Extraer timestamp del nombre original
        match = re.search(r"(\d{4}-\d{2}-\d{2}_\d{2}-\d{2})", old_raw)
        if not match:
            return old_raw, old_min
        timestamp = match.group(1)

        new_raw = f"{OUTPUT_DIR}/RAW_{timestamp}_{safe_name}.txt"
        new_min = f"{OUTPUT_DIR}/MINUTA_{timestamp}_{safe_name}.md"

        # Solo renombrar si los archivos existen y el nuevo nombre es diferente
        if os.path.exists(old_raw) and old_raw != new_raw:
            os.rename(old_raw, new_raw)
        if os.path.exists(old_min) and old_min != new_min:
            os.rename(old_min, new_min)

        return new_raw, new_min
    except Exception:
        return old_raw, old_min


# === LÓGICA IA ===
def process_smart_segment(client, full_payload):
    system_prompt = """
    # ROL: Senior Tech Lead & Analista de Contexto Forense
    # OBJETIVO: Generar una Bitácora Técnica de Alta Fidelidad a partir de OCR/Audio imperfecto.

    # CONTEXTO OPERATIVO:
    1. INPUT: Recibirás un bloque de texto con "CONTEXTO PREVIO" (primeras 50 palabras) y "SEGMENTO ACTUAL" (siguientes 350 palabras).
    2. FUENTE: Transcripción humana/OCR con mucho ruido, Spanglish, errores fonéticos y acentos fuertes, perdida de audios.
    3. META: Reconstruir la realidad técnica del "SEGMENTO ACTUAL" sin perder UN SOLO detalle crítico.
    4. IDIOMA DE SALIDA: OBLIGATORIAMENTE ESPAÑOL.

    # DICCIONARIO DINÁMICO & REGLAS FONÉTICAS:
    Actúa como un decodificador semántico. Usa este mapeo base, pero aplica la lógica: "¿Suena esto como un término técnico en inglés dicho por un hispanohablante?, ¿Se menciono antes o utilizo una palabra similar que puedar dar conexto y sentido a esta palabra?"

    * Metodología: "escrún/escaun"->Scrum, "vackloc"->Backlog, "deili"->Daily, "gru-min"->Grooming.
    * Infra/DevOps: "paine/paylain"->Pipeline, "dokér"->Docker, "yámel"->YAML, "de-ploi"->Deploy, "kubernetis"->Kubernetes, "infrestrachur"->Infrastructure.
    * Código/Dev: "cuat"->QA/UAT, "vug/back"->Bug, "re-fact"->Refactor, "jaison/yeison"->JSON, "brunch"->Branch, "chisme"->Schema, "mono redpo"->Monorepo, "depor puches"->purchases.
    * Negocio/Entidades: "estéicol"->Stakeholder, "pi-o"->PO, "peme"->PM, "cián"->CIAM, "Sogo"->SOCO, "sorb"->SOBR, "andy"->Andes, "biyu"->BIU, "flavela"->Falabella, "Yarby"->Jarvis.
    * Cloud: "ázur"->Azure, "ámason"->Amazon, "gúgol"->Google.

    # INSTRUCCIONES CRÍTICAS (NO OMITIR NADA):
    1. POLÍTICA DE CERO OMISIÓN: Trata cada sustantivo técnico, número, ID de ticket, nombre de tabla o nombre propio como CRÍTICO. Si tienes duda de qué palabra es, escríbela tal cual con un signo [?]. Es mejor incluir el dato sucio que borrarlo.
    2. REPARACIÓN CONTEXTUAL: Usa el "CONTEXTO PREVIO" para resolver ambigüedades. (Ej: Si antes se habló de "Base de datos" y ahora dice "la base", infiere "Base de Datos").
    3. INFERENCIA FONÉTICA AGRESIVA: Si lees "el vaquen", infiere "Backend". Si lees "frone", infiere "Frontend". Asume siempre que es un desarrollador hablando rápido en Spanglish.
    4. FILTRO DE RUIDO: Solo elimina saludos vacíos o muletillas sociales puras (ej: "bueno pues", "este..."). Mantén cualquier comentario sobre el estado de ánimo del equipo (ej: "estamos quemados" -> Riesgo de Burnout).

    # FORMATO DE SALIDA (Strict Markdown en Español):

    ## [TEMA DOMINANTE DEL SEGMENTO]

    **> Reconstrucción Técnica (El "Qué"):**
    (Una síntesis detallada en viñetas de los hechos técnicos. Corrige la terminología pero mantén el significado específico. Usa lenguaje técnico profesional).

    **> Puntos de Datos Críticos (Extracción Minuciosa):**
    * [Entidades]: (Lista exhaustiva de sistemas, APIs, Tablas, DBs mencionadas. Ej: 'tabla user_logs', 'API B2B').
    * [Acciones]: (¿Qué se está haciendo exactamente? Ej: 'Refactorizando', 'Migrando', 'Depurando').

    **> Acuerdos y Bloqueos:**
    * [Decisión/Tarea]: (¿Quién hace qué? Nombres y responsabilidades).
    * [Riesgo/Impedimento]: (Cualquier error técnico, bloqueo o problema mencionado).
    """
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": full_payload},
            ],
            temperature=0.2,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error IA: {str(e)}"


def generate_final_summary(client, full_minutes_text):
    gui_queue.put(("status", "🧠 Generando Resumen Final..."))

    system_prompt = """
    # ROL: Director de Ingeniería & Lead Technical PMO
    # TAREA: Generar un REPORTE TÉCNICO-EJECUTIVO MAESTRO (High-Fidelity).

    # INPUT:
    Recibirás una lista secuencial de "minutas segmentadas".

    # OBJETIVO PRINCIPAL:
    No hagas un "copiar-pegar" de los resúmenes anteriores. Tu trabajo es SINTETIZAR, LIMPIAR y ESTRUCTURAR la narrativa completa de la reunión. Debes detectar el hilo conductor, eliminar redundancias y resolver contradicciones (si en el minuto 10 dijeron "A" y en el minuto 50 corrigieron a "B", el reporte final debe decir "B").

    # REGLAS DE ENRIQUECIMIENTO (Critical Thinking):
    1. CLASIFICACIÓN TEMÁTICA: No ordenes por tiempo, ordena por TEMA (Backend, Frontend, Infra, Negocio).
    2. PROFUNDIDAD TÉCNICA: Si se mencionan tecnologías específicas (versiones, librerías), deben aparecer en el reporte. No generalices (No digas "base de datos", di "PostgreSQL 15").
    3. IMPACTO VS RUIDO: Diferencia entre una "idea al aire" y un "acuerdo firme". Solo reporta lo que tenga impacto real en el proyecto.
    4. RATIONALE (El "Por Qué"): En las decisiones de arquitectura, intenta inferir o explícitar *por qué* se tomó esa decisión basado en el contexto (ej: "Se eligió Go por rendimiento", no solo "Se eligió Go").

    # FORMATO DE SALIDA (Markdown Estricto):

    # 🏛️ REPORTE MAESTRO DE INGENIERÍA: [TÍTULO/FECHA]

    ## 🎯 Resumen Ejecutivo (Visión 360°)
    (Un párrafo denso y narrativo. ¿Cuál fue el objetivo principal de la sesión? ¿Se logró? ¿Cuáles son los titulares más importantes? Ideal para lectura de C-Level).

    ## 🧩 Clusterización Técnica y Funcional
    *(Agrupa aquí todos los puntos discutidos en los segmentos anteriores. Si una categoría no aplica, omítela).*

    ### ⚙️ Backend & API Strategy
    * **Decisiones:** (Ej: Endpoints definidos, cambios en esquemas JSON, lógica de controladores).
    * **Stack:** (Lenguajes, librerías mencionadas).

    ### 🎨 Frontend & UX
    * **Componentes:** (Cambios en UI, flujos de usuario, validaciones en cliente).
    * **Integración:** (Consumo de servicios, manejo de estado).

    ### ☁️ Infraestructura & DevOps (Cloud/CI-CD)
    * **Entorno:** (Pipelines, Docker, Kubernetes, Variables de entorno).
    * **Seguridad/Rendimiento:** (Cualquier mención a Auth, latencia o escalabilidad).

    ### 💼 Reglas de Negocio & Producto
    * **Definiciones:** (Cambios en cómo funciona el producto de cara al usuario o negocio).

    ## 📋 Matriz de Acuerdos y Responsabilidades (Action Items)
    *(Tabla consolidada. Si una tarea se mencionó varias veces, unifícala en una sola fila).*

    | Tarea / Entregable | Responsable (Owner) | Prioridad | Estado/Notas |
    | :--- | :--- | :--- | :--- |
    | (Verbo de acción + Detalle) | (Nombre/Rol) | (Alta/Media/Baja) | (Fecha o Dependencia) |

    ## 🚨 Riesgos, Bloqueos y Deuda Técnica
    * **Bloqueo Crítico:** (Algo que impide avanzar AHORA).
    * **Riesgo Latente:** (Algo que podría fallar en el futuro).
    * **Deuda Técnica:** (Cosas que se decidieron hacer "rápido" pero que habrá que arreglar luego).

    ## 💡 Notas Adicionales del Arquitecto
    (Cualquier observación tuya como IA sobre la coherencia de la reunión, temas que quedaron inconclusos o sugerencias de seguimiento).
    """
    try:
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": full_minutes_text},
            ],
            temperature=0.4,
        )
        return response.choices[0].message.content
    except Exception as e:
        return f"Error Resumen: {str(e)}"


# === WORKER IA ===
def ai_worker(file_min, file_raw, initial_meeting_name=None):
    client = get_llm_client()
    all_minutes_text = []
    current_file_min = file_min
    current_file_raw = file_raw

    # Init Archivos
    meeting_title = initial_meeting_name or "Reunión"
    with open(current_file_raw, "w", encoding="utf-8") as f:
        f.write(f"# RAW DATA - {meeting_title} - {datetime.now()}\n\n")
    with open(current_file_min, "w", encoding="utf-8") as f:
        f.write(f"# BITÁCORA TÉCNICA - {meeting_title} - {datetime.now()}\n\n")

    gui_queue.put(("status", "🟢 Sistemas Listos. Escuchando..."))

    while not ai_stop_event.is_set() or not text_process_queue.empty():
        try:
            if state.is_shutting_down:
                q_size = text_process_queue.qsize()
                gui_queue.put(
                    ("status", f"🛑 Cierre: Procesando {q_size} bloques pendientes...")
                )

            payload_text = text_process_queue.get(timeout=0.5)
            ts = datetime.now().strftime("%H:%M")

            if not state.is_shutting_down:
                gui_queue.put(("status", f"⚡ Procesando bloque {ts}..."))

            # 1. RAW
            with open(current_file_raw, "a", encoding="utf-8") as f:
                f.write(f"\n{payload_text}\n")
                f.flush()
                os.fsync(f.fileno())

            # 2. IA
            minute_txt = process_smart_segment(client, payload_text)

            # Archivo
            formatted_entry = f"\n## ⏱️ {ts}\n{minute_txt}\n"
            all_minutes_text.append(formatted_entry)
            with open(current_file_min, "a", encoding="utf-8") as f:
                f.write(formatted_entry)
                f.flush()
                os.fsync(f.fileno())

            # GUI (LIFO)
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
            gui_queue.put(("status", f"Error IA: {e}"))

    # Resumen Final
    if all_minutes_text:
        full_text = "".join(all_minutes_text)
        summary = generate_final_summary(client, full_text)

        # Intentar generar nombre inteligente con IA
        gui_queue.put(("status", "🏷️ Generando nombre inteligente..."))
        ai_suggested_name = suggest_meeting_name_with_ai(client, full_text)

        if ai_suggested_name:
            gui_queue.put(("status", f"📝 Renombrando: {ai_suggested_name}"))
            current_file_raw, current_file_min = rename_meeting_files(
                current_file_raw, current_file_min, ai_suggested_name
            )

        # Reescribir archivo con resumen al inicio
        gui_queue.put(("status", "💾 Reorganizando y Guardando..."))
        meeting_title = initial_meeting_name or ai_suggested_name or "Reunión"

        final_content = f"# 📋 MINUTA: {meeting_title}\n"
        final_content += f"**Fecha:** {datetime.now().strftime('%Y-%m-%d %H:%M')}\n\n"
        final_content += "=" * 60 + "\n"
        final_content += "# 🎯 RESUMEN EJECUTIVO\n"
        final_content += "=" * 60 + "\n\n"
        final_content += summary
        final_content += "\n\n"
        final_content += "=" * 60 + "\n"
        final_content += "# 📝 BITÁCORA DETALLADA (Cronológica)\n"
        final_content += "=" * 60 + "\n"
        final_content += full_text

        with open(current_file_min, "w", encoding="utf-8") as f:
            f.write(final_content)
            f.flush()
            os.fsync(f.fileno())
        gui_queue.put(("status", f"✅ Guardado: {os.path.basename(current_file_min)}"))
    else:
        gui_queue.put(("status", "⚠️ Finalizado sin datos."))

    gui_queue.put(("shutdown_complete", True))


# === WORKER CAPTURA ===
def capture_worker(translator):
    def on_smart_block(payload):
        text_process_queue.put(payload)

    def on_live_feed(text_buffer):
        gui_queue.put(("live", text_buffer))
        try:
            if len(text_buffer) > 2:
                trans = translator.translate_text(text_buffer[-600:])
                gui_queue.put(("trans", trans))
        except:
            pass

    state.source_name = "Teams Capture"
    tsc.start_headless_capture(on_smart_block, on_live_feed, capture_stop_event)


# === GUI CONFIG ===
def ask_config_gui():
    config_win = tk.Tk()
    config_win.title("Configuración")
    config_win.geometry("300x150")
    config_win.configure(bg=COLORS["bg_main"])

    # Centrar en pantalla
    config_win.eval("tk::PlaceWindow . center")

    selection = {"source": "es", "target": "en"}

    tk.Label(
        config_win,
        text="Idioma de la Reunión:",
        bg=COLORS["bg_main"],
        fg="white",
        font=("Segoe UI", 11),
    ).pack(pady=15)

    def set_es():
        selection["source"], selection["target"] = "es", "en"
        config_win.destroy()

    def set_en():
        selection["source"], selection["target"] = "en", "es"
        config_win.destroy()

    btn_style = {
        "bg": COLORS["fg_accent"],
        "fg": "white",
        "font": ("Segoe UI", 10, "bold"),
        "bd": 0,
        "padx": 20,
        "pady": 5,
        "cursor": "hand2",
    }

    tk.Button(config_win, text="🇪🇸 ESPAÑOL", command=set_es, **btn_style).pack(pady=5)
    tk.Button(config_win, text="🇺🇸 INGLÉS", command=set_en, **btn_style).pack(pady=5)

    config_win.mainloop()
    return selection["source"], selection["target"]


# === GUI APP PRINCIPAL ===
class MeetCopilotApp(tk.Tk):
    def __init__(self, source_lang, target_lang):
        super().__init__()

        self.title("AI Meeting Architect | Pro Edition")
        self.geometry("1100x750")
        self.configure(bg=COLORS["bg_main"])
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Configurar Grid
        self.columnconfigure(0, weight=6)  # 60%
        self.columnconfigure(1, weight=4)  # 40%
        self.rowconfigure(1, weight=1)  # Alto dinámico

        # 1. HEADER
        self.header_var = tk.StringVar(value="Iniciando motores...")
        header_frame = tk.Frame(self, bg=COLORS["fg_accent"], height=35)
        header_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        header_frame.pack_propagate(False)

        lbl_header = tk.Label(
            header_frame,
            textvariable=self.header_var,
            bg=COLORS["fg_accent"],
            fg="white",
            font=("Segoe UI", 11, "bold"),
        )
        lbl_header.pack(expand=True)

        # 2. COLUMNA IZQUIERDA
        left_frame = tk.Frame(self, bg=COLORS["bg_main"])
        left_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        left_frame.rowconfigure(1, weight=1)
        left_frame.rowconfigure(3, weight=1)
        left_frame.columnconfigure(0, weight=1)

        self.create_label(left_frame, "🔊 AUDIO EN VIVO", COLORS["fg_live"], 0)
        self.txt_live = self.create_text_area(left_frame, COLORS["fg_live"], 1)

        self.create_label(
            left_frame, f"🌐 TRADUCCIÓN ({target_lang.upper()})", COLORS["fg_trans"], 2
        )
        self.txt_trans = self.create_text_area(left_frame, COLORS["fg_trans"], 3)

        # 3. COLUMNA DERECHA
        right_frame = tk.Frame(self, bg=COLORS["bg_main"])
        right_frame.grid(row=1, column=1, sticky="nsew", padx=(0, 10), pady=10)
        right_frame.rowconfigure(1, weight=1)
        right_frame.columnconfigure(0, weight=1)

        self.create_label(right_frame, "🤖 BITÁCORA TÉCNICA (LIFO)", COLORS["fg_ai"], 0)
        self.txt_ai = self.create_text_area(right_frame, COLORS["fg_ai"], 1)

        # 4. FOOTER
        self.log_var = tk.StringVar(value="Esperando eventos...")
        lbl_log = tk.Label(
            self,
            textvariable=self.log_var,
            bg="#333333",
            fg="#aaaaaa",
            font=("Consolas", 9),
            anchor="w",
            padx=10,
        )
        lbl_log.grid(row=2, column=0, columnspan=2, sticky="ew")

        self.check_queue()

    def create_label(self, parent, text, color, row):
        lbl = tk.Label(
            parent,
            text=text,
            bg=COLORS["bg_main"],
            fg=color,
            font=("Segoe UI", 10, "bold"),
            anchor="w",
        )
        lbl.grid(row=row, column=0, sticky="ew", pady=(5, 0))

    def create_text_area(self, parent, text_color, row):
        txt = scrolledtext.ScrolledText(
            parent,
            bg=COLORS["bg_panel"],
            fg=text_color,
            insertbackground="white",
            font=("Consolas", 11),
            borderwidth=0,
            wrap=tk.WORD,
            highlightthickness=1,
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["fg_accent"],
        )
        txt.grid(row=row, column=0, sticky="nsew", pady=(2, 5))
        return txt

    def check_queue(self):
        try:
            while True:
                action, data = gui_queue.get_nowait()

                if action == "live":
                    self.txt_live.delete("1.0", tk.END)
                    self.txt_live.insert(tk.END, data)
                    self.txt_live.see(tk.END)

                elif action == "trans":
                    self.txt_trans.delete("1.0", tk.END)
                    self.txt_trans.insert(tk.END, data)
                    self.txt_trans.see(tk.END)

                elif action == "ai_new":
                    self.txt_ai.insert("1.0", data + "\n")

                elif action == "status":
                    self.header_var.set(data)

                elif action == "shutdown_complete":
                    self.destroy()

        except queue.Empty:
            pass

        delay = 50 if state.is_shutting_down else 100
        self.after(delay, self.check_queue)

    def on_close(self):
        if state.is_shutting_down:
            return

        if messagebox.askokcancel(
            "Finalizar Reunión", "¿Desea detener la captura y generar el resumen final?"
        ):
            state.is_shutting_down = True
            self.header_var.set("🛑 DETENIENDO... (VACIANDO MEMORIA)")
            threading.Thread(target=perform_shutdown_sequence).start()


def perform_shutdown_sequence():
    capture_stop_event.set()
    ai_stop_event.set()


# === MAIN ENTRY POINT ===
def main():
    s_lang, t_lang = ask_config_gui()

    state.source_lang = s_lang
    state.target_lang = t_lang

    translator = rt.RealTimeTranslator(state.source_lang, state.target_lang)

    # Intentar obtener nombre de la reunión desde Teams
    initial_meeting_name = None
    try:
        teams_window_title = tsc.get_meeting_name()
        if teams_window_title:
            initial_meeting_name = extract_meeting_name_from_window(teams_window_title)
    except Exception:
        pass

    file_raw = generate_filename("RAW", "txt", initial_meeting_name)
    file_min = generate_filename("MINUTA", "md", initial_meeting_name)

    t_ai = threading.Thread(
        target=ai_worker, args=(file_min, file_raw, initial_meeting_name), daemon=True
    )
    t_capture = threading.Thread(target=capture_worker, args=(translator,), daemon=True)

    t_ai.start()
    t_capture.start()

    app = MeetCopilotApp(s_lang, t_lang)
    app.mainloop()


def hide_console():
    """Oculta la ventana de consola en Windows."""
    """Oculta la ventana de consola en Windows. En otros sistemas operativos no hace nada."""

    if sys.platform == "win32":
        import ctypes

        # SW_HIDE = 0
        ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)


if __name__ == "__main__":
    hide_console()
    main()
