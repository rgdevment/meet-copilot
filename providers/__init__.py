from config import AppConfig

from .base import LLMProvider


def create_provider(config: AppConfig) -> LLMProvider:
    api_key = config.resolve_api_key()
    provider = config.ai_provider

    if provider == "openai":
        from .openai_provider import OpenAIProvider
        return OpenAIProvider(api_key=api_key, model=config.model_name)

    if provider == "anthropic":
        from .anthropic_provider import AnthropicProvider
        return AnthropicProvider(api_key=api_key, model=config.model_name)

    if provider == "gemini":
        from .gemini_provider import GeminiProvider
        return GeminiProvider(api_key=api_key, model=config.model_name)

    if provider == "lmstudio":
        from .lmstudio_provider import LMStudioProvider
        return LMStudioProvider(base_url=config.api_base_url, model=config.model_name)

    raise ValueError(f"Unknown provider: {provider}")
