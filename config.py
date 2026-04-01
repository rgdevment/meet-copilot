import json
import os
import sys
from dataclasses import asdict, dataclass, field

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
CONFIG_FILE = os.path.join(BASE_DIR, "meets_config.json")
DEFAULT_OUTPUT_DIR = os.path.join(BASE_DIR, "reuniones_logs")

PROVIDER_REGISTRY = {
    "openai": {
        "name": "OpenAI",
        "models": ["gpt-4o-mini", "gpt-4o", "gpt-4.1-mini", "gpt-4.1-nano"],
        "default_model": "gpt-4o-mini",
        "needs_key": True,
        "env_key": "OPENAI_API_KEY",
    },
    "anthropic": {
        "name": "Anthropic",
        "models": [
            "claude-sonnet-4-20250514",
            "claude-3-5-haiku-20241022",
        ],
        "default_model": "claude-sonnet-4-20250514",
        "needs_key": True,
        "env_key": "ANTHROPIC_API_KEY",
    },
    "gemini": {
        "name": "Google Gemini",
        "models": [
            "gemini-2.0-flash",
            "gemini-2.5-flash-preview-04-17",
            "gemini-2.5-pro-preview-03-25",
        ],
        "default_model": "gemini-2.0-flash",
        "needs_key": True,
        "env_key": "GOOGLE_API_KEY",
    },
    "lmstudio": {
        "name": "LM Studio (Local)",
        "models": ["local-model"],
        "default_model": "local-model",
        "needs_key": False,
        "env_key": None,
    },
}

PLATFORM_REGISTRY = {
    "auto": "Auto-detect",
    "teams": "Microsoft Teams",
    "zoom": "Zoom",
}

CAPTURE_DEFAULTS = {
    "word_threshold": 350,
    "silence_timeout": 20,
    "min_words_for_timeout": 50,
    "context_overlap": 150,
    "fuzzy_threshold": 0.80,
}

MAX_RETRIES = 3
RETRY_DELAY = 5

EXCLUDED_SPEAKERS = ["Usuario desconocido", "Unknown User"]


@dataclass
class AppConfig:
    ai_provider: str = "openai"
    api_keys: dict = field(default_factory=dict)
    api_base_url: str = "http://localhost:1234/v1"
    model_name: str = "gpt-4o-mini"
    platform: str = "auto"
    source_lang: str = "es"
    target_lang: str = "en"
    output_dir: str = ""

    def __post_init__(self):
        if not self.output_dir:
            self.output_dir = DEFAULT_OUTPUT_DIR

    def resolve_api_key(self) -> str:
        key = self.api_keys.get(self.ai_provider, "")
        if key:
            return key
        provider_info = PROVIDER_REGISTRY.get(self.ai_provider, {})
        env_key = provider_info.get("env_key")
        if env_key:
            return os.environ.get(env_key, "")
        return ""

    def save(self):
        data = asdict(self)
        with open(CONFIG_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @classmethod
    def load(cls) -> "AppConfig":
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # Migrate old single api_key -> per-provider api_keys
                migrated = False
                if "api_key" in data:
                    old_key = data.pop("api_key", "")
                    if old_key and "api_keys" not in data:
                        provider = data.get("ai_provider", "openai")
                        data["api_keys"] = {provider: old_key}
                    migrated = True
                valid = {k: v for k, v in data.items() if k in cls.__dataclass_fields__}
                instance = cls(**valid)
                if migrated:
                    instance.save()
                return instance
            except Exception:
                pass
        return cls()

    @staticmethod
    def is_windows() -> bool:
        return sys.platform == "win32"

    @staticmethod
    def is_mac() -> bool:
        return sys.platform == "darwin"
