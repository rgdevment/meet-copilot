from .base import LLMProvider


class LMStudioProvider(LLMProvider):
    def __init__(
        self,
        base_url: str = "http://localhost:1234/v1",
        model: str = "local-model",
    ):
        from openai import OpenAI

        self.client = OpenAI(base_url=base_url, api_key="lm-studio")
        self.model = model

    def chat(self, system, user, temperature=0.2, max_tokens=None, timeout=45):
        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "temperature": temperature,
            "timeout": timeout,
        }
        if max_tokens:
            kwargs["max_tokens"] = max_tokens

        response = self.client.chat.completions.create(**kwargs)
        return response.choices[0].message.content

    def is_available(self) -> bool:
        try:
            self.client.models.list()
            return True
        except Exception:
            return False
