from .base import LLMProvider


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        self._genai = genai
        self._model_name = model
        self.model = genai.GenerativeModel(model)

    def chat(self, system, user, temperature=0.2, max_tokens=None, timeout=45):
        model = self._genai.GenerativeModel(
            self._model_name, system_instruction=system
        )
        gen_config = self._genai.types.GenerationConfig(temperature=temperature)
        if max_tokens:
            gen_config.max_output_tokens = max_tokens

        response = model.generate_content(user, generation_config=gen_config)
        return response.text

    def is_available(self) -> bool:
        try:
            return self.model is not None
        except Exception:
            return False
