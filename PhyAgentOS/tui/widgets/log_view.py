"""Log display widget."""

from datetime import datetime

from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import Static


class LogView(ScrollableContainer):
    """Scrollable log display."""

    MAX_LINES = 1000

    def __init__(self) -> None:
        super().__init__()
        self._lines: list[str] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="log-content")

    def add_log(self, message: str, level: str = "INFO") -> None:
        """Add a log line."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        line = f"[{timestamp}] [{level}] {message}"
        self._lines.append(line)

        # Trim old lines
        if len(self._lines) > self.MAX_LINES:
            self._lines = self._lines[-self.MAX_LINES:]

        # Update display
        content = self.query_one("#log-content", Static)
        content.update("\n".join(self._lines))
        self.scroll_end(animate=False)

    def clear_logs(self) -> None:
        """Clear all logs."""
        self._lines.clear()
        content = self.query_one("#log-content", Static)
        content.update("")
