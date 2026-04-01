import os

import customtkinter as ctk

from config import PLATFORM_REGISTRY, PROVIDER_REGISTRY, AppConfig

LANGUAGES = {
    "es": "Español",
    "en": "English",
    "pt": "Português",
    "fr": "Français",
}


class ConfigDialog(ctk.CTk):
    def __init__(self, config: AppConfig):
        super().__init__()
        self.config = config
        self.result: AppConfig | None = None
        self._current_provider_key = config.ai_provider

        self.title("Meeting Copilot - Setup")
        self.geometry("500x520")
        self.resizable(False, False)
        ctk.set_appearance_mode("dark")
        ctk.set_default_color_theme("blue")

        self._build_ui()
        self._center_window()

    def _center_window(self):
        self.update_idletasks()
        w = self.winfo_width()
        h = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (w // 2)
        y = (self.winfo_screenheight() // 2) - (h // 2)
        self.geometry(f"+{x}+{y}")

    def _build_ui(self):
        main = ctk.CTkFrame(self, fg_color="transparent")
        main.pack(fill="both", expand=True, padx=25, pady=15)

        ctk.CTkLabel(
            main,
            text="Meeting Copilot",
            font=ctk.CTkFont(size=24, weight="bold"),
        ).pack(pady=(0, 2))
        ctk.CTkLabel(
            main,
            text="Configure your meeting capture settings",
            font=ctk.CTkFont(size=12),
            text_color="gray",
        ).pack(pady=(0, 15))

        # --- Platform ---
        ctk.CTkLabel(main, text="Meeting Platform", font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        platform_names = list(PLATFORM_REGISTRY.values())
        platform_keys = list(PLATFORM_REGISTRY.keys())
        current_idx = platform_keys.index(self.config.platform) if self.config.platform in platform_keys else 0
        self.platform_var = ctk.StringVar(value=platform_names[current_idx])
        ctk.CTkOptionMenu(main, variable=self.platform_var, values=platform_names, width=430).pack(
            pady=(2, 10), fill="x"
        )

        # --- AI Provider ---
        ctk.CTkLabel(main, text="AI Provider", font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        provider_names = [PROVIDER_REGISTRY[k]["name"] for k in PROVIDER_REGISTRY]
        provider_keys = list(PROVIDER_REGISTRY.keys())
        current_p_idx = provider_keys.index(self.config.ai_provider) if self.config.ai_provider in provider_keys else 0
        self.provider_var = ctk.StringVar(value=provider_names[current_p_idx])
        ctk.CTkOptionMenu(
            main, variable=self.provider_var, values=provider_names, width=430,
            command=self._on_provider_change,
        ).pack(pady=(2, 10), fill="x")

        # --- API Key section ---
        self.key_section = ctk.CTkFrame(main, fg_color="transparent")
        self.key_label = ctk.CTkLabel(self.key_section, text="API Key", font=ctk.CTkFont(weight="bold"))
        self.key_label.pack(anchor="w")
        self.key_entry = ctk.CTkEntry(self.key_section, placeholder_text="sk-... or env variable", show="•")
        self.key_entry.pack(pady=(2, 10), fill="x")
        saved_key = self.config.api_keys.get(self.config.ai_provider, "")
        if saved_key:
            self.key_entry.insert(0, saved_key)

        # --- Model ---
        self.model_label = ctk.CTkLabel(main, text="Model", font=ctk.CTkFont(weight="bold"))
        self.model_label.pack(anchor="w")
        self.model_var = ctk.StringVar(value=self.config.model_name)
        self.model_menu = ctk.CTkOptionMenu(main, variable=self.model_var, values=self._get_models(), width=430)
        self.model_menu.pack(pady=(2, 10), fill="x")

        # --- LM Studio URL section ---
        self.url_section = ctk.CTkFrame(main, fg_color="transparent")
        self.url_label = ctk.CTkLabel(self.url_section, text="LM Studio URL", font=ctk.CTkFont(weight="bold"))
        self.url_label.pack(anchor="w")
        self.url_entry = ctk.CTkEntry(self.url_section, placeholder_text="http://localhost:1234/v1")
        self.url_entry.pack(pady=(2, 10), fill="x")
        self.url_entry.insert(0, self.config.api_base_url)

        # --- Languages ---
        lang_frame = ctk.CTkFrame(main, fg_color="transparent")
        lang_frame.pack(fill="x", pady=(5, 10))

        left = ctk.CTkFrame(lang_frame, fg_color="transparent")
        left.pack(side="left", expand=True, fill="x", padx=(0, 5))
        ctk.CTkLabel(left, text="Meeting Language", font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        lang_display = [LANGUAGES[k] for k in LANGUAGES]
        lang_keys = list(LANGUAGES.keys())
        src_idx = lang_keys.index(self.config.source_lang) if self.config.source_lang in lang_keys else 0
        self.src_lang_var = ctk.StringVar(value=lang_display[src_idx])
        ctk.CTkOptionMenu(left, variable=self.src_lang_var, values=lang_display).pack(fill="x", pady=2)

        right = ctk.CTkFrame(lang_frame, fg_color="transparent")
        right.pack(side="right", expand=True, fill="x", padx=(5, 0))
        ctk.CTkLabel(right, text="Translate To", font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        tgt_idx = lang_keys.index(self.config.target_lang) if self.config.target_lang in lang_keys else 1
        self.tgt_lang_var = ctk.StringVar(value=lang_display[tgt_idx])
        ctk.CTkOptionMenu(right, variable=self.tgt_lang_var, values=lang_display).pack(fill="x", pady=2)

        # --- Status ---
        self.status_label = ctk.CTkLabel(main, text="", text_color="red")
        self.status_label.pack(pady=(2, 0))

        # --- Start Button ---
        ctk.CTkButton(
            main, text="▶  Start Meeting Capture",
            font=ctk.CTkFont(size=15, weight="bold"), height=45,
            command=self._on_start,
        ).pack(fill="x", pady=(8, 0))

        # Apply initial provider visibility (without resetting saved model)
        self._on_provider_change(self.provider_var.get(), initial=True)

    def _get_models(self) -> list[str]:
        for key, info in PROVIDER_REGISTRY.items():
            if info["name"] == self.provider_var.get():
                return info["models"]
        return ["local-model"]

    def _resolve_provider_key(self, display_name: str) -> str:
        for key, info in PROVIDER_REGISTRY.items():
            if info["name"] == display_name:
                return key
        return "openai"

    def _on_provider_change(self, selection: str, initial: bool = False):
        new_key = self._resolve_provider_key(selection)

        # Save current provider's API key before switching
        if not initial and self._current_provider_key != new_key:
            current_typed = self.key_entry.get().strip()
            if current_typed:
                self.config.api_keys[self._current_provider_key] = current_typed

        self._current_provider_key = new_key
        needs_key = PROVIDER_REGISTRY.get(new_key, {}).get("needs_key", True)
        is_local = new_key == "lmstudio"

        # Show/hide entire section frames
        if needs_key:
            self.key_section.pack(fill="x", before=self.model_label)
        else:
            self.key_section.pack_forget()

        if is_local:
            self.url_section.pack(fill="x", after=self.model_menu)
        else:
            self.url_section.pack_forget()

        # Load saved key for new provider
        if not initial:
            self.key_entry.delete(0, "end")
            saved_key = self.config.api_keys.get(new_key, "")
            if saved_key:
                self.key_entry.insert(0, saved_key)

        # Update model list, keep saved model if valid
        models = PROVIDER_REGISTRY.get(new_key, {}).get("models", ["local-model"])
        self.model_menu.configure(values=models)
        if self.model_var.get() not in models:
            default_model = PROVIDER_REGISTRY.get(new_key, {}).get("default_model", models[0])
            self.model_var.set(default_model)

    def _on_start(self):
        lang_keys = list(LANGUAGES.keys())
        lang_display = [LANGUAGES[k] for k in LANGUAGES]

        provider_key = self._resolve_provider_key(self.provider_var.get())

        platform_key = "teams"
        for key, name in PLATFORM_REGISTRY.items():
            if name == self.platform_var.get():
                platform_key = key
                break

        # Save current API key to per-provider dict
        api_key = self.key_entry.get().strip()
        needs_key = PROVIDER_REGISTRY.get(provider_key, {}).get("needs_key", True)

        if needs_key:
            if api_key:
                self.config.api_keys[provider_key] = api_key
            else:
                env_key = PROVIDER_REGISTRY.get(provider_key, {}).get("env_key", "")
                env_val = os.environ.get(env_key, "") if env_key else ""
                if not env_val:
                    self.status_label.configure(
                        text=f"API Key required. Set {env_key} env var or enter key above."
                    )
                    return

        src_idx = lang_display.index(self.src_lang_var.get()) if self.src_lang_var.get() in lang_display else 0
        tgt_idx = lang_display.index(self.tgt_lang_var.get()) if self.tgt_lang_var.get() in lang_display else 1

        self.config.ai_provider = provider_key
        self.config.api_base_url = self.url_entry.get().strip()
        self.config.model_name = self.model_var.get()
        self.config.platform = platform_key
        self.config.source_lang = lang_keys[src_idx]
        self.config.target_lang = lang_keys[tgt_idx]

        self.config.save()
        self.result = self.config
        self.destroy()

    def run(self) -> AppConfig | None:
        self.mainloop()
        return self.result
