from .base import LLMProvider


class AnthropicProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        import anthropic

        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def chat(self, system, user, temperature=0.2, max_tokens=None, timeout=45):
        response = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens or 4096,
            system=system,
            messages=[{"role": "user", "content": user}],
            temperature=temperature,
            timeout=timeout,
        )
        return response.content[0].text

    def is_available(self) -> bool:
        try:
            return bool(self.client.api_key)
        except Exception:
            return False
