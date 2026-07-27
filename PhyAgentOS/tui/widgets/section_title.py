"""Refined section title widget."""

from textual.app import ComposeResult
from textual.containers import Horizontal
from textual.widgets import Static


class SectionTitle(Horizontal):
    """Uppercase bold title with an accent bar and a hairline rule below."""

    def __init__(self, text: str) -> None:
        super().__init__(classes="section-title")
        self._text = text

    def compose(self) -> ComposeResult:
        yield Static("", classes="title-bar")
        yield Static(self._text.upper(), classes="title-text")
