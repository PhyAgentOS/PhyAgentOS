"""Centered overlay menu widget."""

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Center, Vertical
from textual.message import Message
from textual.widgets import Label, ListItem, ListView, Static


class NavListView(ListView):
    """ListView with ranger-style vim keys (j/k/l)."""

    BINDINGS = [
        Binding("j", "cursor_down", show=False),
        Binding("k", "cursor_up", show=False),
        Binding("l", "select_cursor", show=False),
        Binding("right", "select_cursor", show=False),
    ]


class MenuOverlay(Center):
    """Centered modal menu, toggled with Tab."""

    ITEMS = [
        ("chat", "Chat"),
        ("providers", "Providers"),
        ("channels", "Channels"),
        ("settings", "Settings"),
    ]

    class Selected(Message):
        """Emitted when a menu item is chosen."""

        def __init__(self, name: str) -> None:
            super().__init__()
            self.name = name

    def compose(self) -> ComposeResult:
        with Vertical(id="menu-box"):
            yield Static("MENU", classes="overlay-title")
            yield NavListView(
                *[ListItem(Label(label), id=f"menu-{name}") for name, label in self.ITEMS],
                id="menu-list",
            )

    def on_list_view_selected(self, event: ListView.Selected) -> None:
        item_id = event.item.id or ""
        if item_id.startswith("menu-"):
            self.post_message(self.Selected(item_id[5:]))

    def focus_list(self) -> None:
        self.query_one("#menu-list", NavListView).focus()
