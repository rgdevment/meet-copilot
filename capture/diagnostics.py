import logging
import os
import time

logger = logging.getLogger(__name__)


def dump_uia_tree(diag_dir: str) -> str | None:
    """Walk the UIA tree of likely meeting windows into a timestamped file.

    Best-effort diagnostic for when Teams/Zoom change their accessibility tree
    and captions stop parsing. Runs its own UIA thread initializer so it is safe
    to call from the GUI thread.
    """
    try:
        import uiautomation as auto
    except Exception:
        logger.warning("UIA dump unavailable: uiautomation not importable", exc_info=True)
        return None

    os.makedirs(diag_dir, exist_ok=True)
    path = os.path.join(diag_dir, f"uia_tree_{time.strftime('%Y-%m-%d_%H-%M-%S')}.txt")

    init = auto.UIAutomationInitializerInThread()
    init.__enter__()
    try:
        auto.uiautomation.SetGlobalSearchTimeout(3)
        root = auto.GetRootControl()
        with open(path, "w", encoding="utf-8") as f:
            f.write(f"UIA tree dump — {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            for win in root.GetChildren():
                name = win.Name or ""
                cls = win.ClassName or ""
                low = name.lower()
                is_target = cls in ("TeamsWebView",) or any(
                    h in low for h in ("teams", "zoom", "meeting", "reunión", "webinar")
                )
                if not is_target or not name:
                    continue
                f.write(f"\n{'=' * 70}\nWINDOW '{name}' Class={cls} PID={win.ProcessId}\n{'=' * 70}\n")
                count = 0
                for control, depth in auto.WalkControl(win, maxDepth=30):
                    count += 1
                    ct = control.ControlTypeName or ""
                    cn = (control.Name or "")[:150]
                    indent = "  " * min(depth, 15)
                    if ct == "GroupControl":
                        kids = control.GetChildren()
                        texts = [c for c in kids if c.ControlTypeName == "TextControl"]
                        if len(texts) >= 2:
                            f.write(
                                f"{indent}[Group] CAPTION? speaker='{texts[0].Name}' "
                                f"text='{texts[1].Name}'\n"
                            )
                    elif ct in ("TextControl", "ListItemControl", "EditControl") and cn:
                        f.write(f"{indent}[{ct}] '{cn}'\n")
                    if count > 3000:
                        f.write(f"{indent}... truncated at {count}\n")
                        break
        return path
    except Exception:
        logger.warning("UIA dump failed", exc_info=True)
        return None
    finally:
        init.__exit__(None, None, None)
