import logging
import re
import time

from .base import CaptureSource

logger = logging.getLogger(__name__)

# Zoom meeting window classes (NOT the Zoom Workplace home window)
_MEETING_CLASSES = [
    "ConfMultiTabContentWndClass",
    "ZPContentViewWndClass",
]
_MEETING_TITLE_HINTS = ["webinar", "meeting", "reunión", "zoom"]

# Caption panel structure:
# CCReceiverContainerWnd → ZConfCCRecieveWndExClass ("CaptionWindow")
# └─ ListControl ("Closed caption")
#    └─ ListItemControl (name = "Speaker (Room), caption text...")
#       └─ EditControl (name = full caption text)
_CAPTION_WINDOW_CLASS = "ZConfCCRecieveWndExClass"


class ZoomWindowsCapture(CaptureSource):
    def __init__(self):
        import uiautomation as auto

        self._auto = auto
        self._thread_init = None
        self._cached_meeting = None
        self._cached_caption_list = None
        self._cache_ts = 0
        self._cache_ttl = 8
        self.window_name = ""

    def initialize(self):
        if self._thread_init is None:
            self._thread_init = self._auto.UIAutomationInitializerInThread()
            self._thread_init.__enter__()

    def cleanup(self):
        if self._thread_init:
            self._thread_init.__exit__(None, None, None)
            self._thread_init = None
        self._cached_meeting = None
        self._cached_caption_list = None

    def is_available(self) -> bool:
        return self._find_meeting_window() is not None

    def get_meeting_name(self) -> str | None:
        win = self._find_meeting_window()
        return win.Name if win else None

    def get_captions(self) -> list[tuple[str | None, str | None]]:
        caption_list = self._get_caption_list()
        if not caption_list:
            return []

        try:
            items = caption_list.GetChildren()
        except Exception:
            logger.debug("Zoom caption list read failed", exc_info=True)
            return []

        out = []
        for item in items:
            try:
                speaker, text = self._parse_caption_item(item)
            except Exception:
                logger.debug("Zoom caption item parse failed", exc_info=True)
                continue
            if text:
                out.append((speaker, text))
        return out

    def get_caption(self) -> tuple[str | None, str | None]:
        caps = self.get_captions()
        return caps[-1] if caps else (None, None)

    def _find_meeting_window(self):
        auto = self._auto
        now = time.time()

        if self._cached_meeting and (now - self._cache_ts) < self._cache_ttl:
            try:
                if self._cached_meeting.Exists(0, 0):
                    return self._cached_meeting
            except Exception:
                pass
            self._cached_meeting = None

        # Strategy 1: by known meeting class names
        for cls in _MEETING_CLASSES:
            try:
                win = auto.WindowControl(searchDepth=1, ClassName=cls)
                if win.Exists(1, 1):
                    self._cached_meeting = win
                    self._cache_ts = now
                    self.window_name = win.Name or ""
                    return win
            except Exception:
                continue

        # Strategy 2: search by title hints
        try:
            root = auto.GetRootControl()
            for win in root.GetChildren():
                name = (win.Name or "").lower()
                if any(h in name for h in _MEETING_TITLE_HINTS):
                    cls = win.ClassName or ""
                    # Skip the Zoom Workplace home window
                    if cls == "ZPPTMainFrmWndClassEx":
                        continue
                    self._cached_meeting = win
                    self._cache_ts = now
                    self.window_name = win.Name or ""
                    return win
        except Exception:
            pass

        return None

    def _get_caption_list(self):
        auto = self._auto
        now = time.time()

        if self._cached_caption_list and (now - self._cache_ts) < self._cache_ttl:
            try:
                if self._cached_caption_list.Exists(0, 0):
                    return self._cached_caption_list
            except Exception:
                pass
            self._cached_caption_list = None

        meeting = self._find_meeting_window()
        if not meeting:
            return None

        # Direct path: find CaptionWindow by class name
        try:
            caption_win = meeting.WindowControl(
                searchDepth=5, ClassName=_CAPTION_WINDOW_CLASS
            )
            if caption_win.Exists(1, 1):
                lst = caption_win.ListControl(searchDepth=3)
                if lst.Exists(0, 0):
                    self._cached_caption_list = lst
                    self._cache_ts = now
                    return lst
        except Exception:
            pass

        # Fallback: search for any ListControl named "Closed caption"
        try:
            for control, depth in auto.WalkControl(meeting, maxDepth=10):
                if control.ControlTypeName == "ListControl":
                    name = (control.Name or "").lower()
                    if "caption" in name or "subtitle" in name:
                        self._cached_caption_list = control
                        self._cache_ts = now
                        return control
        except Exception:
            pass

        return None

    def _parse_caption_item(self, item) -> tuple[str | None, str | None]:
        speaker = None
        text = None

        # The ListItemControl.Name has format: "Speaker (Room), caption text..."
        item_name = item.Name or ""

        # Try to get the fuller text from the EditControl child
        try:
            children = item.GetChildren()
            for child in children:
                if child.ControlTypeName == "PaneControl":
                    for sub in child.GetChildren():
                        if sub.ControlTypeName == "EditControl":
                            edit_text = sub.Name or ""
                            if len(edit_text) > len(text or ""):
                                text = edit_text
        except Exception:
            pass

        if not text:
            text = item_name

        # Extract speaker from ListItemControl.Name pattern:
        # "Speaker N (Room Name), actual caption text"
        # or "Speaker Name, actual caption text"
        match = re.match(r"^(?:Speaker \d+\s*\([^)]*\)|[^,]{2,40}),\s*(.+)", item_name)
        if match:
            text = text or match.group(1)
            speaker_part = item_name[: match.start(1) - 2]
            # Clean up "Speaker 2 (Room Name)" → just the speaker identifier
            speaker = speaker_part.strip().rstrip(",")

        if text and len(text.strip()) > 2:
            return (speaker, text.strip())
        return (None, None)
