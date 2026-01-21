import queue
import threading
import tkinter as tk
from tkinter import messagebox, scrolledtext

COLORS = {
    "bg_main": "#1e1e1e",
    "bg_panel": "#252526",
    "fg_text": "#d4d4d4",
    "fg_accent": "#007acc",
    "fg_live": "#4ec9b0",
    "fg_trans": "#ce9178",
    "fg_ai": "#9cdcfe",
    "fg_dim": "#858585",
    "border": "#3e3e42",
    "led_on": "#2ecc71",
    "led_off": "#e74c3c",
    "led_process": "#3498db",
}


def ask_config_gui():
    """Ventana modal de configuración inicial de idiomas"""
    config_win = tk.Tk()
    config_win.title("Configuración")
    config_win.geometry("300x150")
    config_win.configure(bg=COLORS["bg_main"])
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


class MeetCopilotApp(tk.Tk):
    def __init__(
        self,
        source_lang,
        target_lang,
        gui_queue,
        state,
        translator,
        perform_shutdown_callback,
    ):
        super().__init__()

        self.gui_queue = gui_queue
        self.state = state
        self.translator = translator
        self.perform_shutdown_callback = perform_shutdown_callback
        self.auto_scroll = tk.BooleanVar(value=True)

        self.title("AI Meeting Architect | Pro Edition")
        self.geometry("1150x800")
        self.configure(bg=COLORS["bg_main"])
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.columnconfigure(0, weight=6)
        self.columnconfigure(1, weight=4)
        self.rowconfigure(1, weight=1)

        # --- 1. HEADER & LANGUAGE SWAP ---
        header_frame = tk.Frame(self, bg=COLORS["fg_accent"], height=45)
        header_frame.grid(row=0, column=0, columnspan=2, sticky="ew")
        header_frame.pack_propagate(False)

        self.header_var = tk.StringVar(value="Sistemas Listos")
        lbl_header = tk.Label(
            header_frame,
            textvariable=self.header_var,
            bg=COLORS["fg_accent"],
            fg="white",
            font=("Segoe UI", 12, "bold"),
        )
        lbl_header.pack(side="left", padx=20)

        # Botón visual de cambio de idioma (Mixed Meetings)
        self.lang_btn_var = tk.StringVar(
            value=f"🔄 MODO: {source_lang.upper()} ➔ {target_lang.upper()}"
        )
        btn_swap = tk.Button(
            header_frame,
            textvariable=self.lang_btn_var,
            command=self.toggle_language,
            bg="#34495e",
            fg="white",
            font=("Segoe UI", 9, "bold"),
            bd=0,
            padx=15,
            cursor="hand2",
        )
        btn_swap.pack(side="right", padx=10, pady=8)

        # --- 2. COLUMNA IZQUIERDA (Audio & Trans) ---
        left_frame = tk.Frame(self, bg=COLORS["bg_main"])
        left_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=10)
        left_frame.rowconfigure(1, weight=1)
        left_frame.rowconfigure(3, weight=1)
        left_frame.columnconfigure(0, weight=1)

        # Panel Audio
        self.create_section_header(
            left_frame, "🔊 AUDIO EN VIVO", COLORS["fg_live"], 0, self.copy_live
        )
        self.txt_live = self.create_text_area(left_frame, COLORS["fg_live"], 1)

        # Panel Traducción
        self.trans_label_var = tk.StringVar(
            value=f"🌐 TRADUCCIÓN ({target_lang.upper()})"
        )
        self.create_section_header(
            left_frame, self.trans_label_var, COLORS["fg_trans"], 2, self.copy_trans
        )
        self.txt_trans = self.create_text_area(left_frame, COLORS["fg_trans"], 3)

        # --- 3. COLUMNA DERECHA (AI) ---
        right_frame = tk.Frame(self, bg=COLORS["bg_main"])
        right_frame.grid(row=1, column=1, sticky="nsew", padx=(0, 10), pady=10)
        right_frame.rowconfigure(1, weight=1)
        right_frame.columnconfigure(0, weight=1)

        self.create_section_header(
            right_frame, "🤖 BITÁCORA TÉCNICA (LIFO)", COLORS["fg_ai"], 0, self.copy_ai
        )
        self.txt_ai = self.create_text_area(right_frame, COLORS["fg_ai"], 1)

        # --- 4. FOOTER & STATUS LEDS ---
        footer_frame = tk.Frame(self, bg="#333333", height=30)
        footer_frame.grid(row=2, column=0, columnspan=2, sticky="ew")

        self.log_var = tk.StringVar(value="Esperando eventos...")
        tk.Label(
            footer_frame,
            textvariable=self.log_var,
            bg="#333333",
            fg="#aaaaaa",
            font=("Consolas", 9),
            anchor="w",
        ).pack(side="left", padx=10)

        # Visual Status LEDs
        self.led_sensor = self.create_led(footer_frame, "SENSOR")
        self.led_trans = self.create_led(footer_frame, "TRANS")
        self.led_ai = self.create_led(footer_frame, "AI")

        # Checkbox visual para Auto-Scroll
        tk.Checkbutton(
            footer_frame,
            text="Auto-Scroll",
            variable=self.auto_scroll,
            bg="#333333",
            fg="white",
            selectcolor="#1e1e1e",
            activebackground="#333333",
            font=("Segoe UI", 8),
        ).pack(side="right", padx=10)

        self.check_queue()

    def create_section_header(self, parent, text_or_var, color, row, copy_func):
        """Crea un encabezado de sección con botones de utilidad."""
        frame = tk.Frame(parent, bg=COLORS["bg_main"])
        frame.grid(row=row, column=0, sticky="ew", pady=(5, 0))

        if isinstance(text_or_var, tk.StringVar):
            lbl = tk.Label(
                frame,
                textvariable=text_or_var,
                bg=COLORS["bg_main"],
                fg=color,
                font=("Segoe UI", 10, "bold"),
            )
        else:
            lbl = tk.Label(
                frame,
                text=text_or_var,
                bg=COLORS["bg_main"],
                fg=color,
                font=("Segoe UI", 10, "bold"),
            )
        lbl.pack(side="left")

        # Botones Visuales
        tk.Button(
            frame,
            text="📋",
            command=copy_func,
            bg=COLORS["bg_main"],
            fg=color,
            bd=0,
            cursor="hand2",
        ).pack(side="right", padx=5)
        tk.Button(
            frame,
            text="🧹",
            command=lambda: self.clear_panel(row),
            bg=COLORS["bg_main"],
            fg=color,
            bd=0,
            cursor="hand2",
        ).pack(side="right")

    def create_led(self, parent, label):
        """Crea un indicador LED visual."""
        frame = tk.Frame(parent, bg="#333333")
        frame.pack(side="right", padx=5)
        tk.Label(
            frame, text=label, bg="#333333", fg="#888888", font=("Consolas", 8)
        ).pack(side="left")
        canvas = tk.Canvas(
            frame, width=10, height=10, bg="#333333", highlightthickness=0
        )
        canvas.pack(side="left", padx=2)
        led = canvas.create_oval(2, 2, 9, 9, fill=COLORS["border"])
        return (canvas, led)

    def update_led(self, led_tuple, status):
        canvas, led = led_tuple
        color = COLORS["led_on"] if status else COLORS["border"]
        canvas.itemconfig(led, fill=color)

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

    def toggle_language(self):
        """Alterna idiomas para reuniones mixtas sin detener la IA."""
        old_s, old_t = self.state.source_lang, self.state.target_lang
        self.state.source_lang, self.state.target_lang = old_t, old_s

        # Actualizar traductor
        self.translator.source = self.state.source_lang
        self.translator.target = self.state.target_lang
        self.translator.translator.source = self.state.source_lang
        self.translator.translator.target = self.state.target_lang

        # Actualizar UI
        self.lang_btn_var.set(
            f"🔄 MODO: {self.state.source_lang.upper()} ➔ {self.state.target_lang.upper()}"
        )
        self.trans_label_var.set(f"🌐 TRADUCCIÓN ({self.state.target_lang.upper()})")
        self.header_var.set(f"Cambiado a escucha en {self.state.source_lang.upper()}")

    def copy_live(self):
        self.clipboard_clear()
        self.clipboard_append(self.txt_live.get("1.0", tk.END))

    def copy_trans(self):
        self.clipboard_clear()
        self.clipboard_append(self.txt_trans.get("1.0", tk.END))

    def copy_ai(self):
        self.clipboard_clear()
        self.clipboard_append(self.txt_ai.get("1.0", tk.END))

    def clear_panel(self, row):
        if row == 0:
            self.txt_live.delete("1.0", tk.END)
        elif row == 2:
            self.txt_trans.delete("1.0", tk.END)
        else:
            self.txt_ai.delete("1.0", tk.END)

    def check_queue(self):
        try:
            while True:
                action, data = self.gui_queue.get_nowait()
                if action == "live":
                    self.update_led(self.led_sensor, True)
                    self.txt_live.delete("1.0", tk.END)
                    self.txt_live.insert(tk.END, data)
                    if self.auto_scroll.get():
                        self.txt_live.see(tk.END)

                elif action == "trans":
                    self.update_led(self.led_trans, True)
                    self.txt_trans.delete("1.0", tk.END)
                    self.txt_trans.insert(tk.END, data)
                    if self.auto_scroll.get():
                        self.txt_trans.see(tk.END)

                elif action == "ai_new":
                    self.update_led(self.led_ai, True)
                    self.txt_ai.insert("1.0", data + "\n")
                    self.after(1000, lambda: self.update_led(self.led_ai, False))

                elif action == "status":
                    self.header_var.set(data)

                elif action == "shutdown_complete":
                    self.destroy()
        except queue.Empty:
            pass
        self.after(100, self.check_queue)

    def on_close(self):
        if self.state.is_shutting_down:
            return
        if messagebox.askokcancel("Finalizar", "¿Desea generar el resumen final?"):
            self.state.is_shutting_down = True
            threading.Thread(target=self.perform_shutdown_callback).start()
