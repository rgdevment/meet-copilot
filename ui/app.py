import os
import queue
import threading
import tkinter as tk

import customtkinter as ctk

from config import AppConfig

COLORS = {
    "bg_main": "#1a1a2e",
    "bg_panel": "#16213e",
    "bg_header": "#0f3460",
    "fg_live": "#4ecca3",
    "fg_trans": "#e8a87c",
    "fg_ai": "#95e1d3",
    "fg_dim": "#858585",
    "accent": "#e94560",
    "border": "#2a2a4a",
    "led_on": "#2ecc71",
    "led_off": "#555555",
}


class MeetingApp(ctk.CTk):
    def __init__(
        self,
        config: AppConfig,
        gui_queue: queue.Queue,
        translator,
        shutdown_callback,
    ):
        super().__init__()
        self.config = config
        self.gui_queue = gui_queue
        self.translator = translator
        self.shutdown_callback = shutdown_callback
        self._is_shutting_down = False
        self.on_note_callback = None

        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self.title("Meeting Copilot")
        self.geometry("1200x850")
        self.minsize(900, 600)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

        self._build_ui()
        self._poll_queue()

    def _build_ui(self):
        # Header
        header = ctk.CTkFrame(self, height=50, corner_radius=0, fg_color=COLORS["bg_header"])
        header.pack(fill="x")
        header.pack_propagate(False)

        self.status_label = ctk.CTkLabel(
            header,
            text="Waiting for captions...",
            font=ctk.CTkFont(size=13, weight="bold"),
        )
        self.status_label.pack(side="left", padx=20)

        provider_text = f"{self.config.ai_provider.upper()} | {self.config.model_name}"
        ctk.CTkLabel(
            header,
            text=provider_text,
            font=ctk.CTkFont(size=11),
            text_color="gray",
        ).pack(side="right", padx=20)

        self.lang_btn = ctk.CTkButton(
            header,
            text=f"🔄 {self.config.source_lang.upper()} → {self.config.target_lang.upper()}",
            width=130,
            height=30,
            command=self._toggle_language,
        )
        self.lang_btn.pack(side="right", padx=10)

        self.diag_btn = ctk.CTkButton(
            header, text="🩺", width=36, height=30, command=self._dump_uia
        )
        self.diag_btn.pack(side="right", padx=4)

        # Context bar (topic display + quick note input)
        ctx_bar = ctk.CTkFrame(self, height=36, corner_radius=0, fg_color="#1e1e3a")
        ctx_bar.pack(fill="x")
        ctx_bar.pack_propagate(False)

        self.topic_label = ctk.CTkLabel(
            ctx_bar, text="📌 Topic: detecting...",
            font=ctk.CTkFont(size=11), text_color="#777",
        )
        self.topic_label.pack(side="left", padx=12)

        note_btn = ctk.CTkButton(
            ctx_bar, text="+", width=30, height=26, font=ctk.CTkFont(size=13, weight="bold"),
            command=self._on_add_note,
        )
        note_btn.pack(side="right", padx=(0, 10))

        self.note_entry = ctk.CTkEntry(
            ctx_bar, placeholder_text="Add context note (project terms, corrections...)",
            height=26, font=ctk.CTkFont(size=11),
        )
        self.note_entry.pack(side="right", fill="x", expand=True, padx=(10, 4))
        self.note_entry.bind("<Return>", lambda e: self._on_add_note())

        # Main content
        content = ctk.CTkFrame(self, fg_color="transparent")
        content.pack(fill="both", expand=True, padx=10, pady=10)
        content.columnconfigure(0, weight=6)
        content.columnconfigure(1, weight=4)
        content.rowconfigure(0, weight=1)

        # Left column
        left = ctk.CTkFrame(content, fg_color="transparent")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 5))
        left.rowconfigure(0, weight=1)
        left.rowconfigure(1, weight=1)
        left.columnconfigure(0, weight=1)

        # Live panel
        live_frame = ctk.CTkFrame(left, fg_color=COLORS["bg_panel"])
        live_frame.grid(row=0, column=0, sticky="nsew", pady=(0, 5))
        live_frame.rowconfigure(1, weight=1)
        live_frame.columnconfigure(0, weight=1)

        live_header = ctk.CTkFrame(live_frame, fg_color="transparent", height=30)
        live_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
        ctk.CTkLabel(
            live_header,
            text="🔊 LIVE CAPTIONS",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["fg_live"],
        ).pack(side="left")
        ctk.CTkButton(
            live_header, text="📋", width=28, height=28, command=self._copy_live
        ).pack(side="right", padx=2)
        ctk.CTkButton(
            live_header, text="🧹", width=28, height=28, command=lambda: self._clear("live")
        ).pack(side="right", padx=2)

        self.txt_live = ctk.CTkTextbox(
            live_frame,
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=COLORS["fg_live"],
            fg_color=COLORS["bg_main"],
            wrap="word",
        )
        self.txt_live.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))

        # Translation panel
        trans_frame = ctk.CTkFrame(left, fg_color=COLORS["bg_panel"])
        trans_frame.grid(row=1, column=0, sticky="nsew", pady=(5, 0))
        trans_frame.rowconfigure(1, weight=1)
        trans_frame.columnconfigure(0, weight=1)

        trans_header = ctk.CTkFrame(trans_frame, fg_color="transparent", height=30)
        trans_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
        self.trans_title = ctk.CTkLabel(
            trans_header,
            text=f"🌐 TRANSLATION ({self.config.target_lang.upper()})",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["fg_trans"],
        )
        self.trans_title.pack(side="left")
        ctk.CTkButton(
            trans_header, text="📋", width=28, height=28, command=self._copy_trans
        ).pack(side="right", padx=2)
        ctk.CTkButton(
            trans_header, text="🧹", width=28, height=28, command=lambda: self._clear("trans")
        ).pack(side="right", padx=2)

        self.txt_trans = ctk.CTkTextbox(
            trans_frame,
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=COLORS["fg_trans"],
            fg_color=COLORS["bg_main"],
            wrap="word",
        )
        self.txt_trans.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))

        # Right column - AI Log
        ai_frame = ctk.CTkFrame(content, fg_color=COLORS["bg_panel"])
        ai_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0))
        ai_frame.rowconfigure(1, weight=1)
        ai_frame.columnconfigure(0, weight=1)

        ai_header = ctk.CTkFrame(ai_frame, fg_color="transparent", height=30)
        ai_header.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 0))
        ctk.CTkLabel(
            ai_header,
            text="🤖 AI TECHNICAL LOG",
            font=ctk.CTkFont(size=12, weight="bold"),
            text_color=COLORS["fg_ai"],
        ).pack(side="left")
        ctk.CTkButton(
            ai_header, text="📋", width=28, height=28, command=self._copy_ai
        ).pack(side="right", padx=2)
        ctk.CTkButton(
            ai_header, text="🧹", width=28, height=28, command=lambda: self._clear("ai")
        ).pack(side="right", padx=2)

        self.txt_ai = ctk.CTkTextbox(
            ai_frame,
            font=ctk.CTkFont(family="Consolas", size=12),
            text_color=COLORS["fg_ai"],
            fg_color=COLORS["bg_main"],
            wrap="word",
        )
        self.txt_ai.grid(row=1, column=0, sticky="nsew", padx=8, pady=(4, 8))

        # Footer
        footer = ctk.CTkFrame(self, height=35, corner_radius=0, fg_color="#2a2a2a")
        footer.pack(fill="x")
        footer.pack_propagate(False)

        self.footer_label = ctk.CTkLabel(
            footer,
            text="Waiting for events...",
            font=ctk.CTkFont(family="Consolas", size=10),
            text_color="#888888",
        )
        self.footer_label.pack(side="left", padx=10)

        self.led_sensor = self._create_led(footer, "CAPTURE")
        self.led_trans = self._create_led(footer, "TRANS")
        self.led_ai = self._create_led(footer, "AI")

        self.scroll_switch = ctk.CTkSwitch(
            footer, text="Auto-Scroll", onvalue=True, offvalue=False
        )
        self.scroll_switch.select()
        self.scroll_switch.pack(side="right", padx=10)

    def _create_led(self, parent, label: str):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        frame.pack(side="right", padx=6)
        ctk.CTkLabel(
            frame,
            text=label,
            font=ctk.CTkFont(family="Consolas", size=9),
            text_color="#666666",
        ).pack(side="left", padx=2)
        canvas = tk.Canvas(frame, width=10, height=10, bg="#2a2a2a", highlightthickness=0)
        canvas.pack(side="left")
        led = canvas.create_oval(1, 1, 9, 9, fill=COLORS["led_off"])
        return canvas, led

    def _set_led(self, led_tuple, on: bool):
        canvas, led = led_tuple
        canvas.itemconfig(led, fill=COLORS["led_on"] if on else COLORS["led_off"])

    def _toggle_language(self):
        self.config.source_lang, self.config.target_lang = (
            self.config.target_lang,
            self.config.source_lang,
        )
        if self.translator:
            self.translator.swap_languages()
        self.lang_btn.configure(
            text=f"🔄 {self.config.source_lang.upper()} → {self.config.target_lang.upper()}"
        )
        self.trans_title.configure(
            text=f"🌐 TRANSLATION ({self.config.target_lang.upper()})"
        )
        self.status_label.configure(
            text=f"Switched to {self.config.source_lang.upper()} listening"
        )

    def _copy_live(self):
        self.clipboard_clear()
        self.clipboard_append(self.txt_live.get("1.0", "end"))

    def _copy_trans(self):
        self.clipboard_clear()
        self.clipboard_append(self.txt_trans.get("1.0", "end"))

    def _copy_ai(self):
        self.clipboard_clear()
        self.clipboard_append(self.txt_ai.get("1.0", "end"))

    def _clear(self, panel: str):
        target = {"live": self.txt_live, "trans": self.txt_trans, "ai": self.txt_ai}
        widget = target.get(panel)
        if widget:
            widget.delete("1.0", "end")

    def _dump_uia(self):
        from capture.diagnostics import dump_uia_tree

        diag_dir = os.path.join(self.config.output_dir, "_diag")
        self.status_label.configure(text="Generando dump UIA...")

        def work():
            path = dump_uia_tree(diag_dir)
            if path:
                self.gui_queue.put(("status", f"Dump UIA: {os.path.basename(path)}"))
                try:
                    os.startfile(os.path.dirname(path))
                except Exception:
                    pass
            else:
                self.gui_queue.put(("status", "Dump UIA falló (revisa logs)"))

        threading.Thread(target=work, daemon=True).start()

    def _on_add_note(self):
        note = self.note_entry.get().strip()
        if note and self.on_note_callback:
            self.on_note_callback(note)
            self.note_entry.delete(0, "end")
            self.topic_label.configure(text=f"📌 Note added: {note[:60]}")

    def _poll_queue(self):
        if self._is_shutting_down:
            return
        try:
            while True:
                action, data = self.gui_queue.get_nowait()

                if action == "live":
                    self._set_led(self.led_sensor, True)
                    self.txt_live.delete("1.0", "end")
                    self.txt_live.insert("end", data)
                    if self.scroll_switch.get():
                        self.txt_live.see("end")

                elif action == "trans":
                    self._set_led(self.led_trans, True)
                    self.txt_trans.delete("1.0", "end")
                    self.txt_trans.insert("end", data)
                    if self.scroll_switch.get():
                        self.txt_trans.see("end")

                elif action == "ai_new":
                    self._set_led(self.led_ai, True)
                    self.txt_ai.insert("1.0", data + "\n")
                    self.after(1000, lambda: self._set_led(self.led_ai, False))

                elif action == "topic":
                    self.topic_label.configure(text=f"📌 {data}")

                elif action == "status":
                    self.status_label.configure(text=data)

                elif action == "shutdown_complete":
                    if data and os.path.isfile(data):
                        os.startfile(data)
                    self._safe_destroy()
                    return

        except queue.Empty:
            pass
        if not self._is_shutting_down:
            self.after(100, self._poll_queue)

    def _safe_destroy(self):
        try:
            for after_id in self.tk.call("after", "info"):
                self.after_cancel(after_id)
        except Exception:
            pass
        try:
            self.destroy()
        except Exception:
            pass

    def _on_close(self):
        if self._is_shutting_down:
            return

        dialog = ctk.CTkToplevel(self)
        dialog.title("End Meeting")
        dialog.geometry("350x150")
        dialog.transient(self)
        dialog.grab_set()

        # Center on parent
        dialog.update_idletasks()
        x = self.winfo_x() + (self.winfo_width() // 2) - 175
        y = self.winfo_y() + (self.winfo_height() // 2) - 75
        dialog.geometry(f"+{x}+{y}")

        ctk.CTkLabel(
            dialog,
            text="Generate final summary and close?",
            font=ctk.CTkFont(size=14),
        ).pack(pady=20)

        btn_frame = ctk.CTkFrame(dialog, fg_color="transparent")
        btn_frame.pack(pady=10)

        def confirm():
            dialog.destroy()
            self._is_shutting_down = True
            threading.Thread(target=self.shutdown_callback, daemon=True).start()

        def cancel():
            dialog.destroy()

        ctk.CTkButton(btn_frame, text="Generate & Close", command=confirm, width=140).pack(
            side="left", padx=10
        )
        ctk.CTkButton(
            btn_frame,
            text="Cancel",
            command=cancel,
            width=100,
            fg_color="gray",
            hover_color="darkgray",
        ).pack(side="right", padx=10)
