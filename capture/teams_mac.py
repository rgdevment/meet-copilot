import logging

from .base import CaptureSource

logger = logging.getLogger(__name__)


class TeamsCaptureMac(CaptureSource):
    """
    Teams caption capture for macOS using Accessibility APIs.
    Requires: pyobjc-framework-ApplicationServices, pyobjc-framework-Quartz
    """

    def __init__(self):
        self.window_name = ""
        self._app_ref = None

    def initialize(self):
        try:
            from ApplicationServices import AXIsProcessTrusted

            if not AXIsProcessTrusted():
                logger.warning(
                    "Accessibility permissions required. "
                    "Grant access in System Preferences > Privacy > Accessibility."
                )
        except ImportError:
            logger.error("pyobjc not installed. Run: pip install pyobjc-framework-ApplicationServices")

    def is_available(self) -> bool:
        try:
            import Quartz

            apps = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
            )
            for app in apps:
                owner = app.get("kCGWindowOwnerName", "")
                if "teams" in owner.lower():
                    return True
        except Exception:
            pass
        return False

    def get_meeting_name(self) -> str | None:
        try:
            import Quartz

            apps = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
            )
            for app in apps:
                owner = app.get("kCGWindowOwnerName", "")
                name = app.get("kCGWindowName", "")
                if "teams" in owner.lower() and name:
                    keywords = ["meeting", "reunión", "call"]
                    if any(k in name.lower() for k in keywords):
                        return name
        except Exception:
            pass
        return None

    def get_caption(self) -> tuple[str | None, str | None]:
        try:
            from ApplicationServices import AXUIElementCreateApplication

            teams_pid = self._find_teams_pid()
            if not teams_pid:
                return None, None

            app_ref = AXUIElementCreateApplication(teams_pid)
            captions = self._walk_for_captions(app_ref)
            if captions:
                return captions[-1]
        except Exception as e:
            logger.debug(f"Mac caption read failed: {e}")
        return None, None

    def _find_teams_pid(self) -> int | None:
        try:
            import Quartz

            apps = Quartz.CGWindowListCopyWindowInfo(
                Quartz.kCGWindowListOptionOnScreenOnly, Quartz.kCGNullWindowID
            )
            for app in apps:
                owner = app.get("kCGWindowOwnerName", "")
                if "teams" in owner.lower():
                    return app.get("kCGWindowOwnerPID")
        except Exception:
            pass
        return None

    def _walk_for_captions(self, element) -> list[tuple[str, str]]:
        from ApplicationServices import AXUIElementCopyAttributeValue
        from CoreFoundation import CFArrayGetCount, CFArrayGetValueAtIndex

        results = []
        try:
            err, children = AXUIElementCopyAttributeValue(element, "AXChildren", None)
            if err or not children:
                return results

            count = CFArrayGetCount(children)
            for i in range(count):
                child = CFArrayGetValueAtIndex(children, i)
                err, role = AXUIElementCopyAttributeValue(child, "AXRole", None)
                err, value = AXUIElementCopyAttributeValue(child, "AXValue", None)

                if value and isinstance(value, str) and len(value) > 3:
                    err, desc = AXUIElementCopyAttributeValue(
                        child, "AXDescription", None
                    )
                    speaker = desc if desc and isinstance(desc, str) else None
                    results.append((speaker, value))

                results.extend(self._walk_for_captions(child))
        except Exception:
            pass
        return results
