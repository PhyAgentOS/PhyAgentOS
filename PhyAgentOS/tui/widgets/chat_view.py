"""Chat message display widget."""

from rich.console import Group, RenderableType
from rich.markdown import Markdown
from rich.text import Text
from textual.app import ComposeResult
from textual.containers import ScrollableContainer
from textual.widgets import Static


class ChatView(ScrollableContainer):
    """Scrollable chat message display."""

    def __init__(self) -> None:
        super().__init__()
        self._messages: list[RenderableType] = []

    def compose(self) -> ComposeResult:
        yield Static("", id="chat-content")

    def add_user_message(self, message: str) -> None:
        """Add a user message to the chat."""
        text = Text("You: ", style="bold #6b8ca8")
        text.append(message)
        self._append(text)

    def add_agent_message(self, message: str) -> None:
        """Add an agent message to the chat."""
        self._append(Group(Text("PhyAgentOS:", style="bold #5c7385"), Markdown(message)))

    def add_progress(self, message: str) -> None:
        """Add a progress hint to the chat."""
        self._append(Text(f"  -> {message}", style="italic #8d97a3"), spacing=False)

    def _append(self, renderable: RenderableType, *, spacing: bool = True) -> None:
        """Append a renderable and refresh the combined chat transcript."""
        if spacing and self._messages:
            self._messages.append(Text(""))
        self._messages.append(renderable)
        self.query_one("#chat-content", Static).update(Group(*self._messages))
        self.call_after_refresh(self.scroll_end, animate=False)

    def clear_messages(self) -> None:
        """Clear all chat messages."""
        self._messages.clear()
        self.query_one("#chat-content", Static).update("")
