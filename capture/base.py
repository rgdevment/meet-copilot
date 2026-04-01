from abc import ABC, abstractmethod


class CaptureSource(ABC):
    @abstractmethod
    def get_caption(self) -> tuple[str | None, str | None]:
        """Returns (speaker_name, caption_text) or (None, None)"""
        ...

    @abstractmethod
    def get_meeting_name(self) -> str | None:
        ...

    @abstractmethod
    def is_available(self) -> bool:
        ...

    def initialize(self):
        pass

    def cleanup(self):
        pass
