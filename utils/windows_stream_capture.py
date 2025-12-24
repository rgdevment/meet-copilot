import uiautomation as auto
import re
import time
from collections import deque
from rich.console import Console
from rich.panel import Panel
from rich.layout import Layout
from rich.live import Live
from rich.text import Text

class MeetingContextManager:
    def __init__(self, block_duration=60, live_limit=60):
        self.block_duration = block_duration
        self.live_limit = live_limit
        self.start_time = time.time()

        self.master_pending_block = []
        self.minute_history = deque(maxlen=30)
        self.all_words = []
        self.startup_synced = False

        self.committed_word_count = 0
        self.safe_margin = 12

    def _get_raw_data(self):
        window = auto.WindowControl(searchDepth=1, ClassName="LiveCaptionsDesktopWindow")
        if not window.Exists(0, 0): return None
        node = window.TextControl(searchDepth=4, ClassName="TextBlock")
        if not node.Exists(0, 0): return None
        return node.Name

    def _sanitize(self, text):
        if not text: return ""
        return re.sub(r'\s+', ' ', text).strip()

    def update(self):
        raw = self._get_raw_data()
        if raw is None: return False

        current_clean = self._sanitize(raw)
        current_tokens = current_clean.split()
        self.all_words = current_tokens

        if not self.startup_synced:
            if len(current_tokens) > 0:
                self.committed_word_count = len(current_tokens)
                self.startup_synced = True
            return True

        if len(current_tokens) > (self.committed_word_count + self.safe_margin):
            new_commit_end = len(current_tokens) - self.safe_margin
            new_safe_words = current_tokens[self.committed_word_count:new_commit_end]

            if new_safe_words:
                self.master_pending_block.extend(new_safe_words)
                self.committed_word_count = new_commit_end

        elif len(current_tokens) < self.committed_word_count:
            self.committed_word_count = 0
            self.master_pending_block.extend(current_tokens)
            self.committed_word_count = len(current_tokens)

        return True

    def check_and_anchor_block(self):
        elapsed = int(time.time() - self.start_time)
        if elapsed >= self.block_duration:
            if self.master_pending_block:
                timestamp = time.strftime('%H:%M')
                block_text = " ".join(self.master_pending_block)
                self.minute_history.appendleft(f"[{timestamp}] {block_text}")
                self.master_pending_block = []

            self.start_time = time.time()
            return True
        return False

    def get_live_view(self):
        return " ".join(self.all_words[-self.live_limit:])

    def get_history_view(self):
        return "\n\n".join(list(self.minute_history))

    def get_remaining_seconds(self):
        elapsed = int(time.time() - self.start_time)
        return max(0, self.block_duration - elapsed)

def run_app():
    manager = MeetingContextManager(block_duration=60, live_limit=60)
    layout = Layout()

    layout.split_column(
        Layout(name="header", size=3),
        Layout(name="live", size=10),
        Layout(name="history", ratio=1)
    )

    with Live(layout, screen=True, refresh_per_second=10) as live:
        try:
            while True:
                if not manager.update():
                    layout["header"].update(Panel("🔍 Searching for Windows Captions...", style="bold red"))
                    time.sleep(1)
                    continue

                manager.check_and_anchor_block()

                layout["header"].update(Panel(
                    Text(f"TECHNICAL ASSISTANT PRO v1.7 | Snapshot in: {manager.get_remaining_seconds()}s | Blocks: {len(manager.minute_history)}", justify="center"),
                    style="bold white on blue"
                ))

                layout["live"].update(Panel(
                    Text(manager.get_live_view(), style="bold green", justify="left"),
                    title="[green]● LIVE STREAM (Safe Commitment)[/green]",
                    border_style="green"
                ))

                layout["history"].update(Panel(
                    manager.get_history_view(),
                    title="[white]ACUMULADOR DE CONTEXTO (Zero Duplication High Fidelity)[/white]",
                    subtitle="Technical blocks secured after stability check",
                    border_style="white"
                ))

                time.sleep(0.05)
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    run_app()

def start_headless_capture(on_block_complete_callback, on_live_update_callback=None):
    """
    Args:
        on_block_complete_callback: Se llama cada 60s con el bloque final.
        on_live_update_callback: Se llama frecuentemente con el texto parcial actual.
    """
    print(f"[Windows Capture] Initializing COM in thread...")
    with auto.UIAutomationInitializerInThread():
        manager = MeetingContextManager(block_duration=60, live_limit=60)

        try:
            while True:
                if not manager.update():
                    time.sleep(1)
                    continue

                # 1. LIVE UPDATE
                if on_live_update_callback:
                    # Envia los ultimos tokens detectados
                    live_text = " ".join(manager.all_words[-30:])
                    on_live_update_callback(live_text)

                # 2. BLOCK COMMIT
                if manager.check_and_anchor_block():
                    raw_block = manager.minute_history[0]
                    clean_text = re.sub(r'^\[\d{2}:\d{2}\]\s+', '', raw_block)
                    on_block_complete_callback(clean_text)

                time.sleep(0.1)

        except KeyboardInterrupt:
            pass
