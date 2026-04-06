"""
Debug script: dump the UI automation tree for the Teams meeting window only.
Run while a Teams meeting is open with captions/subtitles enabled.
"""
import sys

import uiautomation as auto

auto.uiautomation.SetGlobalSearchTimeout(3)

print("=" * 80)
print("Scanning for Teams meeting window (TeamsWebView class)...")
print("=" * 80)

root = auto.GetRootControl()
meeting_win = None

for win in root.GetChildren():
    name = win.Name or ""
    cls = win.ClassName or ""
    lower = name.lower()

    if cls == "TeamsWebView" and "chat" not in lower:
        meeting_win = win
        print(f"  FOUND: '{name}' Class={cls} PID={win.ProcessId}")
        break

if not meeting_win:
    # Fallback: any window with "microsoft teams" in title excluding chat
    for win in root.GetChildren():
        name = win.Name or ""
        lower = name.lower()
        if "microsoft teams" in lower and "chat" not in lower:
            meeting_win = win
            print(f"  FOUND (fallback): '{name}' Class={win.ClassName}")
            break

if not meeting_win:
    print("NO Teams meeting window found.")
    print("\nAll windows:")
    for win in root.GetChildren():
        if win.Name:
            print(f"  '{win.Name[:80]}' | Class='{win.ClassName}'")
    sys.exit(1)

print(f"\n{'='*80}")
print(f"Dumping tree for: '{meeting_win.Name}'")
print(f"{'='*80}\n")

count = 0
group_count = 0
text_count = 0

for control, depth in auto.WalkControl(meeting_win, maxDepth=30):
    count += 1
    ct = control.ControlTypeName or ""
    cn = (control.Name or "")[:150]
    cc = control.ClassName or ""
    aid = control.AutomationId or ""
    indent = "  " * min(depth, 15)

    if ct == "GroupControl":
        group_count += 1
        children = control.GetChildren()
        child_types = [(c.ControlTypeName, (c.Name or "")[:60]) for c in children[:6]]
        print(f"{indent}[Group] children={len(children)}: {child_types}")

        text_kids = [c for c in children if c.ControlTypeName == "TextControl"]
        if len(text_kids) >= 2:
            print(f"{indent}  >>> CAPTION? speaker='{text_kids[0].Name}' text='{text_kids[1].Name}'")

    elif ct == "TextControl":
        text_count += 1
        if cn:
            print(f"{indent}[Text] '{cn}' class='{cc}' aid='{aid}'")

    elif ct == "DocumentControl":
        print(f"{indent}[Document] '{cn}' class='{cc}' aid='{aid}'")

    elif ct == "ListControl":
        print(f"{indent}[List] '{cn}' class='{cc}' aid='{aid}'")

    elif ct == "ListItemControl":
        print(f"{indent}[ListItem] '{cn}' class='{cc}' aid='{aid}'")
        children = control.GetChildren()
        child_types = [(c.ControlTypeName, (c.Name or "")[:60]) for c in children[:6]]
        print(f"{indent}  children={len(children)}: {child_types}")

    elif aid:
        print(f"{indent}[{ct}] '{cn}' class='{cc}' aid='{aid}'")

    if count > 3000:
        print(f"\n... truncated at {count}")
        break

print(f"\nTotal: {count} controls, {group_count} groups, {text_count} texts")

