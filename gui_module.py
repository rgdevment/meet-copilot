"""
Módulo de interfaz gráfica para la aplicación de transcripción de reuniones.
Proporciona ventanas y componentes visuales para la interacción con el usuario.
"""

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
    """Aplicación principal de UI para transcripción y análisis de reuniones"""

    def __init__(self, source_lang, target_lang, gui_queue, state, perform_shutdown_callback):
        super().__init__()

        self.gui_queue = gui_queue
        self.state = state
        self.perform_shutdown_callback = perform_shutdown_callback

        self.title("AI Meeting Architect | Pro Edition")
        self.geometry("1100x750")
        self.configure(bg=COLORS["bg_main"])
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        self.columnconfigure(0, weight=6)
        self.columnconfigure(1, weight=4)
        self.rowconfigure(1, weight=1)

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

        right_frame = tk.Frame(self, bg=COLORS["bg_main"])
        right_frame.grid(row=1, column=1, sticky="nsew", padx=(0, 10), pady=10)
        right_frame.rowconfigure(1, weight=1)
        right_frame.columnconfigure(0, weight=1)

        self.create_label(right_frame, "🤖 BITÁCORA TÉCNICA (LIFO)", COLORS["fg_ai"], 0)
        self.txt_ai = self.create_text_area(right_frame, COLORS["fg_ai"], 1)

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
                action, data = self.gui_queue.get_nowait()

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

        delay = 50 if self.state.is_shutting_down else 100
        self.after(delay, self.check_queue)

    def on_close(self):
        if self.state.is_shutting_down:
            return

        if messagebox.askokcancel(
            "Finalizar Reunión", "¿Desea detener la captura y generar el resumen final?"
        ):
            self.state.is_shutting_down = True
            self.header_var.set("🛑 DETENIENDO... (VACIANDO MEMORIA)")
            threading.Thread(target=self.perform_shutdown_callback).start()
