import logging
import time

from .base import CaptureSource

logger = logging.getLogger(__name__)

# Window class names across Teams versions
_TEAMS_CLASSES = ["TeamsWebView"]
_CAPTION_KEYWORDS = ["subtítulos", "subtitulos", "captions", "subtitles"]
_MEETING_KEYWORDS = ["meeting", "reunión", "call", "llamada", "join"]
_REJECT_KEYWORDS = ["chat", "teams and channels"]
_CAPTION_NOISE = ["Micrófono", "Microphone", "Muted", "Silenciado"]


class TeamsWindowsCapture(CaptureSource):
    def __init__(self):
        import uiautomation as auto

        self._auto = auto
        self._thread_init = None
        self._cached_window = None
        self._cached_web_area = None
        self._cache_ts = 0
        self._cache_ttl = 10
        self.window_name = ""

    def initialize(self):
        if self._thread_init is None:
            self._thread_init = self._auto.UIAutomationInitializerInThread()
            self._thread_init.__enter__()

    def cleanup(self):
        if self._thread_init:
            self._thread_init.__exit__(None, None, None)
            self._thread_init = None
        self._cached_window = None
        self._cached_web_area = None

    def is_available(self) -> bool:
        return self._find_meeting_window() is not None

    def get_meeting_name(self) -> str | None:
        win = self._find_meeting_window()
        if not win:
            return None
        name = win.Name or ""
        # Strip Teams UI prefixes/suffixes from pop-out windows
        for prefix in ["Subtítulos | ", "Subtitulos | ", "Captions | ", "Subtitles | "]:
            if name.startswith(prefix):
                name = name[len(prefix):]
        for suffix in [" | Ventana anclada", " | Pinned window"]:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
        return name.strip() or None

    def get_captions(self) -> list[tuple[str | None, str | None]]:
        web_area = self._get_web_area()
        if not web_area:
            return []
        # No captions right now is normal silence, not a stale cache. The cache
        # is only dropped in _get_web_area when the area stops Exists()-ing.
        return self._extract_captions(web_area)

    def get_caption(self) -> tuple[str | None, str | None]:
        caps = self.get_captions()
        return caps[-1] if caps else (None, None)

    def _find_meeting_window(self):
        auto = self._auto

        try:
            root = auto.GetRootControl()
        except Exception:
            return None

        caption_win = None
        meeting_win = None
        teams_fallback = None

        for win in root.GetChildren():
            try:
                cls = win.ClassName or ""
                if cls not in _TEAMS_CLASSES:
                    continue
                name = win.Name or ""
                name_lower = name.lower()

                if not name_lower or not win.Exists(0, 0):
                    continue

                if "microsoft teams" not in name_lower:
                    continue

                if any(k in name_lower for k in _REJECT_KEYWORDS):
                    continue

                # Prefer caption pop-out window (best source)
                if any(k in name_lower for k in _CAPTION_KEYWORDS):
                    caption_win = win
                    continue

                # Meeting window
                if any(k in name_lower for k in _MEETING_KEYWORDS):
                    meeting_win = win
                    continue

                # Any other Teams window (not chat)
                if teams_fallback is None:
                    teams_fallback = win

            except Exception:
                logger.debug("Teams window scan: skipped a window", exc_info=True)
                continue

        return caption_win or meeting_win or teams_fallback

    def _get_web_area(self):
        auto = self._auto
        now = time.time()

        if self._cached_web_area and (now - self._cache_ts) < self._cache_ttl:
            try:
                if self._cached_web_area.Exists(0, 0):
                    return self._cached_web_area
            except Exception:
                pass
            self._cached_web_area = None

        win = self._find_meeting_window()
        if not win:
            return None

        self.window_name = win.Name or ""

        # Try multiple approaches to find the web content area
        for search_depth in [10, 15, 20]:
            try:
                web_area = win.DocumentControl(
                    searchDepth=search_depth, AutomationId="RootWebArea"
                )
                if web_area.Exists(0, 0):
                    # Verify this web area actually has captions before caching
                    if self._extract_captions(web_area):
                        self._cached_web_area = web_area
                        self._cache_ts = now
                        return web_area
            except Exception:
                logger.debug(
                    "Teams web area search failed at depth %s", search_depth, exc_info=True
                )
                continue

        # Fallback: use the window itself as root (broader search)
        self._cached_web_area = win
        self._cache_ts = now
        return win

    def _extract_captions(self, root):
        candidates = []

        for max_d in [14, 20, 25]:
            try:
                for control, depth in self._auto.WalkControl(root, maxDepth=max_d):
                    try:
                        caption = self._try_parse_caption_group(control)
                        if caption:
                            candidates.append(caption)
                    except Exception:
                        continue
            except Exception:
                logger.debug("Teams caption walk failed at depth %s", max_d, exc_info=True)
                continue

            if candidates:
                break

        return candidates

    def _try_parse_caption_group(self, control):
        if control.ControlTypeName != "GroupControl":
            return None

        children = control.GetChildren()
        if len(children) < 2:
            return None

        text_children = [
            c for c in children if c.ControlTypeName == "TextControl"
        ]
        if len(text_children) < 2:
            return None

        speaker = text_children[0].Name
        caption = text_children[1].Name

        if not caption:
            return None
        if any(noise in caption for noise in _CAPTION_NOISE):
            return None

        return (speaker, caption)
