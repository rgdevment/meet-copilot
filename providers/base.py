from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def chat(
        self,
        system: str,
        user: str,
        temperature: float = 0.2,
        max_tokens: int | None = None,
        timeout: int = 45,
    ) -> str:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...
