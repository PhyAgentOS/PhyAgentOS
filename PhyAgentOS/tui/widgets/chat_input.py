"""Chat input widget."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.message import Message
from textual.widgets import Button, Input


class ChatInput(Horizontal):
    """Chat input with submit button."""

    class Submitted(Message):
        """Emitted when user submits a message."""

        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text

    def compose(self) -> ComposeResult:
        yield Input(placeholder="Type your message... (Enter to send)", id="chat-input-field")
        yield Button("Send", variant="primary", id="chat-send-btn")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle Enter key."""
        self._submit()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle send button click."""
        if event.button.id == "chat-send-btn":
            self._submit()

    def _submit(self) -> None:
        """Submit the current input."""
        input_field = self.query_one("#chat-input-field", Input)
        text = input_field.value.strip()
        if text:
            self.post_message(self.Submitted(text))
            input_field.value = ""

    def focus_input(self) -> None:
        """Focus the input field."""
        input_field = self.query_one("#chat-input-field", Input)
        input_field.focus()
