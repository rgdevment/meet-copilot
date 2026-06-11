from abc import ABC, abstractmethod


class CaptureSource(ABC):
    @abstractmethod
    def get_caption(self) -> tuple[str | None, str | None]:
        """Returns (speaker_name, caption_text) or (None, None)"""
        ...

    def get_captions(self) -> list[tuple[str | None, str | None]]:
        """Returns every visible caption line this frame.

        Default wraps get_caption(); platform sources override to return all
        visible nodes so intermediate speakers are not lost between polls.
        """
        speaker, text = self.get_caption()
        return [(speaker, text)] if text else []

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
